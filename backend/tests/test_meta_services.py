import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import app.models  # noqa: E402,F401
from app.db import Base  # noqa: E402
from app.domain_modules.meta import contracts, services  # noqa: E402
from app.domain_modules.meta.domain import (  # noqa: E402
    EVENT_GOAL_CYCLE_ENDED,
    EVENT_GOAL_CYCLE_STARTED,
    EVENT_PARTICIPANT_MOVED,
    EVENT_PARTICIPANT_REMOVED,
    GoalEndReason,
    GoalState,
)
from app.domain_modules.meta.models import (  # noqa: E402
    MetaCycle,
    MetaCycleParticipant,
    MetaGoal,
    MetaIntegrationEvent,
)
from app.domain_modules.meta.schemas import MetaMemberSnapshotIn  # noqa: E402
from app.api.platform.meta import _event_out  # noqa: E402
from app.platform.registry import discover_domain_modules  # noqa: E402
from app.platform.models import AutomationTask  # noqa: E402


async def _database():
    discover_domain_modules()
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _members(*ids: str, role: str = "10") -> list[MetaMemberSnapshotIn]:
    return [
        MetaMemberSnapshotIn(member_id=value, display_name=f"Membro {value}", role_ids=[role])
        for value in ids
    ]


async def _create_goal(
    session,
    *,
    guild_id: str = "100",
    admin_id: str = "900",
    name: str = "Meta diaria",
    recurrence: str = "daily",
    participation: str = "all_members",
    role_ids: list[str] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
):
    draft = await services.open_draft(
        session, guild_id=guild_id, admin_id=admin_id, goal_id=None
    )
    data = {
        "name": name,
        "recurrence": recurrence,
        "timezone": "America/Sao_Paulo",
        "daily_time": "23:55" if recurrence == "daily" else None,
        "weekday": 0 if recurrence == "weekly" else None,
        "month_day": 31 if recurrence == "monthly" else None,
        "scheduled_start_at": start.isoformat() if start else None,
        "scheduled_end_at": end.isoformat() if end else None,
        "participation": participation,
        "role_ids": role_ids or [],
        "objectives": [
            {
                "kind": "item",
                "name": "Produto",
                "unit": "unidade",
                "item_quantity": "10.500",
                "money_amount": None,
            },
            {
                "kind": "money",
                "name": "Dinheiro",
                "unit": None,
                "item_quantity": None,
                "money_amount": "100.25",
            },
        ],
        "notice_text": "Entreguem os objetivos deste ciclo.",
    }
    draft = await services.patch_draft(
        session,
        guild_id=guild_id,
        admin_id=admin_id,
        expected_revision=draft["revision"],
        step="review",
        patch=data,
    )
    return await services.submit_draft(
        session,
        guild_id=guild_id,
        admin_id=admin_id,
        expected_revision=draft["revision"],
        correlation_id=f"create:{guild_id}:{admin_id}:{name}",
    )


async def _activate(session, goal: dict, members: list[MetaMemberSnapshotIn]):
    prepared = await services.prepare_launch(
        session,
        guild_id=goal["guild_id"],
        goal_id=goal["id"],
        members=members,
        notice_channel_id="500",
        causation_id=f"prepare:{goal['id']}",
    )
    assert prepared["status"] == "prepared"
    return await services.activate_cycle(
        session,
        guild_id=goal["guild_id"],
        cycle_id=prepared["cycle"]["id"],
        members=members,
        notice_channel_id="500",
        notice_message_id=f"600{goal['id']}",
        causation_id=f"activate:{goal['id']}",
    )


def test_first_recurring_cycle_starts_immediately_and_freezes_mixed_objectives() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                goal = await _create_goal(session)
                before = datetime.now(timezone.utc)
                active = await _activate(session, goal, _members("1", "2"))
                cycle = active["cycle"]
                assert active["status"] == "active"
                assert cycle["starts_at"].replace(tzinfo=timezone.utc) >= before - timedelta(seconds=1)
                assert {item["kind"] for item in cycle["objectives"]} == {"item", "money"}
                assert cycle["objectives"][0]["item_quantity"] == "10.500"
                assert cycle["objectives"][1]["money_amount"] == "100.25"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_role_snapshot_does_not_add_members_mid_cycle() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                goal = await _create_goal(
                    session, participation="roles", role_ids=["10"]
                )
                active = await _activate(session, goal, _members("1", role="10"))
                assert await contracts.is_member_participant(
                    session, guild_id="100", cycle_id=active["cycle"]["id"], member_id="1"
                )
                assert not await contracts.is_member_participant(
                    session, guild_id="100", cycle_id=active["cycle"]["id"], member_id="2"
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_member_exit_removes_and_return_does_not_restore_same_cycle() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                goal = await _create_goal(session)
                active = await _activate(session, goal, _members("1"))
                removed = await services.remove_member(
                    session, guild_id="100", member_id="1", causation_id="left:1"
                )
                assert removed["removed"] is True
                assert not await contracts.is_member_participant(
                    session, guild_id="100", cycle_id=active["cycle"]["id"], member_id="1"
                )
                again = await services.activate_cycle(
                    session,
                    guild_id="100",
                    cycle_id=active["cycle"]["id"],
                    members=_members("1"),
                    notice_channel_id="500",
                    notice_message_id="601",
                    causation_id="retry",
                )
                assert again["status"] == "active"
                assert not await contracts.is_member_participant(
                    session, guild_id="100", cycle_id=active["cycle"]["id"], member_id="1"
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_temporary_zero_participants_keeps_recurrence_enabled() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                goal = await _create_goal(session)
                result = await services.prepare_launch(
                    session,
                    guild_id="100",
                    goal_id=goal["id"],
                    members=[],
                    notice_channel_id="500",
                    causation_id="empty",
                )
                stored = await session.get(MetaGoal, goal["id"])
                assert result["status"] == "temporarily_without_participants"
                assert stored.recurrence_enabled is True
                assert stored.state == GoalState.scheduled
                assert stored.end_reason is None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_partial_conflict_moves_only_overlap_and_keeps_old_recurring() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                old = await _create_goal(session, admin_id="900", name="Antiga")
                old_active = await _activate(session, old, _members("1", "2"))
                # O rascunho e persistente por administrador, mas cada abertura
                # para uma nova Meta precisa gerar uma chave de criacao distinta.
                new = await _create_goal(session, admin_id="900", name="Nova")
                new_active = await _activate(session, new, _members("1"))
                old_goal = await session.get(MetaGoal, old["id"])
                assert old_goal.state == GoalState.active
                assert old_goal.recurrence_enabled is True
                assert not await contracts.is_member_participant(
                    session, guild_id="100", cycle_id=old_active["cycle"]["id"], member_id="1"
                )
                assert await contracts.is_member_participant(
                    session, guild_id="100", cycle_id=old_active["cycle"]["id"], member_id="2"
                )
                assert await contracts.is_member_participant(
                    session, guild_id="100", cycle_id=new_active["cycle"]["id"], member_id="1"
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_total_conflict_by_newer_goal_permanently_disables_old_recurrence() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                old = await _create_goal(session, admin_id="900", name="Antiga")
                old_active = await _activate(session, old, _members("1"))
                new = await _create_goal(session, admin_id="901", name="Nova")
                active = await _activate(session, new, _members("1"))
                stored = await session.get(MetaGoal, old["id"])
                old_cycle = await session.get(MetaCycle, old_active["cycle"]["id"])
                assert stored.state == GoalState.ended
                assert stored.end_reason == GoalEndReason.replaced
                assert stored.recurrence_enabled is False
                assert stored.next_transition_at is None
                assert old_cycle.end_reason == GoalEndReason.replaced
                assert active["ended_notices"][0]["goal_id"] == old["id"]
                notice_tasks = int(
                    await session.scalar(
                        select(func.count(AutomationTask.id)).where(
                            AutomationTask.guild_id == "100",
                            AutomationTask.job_key == "meta.notice.reconcile",
                        )
                    )
                    or 0
                )
                assert notice_tasks == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_public_contracts_are_tenant_safe_and_return_immutable_dtos() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                goal = await _create_goal(session)
                active = await _activate(session, goal, _members("1"))
                cycle_id = active["cycle"]["id"]
                member_goal = await contracts.get_active_goal_for_member(
                    session, guild_id="100", member_id="1"
                )
                cycle = await contracts.get_cycle(session, guild_id="100", cycle_id=cycle_id)
                objectives = await contracts.get_cycle_objectives(
                    session, guild_id="100", cycle_id=cycle_id
                )
                assert member_goal and member_goal.goal_id == goal["id"]
                assert cycle and cycle.cycle_id == cycle_id
                assert cycle.starts_at.utcoffset() == timedelta(0)
                assert cycle.ends_at.utcoffset() == timedelta(0)
                assert objectives and objectives[0].item_quantity == "10.500"
                assert await contracts.get_cycle(session, guild_id="other", cycle_id=cycle_id) is None
                with pytest.raises(Exception):
                    member_goal.goal_id = 99  # type: ignore[misc]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_four_events_are_ordered_correlated_and_deduplicated() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                old = await _create_goal(session, admin_id="900", name="Antiga")
                await _activate(session, old, _members("1"))
                new = await _create_goal(session, admin_id="901", name="Nova")
                await _activate(session, new, _members("1"))
                page = await contracts.read_goal_events(session, guild_id="100")
                types = [item.event_type for item in page.events]
                assert EVENT_GOAL_CYCLE_STARTED in types
                assert EVENT_PARTICIPANT_REMOVED in types
                assert EVENT_PARTICIPANT_MOVED in types
                assert EVENT_GOAL_CYCLE_ENDED in types
                assert [item.sequence for item in page.events] == list(range(1, len(page.events) + 1))
                assert all(item.occurred_at.utcoffset() == timedelta(0) for item in page.events)
                count = int(await session.scalar(select(func.count(MetaIntegrationEvent.event_id))) or 0)
                await services._emit_event(
                    session,
                    guild_id="100",
                    event_type=EVENT_GOAL_CYCLE_STARTED,
                    causation_id="duplicate",
                    deduplication_key=page.events[0].deduplication_key,
                    payload={},
                )
                await session.commit()
                assert int(await session.scalar(select(func.count(MetaIntegrationEvent.event_id))) or 0) == count
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_scheduled_custom_is_editable_but_active_custom_is_read_only() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                now = datetime.now(timezone.utc)
                goal = await _create_goal(
                    session,
                    recurrence="custom",
                    start=now - timedelta(minutes=1),
                    end=now + timedelta(hours=1),
                )
                editable = await services.open_draft(
                    session, guild_id="100", admin_id="901", goal_id=goal["id"]
                )
                assert editable["goal_id"] == goal["id"]
                assert editable["data"]["scheduled_start_at"].endswith("+00:00")
                editable = await services.patch_draft(
                    session,
                    guild_id="100",
                    admin_id="901",
                    expected_revision=editable["revision"],
                    step="review",
                    patch={"name": "Personalizada editada"},
                )
                updated = await services.submit_draft(
                    session,
                    guild_id="100",
                    admin_id="901",
                    expected_revision=editable["revision"],
                    correlation_id="custom:scheduled:edit",
                )
                assert updated["name"] == "Personalizada editada"
                await _activate(session, goal, _members("1"))
                with pytest.raises(HTTPException) as raised:
                    await services.open_draft(
                        session, guild_id="100", admin_id="902", goal_id=goal["id"]
                    )
                assert raised.value.status_code == 409
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_two_admins_can_create_different_goals_and_stale_edit_reloads() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                first = await _create_goal(session, admin_id="900", name="Primeira")
                second = await _create_goal(session, admin_id="901", name="Segunda")
                assert first["id"] != second["id"]
                stale = await services.open_draft(
                    session, guild_id="100", admin_id="902", goal_id=first["id"]
                )
                fresh = await services.open_draft(
                    session, guild_id="100", admin_id="903", goal_id=first["id"]
                )
                fresh = await services.patch_draft(
                    session,
                    guild_id="100",
                    admin_id="903",
                    expected_revision=fresh["revision"],
                    step="review",
                    patch={"name": "Atualizada"},
                )
                await services.submit_draft(
                    session,
                    guild_id="100",
                    admin_id="903",
                    expected_revision=fresh["revision"],
                    correlation_id="fresh",
                )
                stale = await services.patch_draft(
                    session,
                    guild_id="100",
                    admin_id="902",
                    expected_revision=stale["revision"],
                    step="review",
                    patch={"name": "Obsoleta"},
                )
                with pytest.raises(HTTPException) as raised:
                    await services.submit_draft(
                        session,
                        guild_id="100",
                        admin_id="902",
                        expected_revision=stale["revision"],
                        correlation_id="stale",
                    )
                assert raised.value.status_code == 409
                reloaded = await services.get_draft(
                    session, guild_id="100", admin_id="902"
                )
                assert reloaded["data"]["name"] == "Atualizada"
                assert reloaded["step"] == "review"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_prepare_launch_is_idempotent_and_multi_guild_isolated() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                first = await _create_goal(session, guild_id="100", admin_id="900")
                second = await _create_goal(session, guild_id="200", admin_id="900")
                one = await services.prepare_launch(
                    session,
                    guild_id="100",
                    goal_id=first["id"],
                    members=_members("1"),
                    notice_channel_id="500",
                    causation_id="one",
                )
                retry = await services.prepare_launch(
                    session,
                    guild_id="100",
                    goal_id=first["id"],
                    members=_members("1"),
                    notice_channel_id="500",
                    causation_id="retry",
                )
                assert one["cycle"]["id"] == retry["cycle"]["id"]
                await session.execute(
                    delete(AutomationTask).where(
                        AutomationTask.guild_id == "100",
                        AutomationTask.job_key == "meta.goal.launch",
                    )
                )
                await session.commit()
                recovered = await services.reconcile(
                    session, guild_id="100", causation_id="recover:pending"
                )
                assert recovered["launch_pending"] == 1
                assert recovered["launch_tasks"] == 1
                assert await contracts.get_cycle(
                    session, guild_id="200", cycle_id=one["cycle"]["id"]
                ) is None
                assert second["guild_id"] == "200"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_cycle_freezes_name_and_notice_when_future_configuration_changes() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                goal = await _create_goal(session, name="Nome congelado")
                active = await _activate(session, goal, _members("1"))
                draft = await services.open_draft(
                    session, guild_id="100", admin_id="901", goal_id=goal["id"]
                )
                draft = await services.patch_draft(
                    session,
                    guild_id="100",
                    admin_id="901",
                    expected_revision=draft["revision"],
                    step="review",
                    patch={"name": "Proxima Meta", "notice_text": "Aviso futuro"},
                )
                await services.submit_draft(
                    session,
                    guild_id="100",
                    admin_id="901",
                    expected_revision=draft["revision"],
                    correlation_id="future-config",
                )
                detail = await services.get_goal_detail(
                    session, guild_id="100", goal_id=goal["id"]
                )
                assert detail["future_configuration"]["name"] == "Proxima Meta"
                assert active["cycle"]["name"] == "Nome congelado"
                assert active["cycle"]["notice_text"] == "Entreguem os objetivos deste ciclo."
                snapshot = await contracts.get_cycle(
                    session, guild_id="100", cycle_id=active["cycle"]["id"]
                )
                assert snapshot and snapshot.name == "Nome congelado"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_settings_use_optimistic_revision_and_keep_first_value_on_conflict() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                saved = await services.save_settings(
                    session,
                    guild_id="100",
                    notice_channel_id="500",
                    expected_revision=0,
                    actor_id="900",
                    correlation_id="settings:1",
                )
                assert saved["revision"] == 1
                with pytest.raises(HTTPException) as raised:
                    await services.save_settings(
                        session,
                        guild_id="100",
                        notice_channel_id="501",
                        expected_revision=0,
                        actor_id="901",
                        correlation_id="settings:stale",
                    )
                assert raised.value.status_code == 409
                current = await services.get_settings(session, guild_id="100")
                assert current["notice_channel_id"] == "500"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_custom_goal_without_eligible_participants_ends_without_recurrence() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                now = datetime.now(timezone.utc)
                goal = await _create_goal(
                    session,
                    recurrence="custom",
                    start=now - timedelta(minutes=1),
                    end=now + timedelta(hours=1),
                )
                result = await services.prepare_launch(
                    session,
                    guild_id="100",
                    goal_id=goal["id"],
                    members=[],
                    notice_channel_id="500",
                    causation_id="custom-empty",
                )
                stored = await session.get(MetaGoal, goal["id"])
                assert result["status"] == "ended_without_participants"
                assert stored.state == GoalState.ended
                assert stored.next_transition_at is None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_goal_listing_paginates_more_than_discord_option_limit() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                for index in range(26):
                    await _create_goal(
                        session, admin_id=str(1000 + index), name=f"Meta {index:02d}"
                    )
                first = await services.list_goals(
                    session, guild_id="100", page=0, page_size=23
                )
                second = await services.list_goals(
                    session, guild_id="100", page=1, page_size=23
                )
                assert first["total"] == 26
                assert len(first["items"]) == 23
                assert len(second["items"]) == 3
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_active_cycle_notice_reference_is_idempotent_but_not_replaceable() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                goal = await _create_goal(session)
                active = await _activate(session, goal, _members("1"))
                cycle_id = active["cycle"]["id"]
                message_id = f"600{goal['id']}"
                same = await services.record_pending_notice(
                    session,
                    guild_id="100",
                    cycle_id=cycle_id,
                    notice_channel_id="500",
                    notice_message_id=message_id,
                )
                assert same["notice_message_id"] == message_id
                with pytest.raises(HTTPException) as raised:
                    await services.record_pending_notice(
                        session,
                        guild_id="100",
                        cycle_id=cycle_id,
                        notice_channel_id="500",
                        notice_message_id="999",
                    )
                assert raised.value.status_code == 409
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_recovery_recreates_missing_launch_and_overdue_transition_once() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                goal = await _create_goal(session)
                await session.execute(delete(AutomationTask).where(AutomationTask.module_key == "meta"))
                await session.commit()
                await services.reconcile(session, guild_id="100", causation_id="boot:1")
                await services.reconcile(session, guild_id="100", causation_id="boot:2")
                launch_count = int(
                    await session.scalar(
                        select(func.count(AutomationTask.id)).where(
                            AutomationTask.guild_id == "100",
                            AutomationTask.job_key == "meta.goal.launch",
                        )
                    )
                    or 0
                )
                assert launch_count == 1
                active = await _activate(session, goal, _members("1"))
                cycle = await session.get(MetaCycle, active["cycle"]["id"])
                cycle.starts_at = datetime.now(timezone.utc) - timedelta(hours=2)
                cycle.ends_at = datetime.now(timezone.utc) - timedelta(hours=1)
                await session.execute(
                    delete(AutomationTask).where(
                        AutomationTask.guild_id == "100",
                        AutomationTask.job_key == "meta.cycle.transition",
                    )
                )
                await session.commit()
                await services.reconcile(session, guild_id="100", causation_id="boot:3")
                await services.reconcile(session, guild_id="100", causation_id="boot:4")
                transition_count = int(
                    await session.scalar(
                        select(func.count(AutomationTask.id)).where(
                            AutomationTask.guild_id == "100",
                            AutomationTask.job_key == "meta.cycle.transition",
                        )
                    )
                    or 0
                )
                assert transition_count == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_event_reader_validates_cursor_filters_pages_and_freezes_payload() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                goal = await _create_goal(session)
                active = await _activate(session, goal, _members("1"))
                await services.remove_member(
                    session, guild_id="100", member_id="1", causation_id="left:event"
                )
                first = await contracts.read_goal_events(
                    session, guild_id="100", limit=1
                )
                assert first.has_more is True
                assert first.next_sequence == first.events[0].sequence
                filtered = await contracts.read_goal_events(
                    session,
                    guild_id="100",
                    event_types=(EVENT_PARTICIPANT_REMOVED,),
                )
                assert [event.event_type for event in filtered.events] == [EVENT_PARTICIPANT_REMOVED]
                with pytest.raises(TypeError):
                    filtered.events[0].payload["goal_id"] = 999  # type: ignore[index]
                assert _event_out(filtered.events[0])["payload"]["member_id"] == "1"
                with pytest.raises(ValueError):
                    await contracts.read_goal_events(session, guild_id="100", after_sequence=-1)
                with pytest.raises(ValueError):
                    await contracts.read_goal_events(session, guild_id="100", limit=501)
                assert active["cycle"]["id"] > 0
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_older_goal_cannot_take_participant_from_newer_creation_sequence() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                older = await _create_goal(session, admin_id="900", name="Antiga")
                newer = await _create_goal(session, admin_id="901", name="Nova")
                newer_active = await _activate(session, newer, _members("1"))
                older_active = await _activate(session, older, _members("1", "2"))
                assert await contracts.is_member_participant(
                    session,
                    guild_id="100",
                    cycle_id=newer_active["cycle"]["id"],
                    member_id="1",
                )
                assert not await contracts.is_member_participant(
                    session,
                    guild_id="100",
                    cycle_id=older_active["cycle"]["id"],
                    member_id="1",
                )
                assert await contracts.is_member_participant(
                    session,
                    guild_id="100",
                    cycle_id=older_active["cycle"]["id"],
                    member_id="2",
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_recurring_close_applies_future_configuration_and_schedules_next_launch() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                goal = await _create_goal(session, name="Atual")
                active = await _activate(session, goal, _members("1"))
                draft = await services.open_draft(
                    session, guild_id="100", admin_id="901", goal_id=goal["id"]
                )
                draft = await services.patch_draft(
                    session,
                    guild_id="100",
                    admin_id="901",
                    expected_revision=draft["revision"],
                    step="review",
                    patch={"name": "Seguinte"},
                )
                await services.submit_draft(
                    session,
                    guild_id="100",
                    admin_id="901",
                    expected_revision=draft["revision"],
                    correlation_id="next:config",
                )
                closed = await services.close_cycle(
                    session,
                    guild_id="100",
                    cycle_id=active["cycle"]["id"],
                    causation_id="cycle:close",
                )
                stored = await session.get(MetaGoal, goal["id"])
                assert closed["status"] == "ended"
                assert stored.name == "Seguinte"
                assert stored.future_config_version_id is None
                assert stored.state == GoalState.scheduled
                task_count = int(
                    await session.scalar(
                        select(func.count(AutomationTask.id)).where(
                            AutomationTask.guild_id == "100",
                            AutomationTask.job_key == "meta.goal.launch",
                            AutomationTask.resource_id == str(goal["id"]),
                        )
                    )
                    or 0
                )
                assert task_count >= 1
        finally:
            await engine.dispose()

    asyncio.run(run())
