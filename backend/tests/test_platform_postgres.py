"""Teste de concorrencia real, executado somente com banco PostgreSQL de teste explicito."""

# ruff: noqa: E402

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import app.models  # noqa: E402,F401
from app.db import Base  # noqa: E402
from app.domain_modules.farm_tickets import (
    services as farm_ticket_services,  # noqa: E402
)
from app.domain_modules.farm_tickets.domain import (  # noqa: E402
    FarmTicketConflict,
)
from app.domain_modules.farm_tickets.domain import (
    OperationKind as FarmOperationKind,
)
from app.domain_modules.farm_tickets.domain import (
    TicketStatus as FarmTicketStatus,
)
from app.domain_modules.farm_tickets.models import (  # noqa: E402
    FarmTicket,
    FarmTicketAllocation,
    FarmTicketEntry,
    FarmTicketEntryItem,
    FarmTicketEvent,
    FarmTicketObjective,
    FarmTicketPendingOperation,
)
from app.domain_modules.meta import contracts as meta_contracts  # noqa: E402
from app.domain_modules.meta import services as meta_services  # noqa: E402
from app.domain_modules.meta.contracts import (  # noqa: E402
    ActiveGoalForMember,
    GoalCycleSnapshot,
    GoalObjectiveSnapshot,
)
from app.domain_modules.meta.domain import (
    ObjectiveKind as MetaObjectiveKind,  # noqa: E402
)
from app.domain_modules.meta.models import (  # noqa: E402
    MetaCycleParticipant,
    MetaIntegrationEvent,
)
from app.domain_modules.meta.schemas import MetaMemberSnapshotIn  # noqa: E402
from app.domain_modules.registration import (
    services as registration_services,  # noqa: E402
)
from app.domain_modules.registration.domain import (
    OrganizationMemberStatus,  # noqa: E402
)
from app.domain_modules.registration.identity import BaseMemberIdentity  # noqa: E402
from app.domain_modules.registration.schemas import (  # noqa: E402
    RegistrationConfig,
    RegistrationSubmit,
)
from app.domain_modules.tags import services as tag_services  # noqa: E402
from app.domain_modules.tags.domain import (  # noqa: E402
    TagSyncRunMode,
    TagSyncRunStatus,
)
from app.domain_modules.tags.models import TagSyncRun  # noqa: E402
from app.platform.automation import claim_tasks, schedule_task  # noqa: E402
from app.platform.configuration import publish  # noqa: E402
from app.platform.contracts import (  # noqa: E402
    JobDefinition,
    ModuleDefinition,
    ModuleManifest,
)
from app.platform.lifecycle import (  # noqa: E402
    ensure_module_instance,
    update_lifecycle,
)
from app.platform.models import (  # noqa: E402
    ModuleConfigVersion,
    ModuleInstance,
    ModuleLifecycle,  # noqa: E402
    RuntimeMode,
)
from app.platform.registry import (
    discover_domain_modules,  # noqa: E402
    module_registry,  # noqa: E402
)
from app.platform.schemas import ActorContextIn  # noqa: E402

POSTGRES_URL = os.getenv("YUNO_TEST_POSTGRES_URL")


@pytest.mark.skipif(
    not POSTGRES_URL,
    reason="Defina YUNO_TEST_POSTGRES_URL para validar FOR UPDATE SKIP LOCKED em PostgreSQL.",
)
def test_postgres_claim_is_exclusive_between_workers() -> None:
    async def scenario() -> None:
        assert POSTGRES_URL is not None
        schema = f"yuno_platform_test_{uuid4().hex}"
        admin_engine = create_async_engine(POSTGRES_URL)
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(
            POSTGRES_URL,
            connect_args={"server_settings": {"search_path": schema}},
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        definition = ModuleDefinition(
            manifest=ModuleManifest(
                key="pg_claim_test",
                name="PG Claim Test",
                description="Modulo sintetico de concorrencia.",
                domain_version="1",
                runtime_modes=("domain",),
                default_runtime_mode="domain",
            ),
            jobs=(JobDefinition("run"),),
        )
        module_registry.register(definition)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with sessions() as session:
                await ensure_module_instance(
                    session, guild_id="pg-guild", module_key="pg_claim_test"
                )
                await session.commit()
                await update_lifecycle(
                    session,
                    guild_id="pg-guild",
                    module_key="pg_claim_test",
                    actor_id="1",
                    expected=ModuleLifecycle.inactive,
                    target=ModuleLifecycle.active,
                    reason=None,
                    correlation_id="pg-activate",
                )
                await schedule_task(
                    session,
                    guild_id="pg-guild",
                    module_key="pg_claim_test",
                    job_key="run",
                    resource_type="test",
                    resource_id="1",
                    payload={},
                    due_at=datetime.now(timezone.utc),
                    idempotency_key="only-once",
                    correlation_id="pg-job",
                    max_attempts=2,
                )

            async def claim(worker_id: str) -> list[str]:
                async with sessions() as session:
                    return [
                        item.id
                        for item in await claim_tasks(
                            session, worker_id=worker_id, limit=1, lease_seconds=60
                        )
                    ]

            first, second = await asyncio.gather(claim("worker-a"), claim("worker-b"))
            assert len(first) + len(second) == 1
        finally:
            module_registry.unregister("pg_claim_test")
            await engine.dispose()
            async with admin_engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin_engine.dispose()

    asyncio.run(scenario())


@pytest.mark.skipif(
    not POSTGRES_URL,
    reason="Defina YUNO_TEST_POSTGRES_URL para validar locks, indice parcial e eventos de Metas.",
)
def test_postgres_meta_serializes_conflicts_and_keeps_event_sequence_unique() -> None:
    async def scenario() -> None:
        assert POSTGRES_URL is not None
        discover_domain_modules()
        schema = f"yuno_meta_test_{uuid4().hex}"
        admin_engine = create_async_engine(POSTGRES_URL)
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(
            POSTGRES_URL,
            connect_args={"server_settings": {"search_path": schema}},
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async def create_goal(session, *, name: str, admin_id: str) -> dict:
            draft = await meta_services.open_draft(
                session, guild_id="meta-pg-guild", admin_id=admin_id, goal_id=None
            )
            draft = await meta_services.patch_draft(
                session,
                guild_id="meta-pg-guild",
                admin_id=admin_id,
                expected_revision=draft["revision"],
                step="review",
                patch={
                    "name": name,
                    "recurrence": "daily",
                    "timezone": "America/Sao_Paulo",
                    "daily_time": "23:55",
                    "participation": "all_members",
                    "role_ids": [],
                    "objectives": [
                        {
                            "kind": "money",
                            "name": "Dinheiro",
                            "money_amount": "100.00",
                            "item_quantity": None,
                            "unit": None,
                        }
                    ],
                    "notice_text": "Aviso PostgreSQL",
                },
            )
            return await meta_services.submit_draft(
                session,
                guild_id="meta-pg-guild",
                admin_id=admin_id,
                expected_revision=draft["revision"],
                correlation_id=f"create:{admin_id}",
            )

        member = [
            MetaMemberSnapshotIn(
                member_id="42", display_name="Membro 42", role_ids=["10"]
            )
        ]
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with sessions() as session:
                older = await create_goal(session, name="Antiga", admin_id="900")
                newer = await create_goal(session, name="Nova", admin_id="901")
                older_prepared = await meta_services.prepare_launch(
                    session,
                    guild_id="meta-pg-guild",
                    goal_id=older["id"],
                    members=member,
                    notice_channel_id="500",
                    causation_id="prepare:old",
                )
                newer_prepared = await meta_services.prepare_launch(
                    session,
                    guild_id="meta-pg-guild",
                    goal_id=newer["id"],
                    members=member,
                    notice_channel_id="500",
                    causation_id="prepare:new",
                )

            async def activate(cycle_id: int, message_id: str, causation_id: str):
                async with sessions() as session:
                    return await meta_services.activate_cycle(
                        session,
                        guild_id="meta-pg-guild",
                        cycle_id=cycle_id,
                        members=member,
                        notice_channel_id="500",
                        notice_message_id=message_id,
                        causation_id=causation_id,
                    )

            await asyncio.gather(
                activate(older_prepared["cycle"]["id"], "600", "activate:old"),
                activate(newer_prepared["cycle"]["id"], "601", "activate:new"),
            )

            async with sessions() as session:
                active = await meta_contracts.get_active_goal_for_member(
                    session, guild_id="meta-pg-guild", member_id="42"
                )
                assert active and active.goal_id == newer["id"]
                active_count = int(
                    await session.scalar(
                        select(func.count(MetaCycleParticipant.id)).where(
                            MetaCycleParticipant.guild_id == "meta-pg-guild",
                            MetaCycleParticipant.member_id == "42",
                            MetaCycleParticipant.active.is_(True),
                        )
                    )
                    or 0
                )
                assert active_count == 1
                sequences = list(
                    (
                        await session.execute(
                            select(MetaIntegrationEvent.sequence)
                            .where(MetaIntegrationEvent.guild_id == "meta-pg-guild")
                            .order_by(MetaIntegrationEvent.sequence)
                        )
                    ).scalars()
                )
                assert sequences == list(range(1, len(sequences) + 1))
                index_definition = await session.scalar(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE schemaname = current_schema() "
                        "AND indexname = 'uq_meta_active_participant'"
                    )
                )
                assert index_definition and "WHERE (active = true)" in index_definition
        finally:
            await engine.dispose()
            async with admin_engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin_engine.dispose()

    asyncio.run(scenario())


@pytest.mark.skipif(
    not POSTGRES_URL,
    reason="Defina YUNO_TEST_POSTGRES_URL para validar indices parciais do Registro.",
)
def test_postgres_registration_partial_indexes_and_concurrent_approvers() -> None:
    async def scenario() -> None:
        assert POSTGRES_URL is not None
        schema = f"yuno_registration_test_{uuid4().hex}"
        admin_engine = create_async_engine(POSTGRES_URL)
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(
            POSTGRES_URL,
            connect_args={"server_settings": {"search_path": schema}},
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with sessions() as session:
                instance = ModuleInstance(
                    guild_id="registration-guild",
                    module_key="registration",
                    lifecycle=ModuleLifecycle.active,
                    runtime_mode=RuntimeMode.domain,
                    contract_version=1,
                    domain_version="2.0.0",
                )
                session.add(instance)
                await session.flush()
                version = ModuleConfigVersion(
                    module_instance_id=instance.id,
                    guild_id="registration-guild",
                    module_key="registration",
                    version=1,
                    schema_version=1,
                    data=RegistrationConfig(
                        panel_channel_id="1",
                        approval_channel_id="2",
                        log_channel_id="3",
                        member_role_id="4",
                    ).model_dump(mode="json"),
                    content_hash="b" * 64,
                    published_by="1",
                )
                session.add(version)
                await session.flush()
                instance.published_config_version_id = version.id
                await session.commit()

            async def submit(user_id: str, player_id: str):
                async with sessions() as session:
                    try:
                        return await registration_services.submit_request(
                            session,
                            guild_id="registration-guild",
                            actor_id=user_id,
                            correlation_id=f"submit-{user_id}-{uuid4()}",
                            data=RegistrationSubmit(name=f"Membro {user_id}", player_id=player_id),
                        )
                    except HTTPException as exc:
                        return exc.status_code

            same_user = await asyncio.gather(submit("10", "100"), submit("10", "101"))
            assert sum(not isinstance(value, int) for value in same_user) == 1
            assert 409 in same_user

            first, second = await asyncio.gather(submit("20", "888"), submit("21", "888"))
            assert not isinstance(first, int) and not isinstance(second, int)

            async def claim(request_id: str, actor_id: str):
                async with sessions() as session:
                    try:
                        item, _ = await registration_services.claim_approval(
                            session,
                            guild_id="registration-guild",
                            request_id=request_id,
                            actor_id=actor_id,
                            correlation_id=f"claim-{actor_id}",
                        )
                        return item.id
                    except HTTPException as exc:
                        return exc.status_code

            competing_ids = await asyncio.gather(
                claim(first.id, "900"), claim(second.id, "901")
            )
            assert sum(isinstance(value, str) for value in competing_ids) == 1
            assert 409 in competing_ids

            third = await submit("30", "999")
            same_request = await asyncio.gather(
                claim(third.id, "902"), claim(third.id, "903")
            )
            assert sum(isinstance(value, str) for value in same_request) == 1
            assert 409 in same_request
        finally:
            await engine.dispose()
            async with admin_engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin_engine.dispose()

    asyncio.run(scenario())


@pytest.mark.skipif(
    not POSTGRES_URL,
    reason="Defina YUNO_TEST_POSTGRES_URL para validar runs e publicacoes concorrentes de Tags.",
)
def test_postgres_tags_keeps_one_active_run_during_concurrent_publish() -> None:
    async def scenario() -> None:
        assert POSTGRES_URL is not None
        discover_domain_modules()
        schema = f"yuno_tags_test_{uuid4().hex}"
        admin_engine = create_async_engine(POSTGRES_URL)
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(
            POSTGRES_URL,
            connect_args={"server_settings": {"search_path": schema}},
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with sessions() as session:
                await tag_services.upsert_draft_binding(
                    session,
                    guild_id="tags-guild",
                    discord_role_id="10",
                    tag="[MEM]",
                    enabled=True,
                    actor_id="900",
                    expected_revision=0,
                    expected_published_version=0,
                    correlation_id="draft-1",
                )
                await publish(
                    session,
                    guild_id="tags-guild",
                    module_key="tags",
                    actor_id="900",
                    expected_revision=1,
                    expected_published_version=0,
                    grants=[],
                    correlation_id="publish-1",
                )
                await update_lifecycle(
                    session,
                    guild_id="tags-guild",
                    module_key="tags",
                    actor_id="900",
                    expected=ModuleLifecycle.inactive,
                    target=ModuleLifecycle.active,
                    reason=None,
                    correlation_id="activate",
                )

            async def create_run(correlation: str):
                async with sessions() as session:
                    return await tag_services.create_sync_run(
                        session,
                        guild_id="tags-guild",
                        mode=TagSyncRunMode.effective,
                        reason="concurrent",
                        actor_id="900",
                        correlation_id=correlation,
                    )

            first_run, second_run = await asyncio.gather(
                create_run("run-a"), create_run("run-b")
            )
            assert first_run.id == second_run.id

            async with sessions() as session:
                await tag_services.upsert_draft_binding(
                    session,
                    guild_id="tags-guild",
                    discord_role_id="10",
                    tag="[NOVO]",
                    enabled=True,
                    actor_id="900",
                    expected_revision=1,
                    expected_published_version=1,
                    correlation_id="draft-2",
                )

            async def publish_latest(actor_id: str):
                async with sessions() as session:
                    try:
                        return await publish(
                            session,
                            guild_id="tags-guild",
                            module_key="tags",
                            actor_id=actor_id,
                            expected_revision=2,
                            expected_published_version=1,
                            grants=[],
                            correlation_id=f"publish-{actor_id}",
                        )
                    except HTTPException as exc:
                        return exc.status_code

            publications = await asyncio.gather(
                publish_latest("901"), publish_latest("902")
            )
            assert sum(not isinstance(item, int) for item in publications) == 1
            assert 409 in publications

            async with sessions() as session:
                active_count = int(
                    await session.scalar(
                        select(func.count(TagSyncRun.id)).where(
                            TagSyncRun.guild_id == "tags-guild",
                            TagSyncRun.status.in_(
                                [
                                    TagSyncRunStatus.pending,
                                    TagSyncRunStatus.planning,
                                    TagSyncRunStatus.running,
                                ]
                            ),
                        )
                    )
                    or 0
                )
                assert active_count == 1
        finally:
            await engine.dispose()
            async with admin_engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin_engine.dispose()

    asyncio.run(scenario())


@pytest.mark.skipif(
    not POSTGRES_URL,
    reason=(
        "Defina YUNO_TEST_POSTGRES_URL para validar Tickets V2 com locks, "
        "indices parciais, FIFO e corridas reais."
    ),
)
def test_postgres_farm_tickets_serializes_open_operations_fifo_and_admin_races(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        assert POSTGRES_URL is not None
        discover_domain_modules()
        schema = f"yuno_farm_tickets_test_{uuid4().hex}"
        admin_engine = create_async_engine(POSTGRES_URL)
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(
            POSTGRES_URL,
            connect_args={"server_settings": {"search_path": schema}},
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(timezone.utc)
        goal = ActiveGoalForMember(
            goal_id=9001,
            cycle=GoalCycleSnapshot(
                cycle_id=9002,
                goal_id=9001,
                guild_id="farm-pg-guild",
                name="Meta PostgreSQL",
                state="active",
                starts_at=now - timedelta(hours=1),
                ends_at=now + timedelta(days=1),
                timezone="America/Sao_Paulo",
                config_version_id=1,
            ),
            objectives=(
                GoalObjectiveSnapshot(
                    objective_id=9003,
                    kind=MetaObjectiveKind.item,
                    name="Ferro",
                    unit="un",
                    item_quantity="1000",
                    money_amount=None,
                    position=0,
                ),
            ),
        )

        async def identity_reader(
            session, *, guild_id: str, discord_user_id: str
        ) -> BaseMemberIdentity:
            del session
            return BaseMemberIdentity(
                identity_id=str(uuid4()),
                guild_id=guild_id,
                discord_user_id=discord_user_id,
                registered_name=f"Membro {discord_user_id}",
                player_id=discord_user_id,
                status=OrganizationMemberStatus.active,
                base_nickname=f"Membro {discord_user_id} | {discord_user_id}",
                config_version=2,
                fingerprint="f" * 64,
            )

        async def goal_reader(*args, **kwargs) -> ActiveGoalForMember:
            return goal

        async def allow_cycle(*args, **kwargs) -> None:
            return None

        monkeypatch.setattr(farm_ticket_services, "read_base_member_identity", identity_reader)
        monkeypatch.setattr(
            farm_ticket_services.meta_contracts,
            "get_active_goal_for_member",
            goal_reader,
        )
        monkeypatch.setattr(farm_ticket_services, "_assert_cycle_open", allow_cycle)

        def actor(user_id: str) -> ActorContextIn:
            return ActorContextIn(
                guild_id="farm-pg-guild",
                user_id=user_id,
                correlation_id=f"farm-pg:{user_id}:{uuid4().hex[:8]}",
            )

        async def open_member(member_id: str, suffix: str) -> dict:
            async with sessions() as session:
                return await farm_ticket_services.open_ticket(
                    session,
                    guild_id="farm-pg-guild",
                    member_id=member_id,
                    actor=actor(member_id),
                    idempotency_key=f"open:{member_id}:{suffix}",
                )

        async def confirm_entry(
            ticket_id: str, member_id: str, amount: str, suffix: str
        ) -> dict:
            async with sessions() as session:
                ticket = await session.get(FarmTicket, ticket_id)
                objective = await session.scalar(
                    select(FarmTicketObjective).where(
                        FarmTicketObjective.ticket_id == ticket_id
                    )
                )
                operation = await farm_ticket_services.begin_operation(
                    session,
                    guild_id="farm-pg-guild",
                    ticket_id=ticket_id,
                    actor=actor(member_id),
                    expected_version=ticket.revision,
                    idempotency_key=f"entry:{suffix}",
                    interaction_id=f"pg-{suffix}"[:32],
                    kind=FarmOperationKind.CREATE_ENTRY,
                    values=[(objective.id, Decimal(amount))],
                )
                row = await session.get(FarmTicketPendingOperation, operation["id"])
                await session.refresh(ticket)
                claimed = await farm_ticket_services.claim_proof(
                    session,
                    guild_id="farm-pg-guild",
                    ticket_id=ticket_id,
                    operation_id=row.id,
                    actor=actor(member_id),
                    expected_version=ticket.revision,
                    message_id=f"proof-{suffix}",
                    attachment_id=f"attachment-{suffix}",
                    author_id=member_id,
                    channel_id=f"channel-{member_id}",
                    received_at=row.proof_deadline - timedelta(milliseconds=1),
                    filename="proof.png",
                    content_type="image/png",
                    size_bytes=100,
                    source_url="https://cdn.discord.test/proof.png",
                )
                return await farm_ticket_services.confirm_proof(
                    session,
                    guild_id="farm-pg-guild",
                    ticket_id=ticket_id,
                    operation_id=row.id,
                    claim_token=claimed["claim_token"],
                    object_key=f"farm-pg/9002/{ticket_id}/{suffix}/proof",
                    checksum_sha256=(suffix.encode().hex() + "0" * 64)[:64],
                    size_bytes=100,
                    content_type="image/png",
                )

        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)

            first, second = await asyncio.gather(
                open_member("42", "a"), open_member("42", "b")
            )
            assert first["id"] == second["id"]
            ticket_id = first["id"]
            async with sessions() as session:
                assert int(
                    await session.scalar(
                        select(func.count(FarmTicket.id)).where(
                            FarmTicket.guild_id == "farm-pg-guild",
                            FarmTicket.member_id == "42",
                        )
                    )
                    or 0
                ) == 1
                active_binding_index = await session.scalar(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE schemaname = current_schema() "
                        "AND indexname = 'uq_ftv2_active_member_binding'"
                    )
                )
                active_operation_index = await session.scalar(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE schemaname = current_schema() "
                        "AND indexname = 'uq_ftv2_active_operation'"
                    )
                )
                assert active_binding_index and "binding_released_at IS NULL" in active_binding_index
                assert active_operation_index and "AWAITING_PROOF" in active_operation_index

            await confirm_entry(ticket_id, "42", "400", "fifo-1")
            await confirm_entry(ticket_id, "42", "300", "fifo-2")
            async with sessions() as session:
                ticket = await session.get(FarmTicket, ticket_id)
                objective = await session.scalar(
                    select(FarmTicketObjective).where(
                        FarmTicketObjective.ticket_id == ticket_id
                    )
                )
                await farm_ticket_services.withdraw(
                    session,
                    guild_id="farm-pg-guild",
                    ticket_id=ticket_id,
                    actor=actor("900"),
                    expected_version=ticket.revision,
                    idempotency_key="fifo-withdraw-500",
                    values=[(objective.id, Decimal("500"))],
                )
                allocations = list(
                    (
                        await session.execute(
                            select(FarmTicketEntry.number, FarmTicketAllocation.amount)
                            .join(
                                FarmTicketEntryItem,
                                FarmTicketEntryItem.id
                                == FarmTicketAllocation.entry_item_id,
                            )
                            .join(
                                FarmTicketEntry,
                                FarmTicketEntry.id == FarmTicketEntryItem.entry_id,
                            )
                            .where(FarmTicketAllocation.ticket_id == ticket_id)
                            .order_by(FarmTicketEntry.number)
                        )
                    ).all()
                )
                assert allocations == [(1, Decimal("400.000")), (2, Decimal("100.000"))]

            # Duas operacoes partem da mesma revision: o FOR UPDATE deixa uma
            # vencer e a outra observa conflito, sem dois efeitos ativos.
            async with sessions() as session:
                snapshot = await session.get(FarmTicket, ticket_id)
                expected = snapshot.revision
                objective_id = await session.scalar(
                    select(FarmTicketObjective.id).where(
                        FarmTicketObjective.ticket_id == ticket_id
                    )
                )

            async def start_operation(suffix: str):
                async with sessions() as session:
                    return await farm_ticket_services.begin_operation(
                        session,
                        guild_id="farm-pg-guild",
                        ticket_id=ticket_id,
                        actor=actor("42"),
                        expected_version=expected,
                        idempotency_key=f"parallel-operation-{suffix}",
                        interaction_id=f"parallel-{suffix}",
                        kind=FarmOperationKind.CREATE_ENTRY,
                        values=[(objective_id, Decimal("10"))],
                    )

            operation_results = await asyncio.gather(
                start_operation("a"), start_operation("b"), return_exceptions=True
            )
            assert sum(isinstance(item, dict) for item in operation_results) == 1
            assert sum(isinstance(item, FarmTicketConflict) for item in operation_results) == 1
            winner = next(item for item in operation_results if isinstance(item, dict))
            async with sessions() as session:
                row = await session.get(FarmTicketPendingOperation, winner["id"])
                assert await farm_ticket_services.expire_operation(
                    session,
                    guild_id="farm-pg-guild",
                    operation_id=row.id,
                    now=row.proof_deadline + timedelta(seconds=1),
                )

            # Em outro ticket, edicao e recolhimento concorrentes tambem ficam
            # serializados: somente um lado produz efeito.
            raced = await open_member("43", "race")
            await confirm_entry(raced["id"], "43", "100", "race-base")
            async with sessions() as session:
                race_ticket = await session.get(FarmTicket, raced["id"])
                race_expected = race_ticket.revision
                race_objective = await session.scalar(
                    select(FarmTicketObjective).where(
                        FarmTicketObjective.ticket_id == raced["id"]
                    )
                )
                race_entry = await session.scalar(
                    select(FarmTicketEntry).where(
                        FarmTicketEntry.ticket_id == raced["id"],
                        FarmTicketEntry.current_revision > 0,
                    )
                )

            async def race_edit():
                async with sessions() as session:
                    return await farm_ticket_services.begin_operation(
                        session,
                        guild_id="farm-pg-guild",
                        ticket_id=raced["id"],
                        actor=actor("43"),
                        expected_version=race_expected,
                        idempotency_key="race-edit",
                        kind=FarmOperationKind.EDIT_ENTRY,
                        target_entry_id=race_entry.id,
                        values=[(race_objective.id, Decimal("110"))],
                    )

            async def race_withdraw():
                async with sessions() as session:
                    return await farm_ticket_services.withdraw(
                        session,
                        guild_id="farm-pg-guild",
                        ticket_id=raced["id"],
                        actor=actor("900"),
                        expected_version=race_expected,
                        idempotency_key="race-withdraw",
                        values=[(race_objective.id, Decimal("50"))],
                    )

            raced_results = await asyncio.gather(
                race_edit(), race_withdraw(), return_exceptions=True
            )
            assert sum(isinstance(item, dict) for item in raced_results) == 1
            assert sum(isinstance(item, FarmTicketConflict) for item in raced_results) == 1

            # Duas retiradas concorrentes nao podem consumir o mesmo saldo.
            withdrawal_race = await open_member("45", "withdrawal-race")
            await confirm_entry(
                withdrawal_race["id"], "45", "100", "withdrawal-race-base"
            )
            async with sessions() as session:
                withdrawal_ticket = await session.get(
                    FarmTicket, withdrawal_race["id"]
                )
                withdrawal_expected = withdrawal_ticket.revision
                withdrawal_objective = await session.scalar(
                    select(FarmTicketObjective).where(
                        FarmTicketObjective.ticket_id == withdrawal_race["id"]
                    )
                )

            async def parallel_withdraw(suffix: str):
                async with sessions() as session:
                    return await farm_ticket_services.withdraw(
                        session,
                        guild_id="farm-pg-guild",
                        ticket_id=withdrawal_race["id"],
                        actor=actor("900"),
                        expected_version=withdrawal_expected,
                        idempotency_key=f"parallel-withdraw-{suffix}",
                        values=[(withdrawal_objective.id, Decimal("80"))],
                    )

            withdrawals = await asyncio.gather(
                parallel_withdraw("a"),
                parallel_withdraw("b"),
                return_exceptions=True,
            )
            assert sum(isinstance(item, dict) for item in withdrawals) == 1
            assert sum(isinstance(item, FarmTicketConflict) for item in withdrawals) == 1
            async with sessions() as session:
                withdrawal_view = await farm_ticket_services.get_ticket(
                    session,
                    guild_id="farm-pg-guild",
                    ticket_id=withdrawal_race["id"],
                )
                assert withdrawal_view["withdrawn"][withdrawal_objective.id] == "80.000"

            # A aprovacao manual concorrente com a confirmacao que atinge 100%
            # permanece bloqueada pela operacao ativa; somente a automatica vence.
            auto_race = await open_member("44", "auto-approval-race")
            await confirm_entry(auto_race["id"], "44", "900", "auto-race-base")
            async with sessions() as session:
                auto_ticket = await session.get(FarmTicket, auto_race["id"])
                auto_objective = await session.scalar(
                    select(FarmTicketObjective).where(
                        FarmTicketObjective.ticket_id == auto_race["id"]
                    )
                )
                auto_operation = await farm_ticket_services.begin_operation(
                    session,
                    guild_id="farm-pg-guild",
                    ticket_id=auto_race["id"],
                    actor=actor("44"),
                    expected_version=auto_ticket.revision,
                    idempotency_key="auto-race-final-entry",
                    kind=FarmOperationKind.CREATE_ENTRY,
                    values=[(auto_objective.id, Decimal("100"))],
                )
                auto_row = await session.get(
                    FarmTicketPendingOperation, auto_operation["id"]
                )
                await session.refresh(auto_ticket)
                auto_claim = await farm_ticket_services.claim_proof(
                    session,
                    guild_id="farm-pg-guild",
                    ticket_id=auto_race["id"],
                    operation_id=auto_row.id,
                    actor=actor("44"),
                    expected_version=auto_ticket.revision,
                    message_id="auto-race-proof",
                    attachment_id="auto-race-attachment",
                    author_id="44",
                    channel_id="channel-44",
                    received_at=auto_row.proof_deadline - timedelta(milliseconds=1),
                    filename="proof.png",
                    content_type="image/png",
                    size_bytes=100,
                    source_url="https://cdn.discord.test/proof.png",
                )
                await session.refresh(auto_ticket)
                auto_expected = auto_ticket.revision

            async def confirm_auto_race():
                async with sessions() as session:
                    return await farm_ticket_services.confirm_proof(
                        session,
                        guild_id="farm-pg-guild",
                        ticket_id=auto_race["id"],
                        operation_id=auto_row.id,
                        claim_token=auto_claim["claim_token"],
                        object_key=(
                            f"farm-pg/9002/{auto_race['id']}/auto-race/proof"
                        ),
                        checksum_sha256="a" * 64,
                        size_bytes=100,
                        content_type="image/png",
                    )

            async def approve_auto_race():
                async with sessions() as session:
                    return await farm_ticket_services.approve_ticket(
                        session=session,
                        guild_id="farm-pg-guild",
                        ticket_id=auto_race["id"],
                        actor=actor("999"),
                        expected_version=auto_expected,
                        idempotency_key="manual-versus-auto",
                    )

            approval_race = await asyncio.gather(
                confirm_auto_race(), approve_auto_race(), return_exceptions=True
            )
            assert sum(isinstance(item, dict) for item in approval_race) == 1
            assert sum(isinstance(item, FarmTicketConflict) for item in approval_race) == 1
            async with sessions() as session:
                auto_final = await session.get(FarmTicket, auto_race["id"])
                assert auto_final.status == FarmTicketStatus.APPROVED
                assert int(
                    await session.scalar(
                        select(func.count(FarmTicketEvent.id)).where(
                            FarmTicketEvent.ticket_id == auto_race["id"],
                            FarmTicketEvent.event_type
                            == "ticket.approved_automatically",
                        )
                    )
                    or 0
                ) == 1
                assert int(
                    await session.scalar(
                        select(func.count(FarmTicketEvent.id)).where(
                            FarmTicketEvent.ticket_id == auto_race["id"],
                            FarmTicketEvent.event_type == "ticket.approved_manually",
                        )
                    )
                    or 0
                ) == 0

            # Aprovacoes com a mesma revision geram um unico evento/resultado.
            async with sessions() as session:
                approval_ticket = await session.get(FarmTicket, ticket_id)
                approval_expected = approval_ticket.revision

            async def approve(suffix: str):
                async with sessions() as session:
                    return await farm_ticket_services.approve_ticket(
                        session=session,
                        guild_id="farm-pg-guild",
                        ticket_id=ticket_id,
                        actor=actor(f"90{suffix}"),
                        expected_version=approval_expected,
                        idempotency_key=f"parallel-approval-{suffix}",
                    )

            approvals = await asyncio.gather(
                approve("0"), approve("1"), return_exceptions=True
            )
            assert sum(isinstance(item, dict) for item in approvals) == 1
            assert sum(isinstance(item, FarmTicketConflict) for item in approvals) == 1
            async with sessions() as session:
                final = await session.get(FarmTicket, ticket_id)
                assert final.status == FarmTicketStatus.APPROVED
                approved_events = int(
                    await session.scalar(
                        select(func.count(FarmTicketEvent.id)).where(
                            FarmTicketEvent.ticket_id == ticket_id,
                            FarmTicketEvent.event_type == "ticket.approved_manually",
                        )
                    )
                    or 0
                )
                assert approved_events == 1
                sequences = list(
                    (
                        await session.execute(
                            select(FarmTicketEvent.sequence)
                            .where(FarmTicketEvent.ticket_id == ticket_id)
                            .order_by(FarmTicketEvent.sequence)
                        )
                    ).scalars()
                )
                assert sequences == list(range(1, len(sequences) + 1))
        finally:
            await engine.dispose()
            async with admin_engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin_engine.dispose()

    asyncio.run(scenario())
