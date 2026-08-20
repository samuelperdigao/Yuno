import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import app.models  # noqa: E402,F401
from app.db import Base  # noqa: E402
from app.domain_modules.registration.domain import OrganizationMemberStatus  # noqa: E402
from app.domain_modules.registration.models import OrganizationMember  # noqa: E402
from app.domain_modules.registration.schemas import RegistrationConfig, RegistrationSubmit  # noqa: E402
from app.domain_modules.registration import services as registration_services  # noqa: E402
from app.domain_modules.tags import services  # noqa: E402
from app.domain_modules.tags.domain import MemberDiscordSnapshot, TagSyncRunMode, TagSyncRunStatus, TagSyncState  # noqa: E402
from app.domain_modules.tags.models import (  # noqa: E402
    TagRoleBindingDraft,
    TagRoleBindingVersion,
    TagSyncIntent,
    TagSyncRun,
    TagSyncRunItem,
)
from app.platform.configuration import publish, rollback  # noqa: E402
from app.platform.models import AutomationTask, ModuleConfigVersion, ModuleInstance, ModuleLifecycle, RuntimeMode  # noqa: E402
from app.platform.registry import discover_domain_modules  # noqa: E402


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


async def _registration_identity(session, guild_id="100", user_id="200") -> None:
    instance = ModuleInstance(
        guild_id=guild_id,
        module_key="registration",
        lifecycle=ModuleLifecycle.active,
        runtime_mode=RuntimeMode.domain,
        contract_version=2,
        domain_version="2.0.0",
    )
    session.add(instance)
    await session.flush()
    config = RegistrationConfig(
        panel_channel_id="1001",
        approval_channel_id="1002",
        member_role_id="1003",
        approver_role_ids=["1004"],
    ).model_dump(mode="json")
    version = ModuleConfigVersion(
        module_instance_id=instance.id,
        guild_id=guild_id,
        module_key="registration",
        version=1,
        schema_version=1,
        data=config,
        content_hash="a" * 64,
        published_by="900",
    )
    session.add(version)
    await session.flush()
    instance.published_config_version_id = version.id
    session.add(
        OrganizationMember(
            guild_id=guild_id,
            discord_user_id=user_id,
            player_id_original="6627",
            player_id_normalized="6627",
            name="Mineiro",
            status=OrganizationMemberStatus.active,
        )
    )
    await session.commit()


def test_relational_publish_is_immutable_and_rollback_restores_children() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                draft, first = await services.upsert_draft_binding(
                    session,
                    guild_id="100",
                    discord_role_id="10",
                    tag="[MEM]",
                    enabled=True,
                    actor_id="900",
                    expected_revision=0,
                    expected_published_version=0,
                    correlation_id="draft-1",
                )
                assert first.tag == "[MEM]" and draft.revision == 1
                version1 = await publish(
                    session,
                    guild_id="100",
                    module_key="tags",
                    actor_id="900",
                    expected_revision=1,
                    expected_published_version=0,
                    grants=[],
                    correlation_id="publish-1",
                )
                rows1 = list(
                    (
                        await session.execute(
                            select(TagRoleBindingVersion).where(
                                TagRoleBindingVersion.config_version_id == version1.id
                            )
                        )
                    ).scalars()
                )
                assert [(item.discord_role_id, item.tag) for item in rows1] == [("10", "[MEM]")]

                await services.upsert_draft_binding(
                    session,
                    guild_id="100",
                    discord_role_id="10",
                    tag="[NOVO]",
                    enabled=True,
                    actor_id="900",
                    expected_revision=1,
                    expected_published_version=1,
                    correlation_id="draft-2",
                )
                version2 = await publish(
                    session,
                    guild_id="100",
                    module_key="tags",
                    actor_id="900",
                    expected_revision=2,
                    expected_published_version=1,
                    grants=[],
                    correlation_id="publish-2",
                )
                version3 = await rollback(
                    session,
                    guild_id="100",
                    module_key="tags",
                    actor_id="900",
                    source_version=1,
                    expected_published_version=version2.version,
                    correlation_id="rollback-1",
                )
                restored = list(
                    (
                        await session.execute(
                            select(TagRoleBindingVersion).where(
                                TagRoleBindingVersion.config_version_id == version3.id
                            )
                        )
                    ).scalars()
                )
                draft_rows = list((await session.execute(select(TagRoleBindingDraft))).scalars())
                assert version3.source_version == 1
                assert [item.tag for item in restored] == ["[MEM]"]
                assert [item.tag for item in draft_rows] == ["[MEM]"]
                assert [item.tag for item in rows1] == ["[MEM]"]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_publish_supersedes_active_run_and_reconciles_every_member_again() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _registration_identity(session)
                await services.upsert_draft_binding(
                    session,
                    guild_id="100",
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
                    guild_id="100",
                    module_key="tags",
                    actor_id="900",
                    expected_revision=1,
                    expected_published_version=0,
                    grants=[],
                    correlation_id="publish-1",
                )
                instance = (
                    await session.execute(
                        select(ModuleInstance).where(
                            ModuleInstance.guild_id == "100",
                            ModuleInstance.module_key == "tags",
                        )
                    )
                ).scalar_one()
                instance.lifecycle = ModuleLifecycle.active
                await session.commit()
                old_run = await services.create_sync_run(
                    session,
                    guild_id="100",
                    mode=TagSyncRunMode.effective,
                    reason="manual",
                    actor_id="900",
                    correlation_id="run-old",
                )
                await services.plan_sync_run_batch(
                    session, guild_id="100", run_id=old_run.id
                )

                await services.upsert_draft_binding(
                    session,
                    guild_id="100",
                    discord_role_id="10",
                    tag="[NOVO]",
                    enabled=True,
                    actor_id="900",
                    expected_revision=1,
                    expected_published_version=1,
                    correlation_id="draft-2",
                )
                version = await publish(
                    session,
                    guild_id="100",
                    module_key="tags",
                    actor_id="900",
                    expected_revision=2,
                    expected_published_version=1,
                    grants=[],
                    correlation_id="publish-2",
                )

                runs = list(
                    (
                        await session.execute(
                            select(TagSyncRun).where(TagSyncRun.guild_id == "100")
                        )
                    ).scalars()
                )
                replacement = next(item for item in runs if item.id != old_run.id)
                await session.refresh(old_run)
                old_items = list(
                    (
                        await session.execute(
                            select(TagSyncRunItem).where(TagSyncRunItem.run_id == old_run.id)
                        )
                    ).scalars()
                )
                assert old_run.status == TagSyncRunStatus.cancelled
                assert old_run.cancel_requested_at is not None
                assert {item.state for item in old_items} == {TagSyncState.cancelled}
                assert {item.result_code for item in old_items} == {"superseded_by_config"}
                assert replacement.status == TagSyncRunStatus.pending
                assert replacement.config_version_id == version.id
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_intent_revisions_stale_job_and_successful_completion() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _registration_identity(session)
                await services.upsert_draft_binding(
                    session,
                    guild_id="100",
                    discord_role_id="10",
                    tag="[MEM]",
                    enabled=True,
                    actor_id="900",
                    expected_revision=0,
                    expected_published_version=0,
                    correlation_id="draft",
                )
                await publish(
                    session,
                    guild_id="100",
                    module_key="tags",
                    actor_id="900",
                    expected_revision=1,
                    expected_published_version=0,
                    grants=[],
                    correlation_id="publish",
                )
                tags_instance = (
                    await session.execute(
                        select(ModuleInstance).where(
                            ModuleInstance.guild_id == "100", ModuleInstance.module_key == "tags"
                        )
                    )
                ).scalar_one()
                assert await services.request_member_sync(
                    session,
                    guild_id="100",
                    discord_user_id="200",
                    observed_fingerprint=None,
                    reason="inactive",
                    correlation_id="inactive",
                ) is None
                tags_instance.lifecycle = ModuleLifecycle.active
                await session.commit()

                first = await services.request_member_sync(
                    session,
                    guild_id="100",
                    discord_user_id="200",
                    observed_fingerprint="a" * 64,
                    reason="roles_changed",
                    correlation_id="event-1",
                )
                second = await services.request_member_sync(
                    session,
                    guild_id="100",
                    discord_user_id="200",
                    observed_fingerprint="b" * 64,
                    reason="nickname_changed",
                    correlation_id="event-2",
                )
                assert first.id == second.id and second.desired_revision == 2
                assert len(list((await session.execute(select(AutomationTask))).scalars())) == 2

                snapshot = MemberDiscordSnapshot(
                    guild_id="100",
                    discord_user_id="200",
                    member_found=True,
                    role_ids=("100", "10"),
                    hierarchy_role_ids=("100", "10", "90"),
                    current_nickname="Mineiro | 6627",
                    manage_nicknames=True,
                    bot_top_role_id="90",
                    target_top_role_id="10",
                )
                stale = await services.prepare_member_sync(
                    session,
                    guild_id="100",
                    intent_id=first.id,
                    revision=1,
                    run_item_id=None,
                    snapshot=snapshot,
                )
                assert stale == {"terminal": True, "state": TagSyncState.skipped, "result_code": "stale"}
                prepared = await services.prepare_member_sync(
                    session,
                    guild_id="100",
                    intent_id=first.id,
                    revision=2,
                    run_item_id=None,
                    snapshot=snapshot,
                )
                assert prepared["expected_nickname"] == "[MEM] Mineiro | 6627"
                third = await services.request_member_sync(
                    session,
                    guild_id="100",
                    discord_user_id="200",
                    observed_fingerprint="c" * 64,
                    reason="event_during_io",
                    correlation_id="event-3",
                )
                assert third.desired_revision == 3
                assert third.state == TagSyncState.processing
                assert third.processing_token == prepared["processing_token"]
                delayed = await services.prepare_member_sync(
                    session,
                    guild_id="100",
                    intent_id=first.id,
                    revision=3,
                    run_item_id=None,
                    snapshot=snapshot,
                )
                assert delayed["action"] == "retry_later"
                completed = await services.complete_member_sync(
                    session,
                    guild_id="100",
                    intent_id=first.id,
                    revision=2,
                    processing_token=prepared["processing_token"],
                    run_item_id=None,
                    result="applied",
                    result_code="nickname_updated",
                    applied_nickname_hash="c" * 64,
                )
                assert completed.applied_revision == 2
                assert completed.state == TagSyncState.pending
                prepared_latest = await services.prepare_member_sync(
                    session,
                    guild_id="100",
                    intent_id=first.id,
                    revision=3,
                    run_item_id=None,
                    snapshot=snapshot,
                )
                assert prepared_latest["action"] == "edit_nickname"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_bindings_and_intents_are_isolated_by_guild() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                for guild_id, role_id, tag in (("100", "10", "[A]"), ("101", "11", "[B]")):
                    await services.upsert_draft_binding(
                        session,
                        guild_id=guild_id,
                        discord_role_id=role_id,
                        tag=tag,
                        enabled=True,
                        actor_id="900",
                        expected_revision=0,
                        expected_published_version=0,
                        correlation_id=f"draft-{guild_id}",
                    )
                _, guild_a = await services.list_draft_bindings(session, guild_id="100")
                _, guild_b = await services.list_draft_bindings(session, guild_id="101")
                assert [(item.discord_role_id, item.tag) for item in guild_a] == [("10", "[A]")]
                assert [(item.discord_role_id, item.tag) for item in guild_b] == [("11", "[B]")]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_global_run_pages_only_active_identities_and_cancels_unstarted_items() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _registration_identity(session)
                session.add_all(
                    [
                        OrganizationMember(
                            guild_id="100",
                            discord_user_id="201",
                            player_id_original="6628",
                            player_id_normalized="6628",
                            name="Ativo",
                            status=OrganizationMemberStatus.active,
                        ),
                        OrganizationMember(
                            guild_id="100",
                            discord_user_id="202",
                            player_id_original="6629",
                            player_id_normalized="6629",
                            name="Inativo",
                            status=OrganizationMemberStatus.inactive,
                        ),
                    ]
                )
                await session.commit()
                await services.upsert_draft_binding(
                    session,
                    guild_id="100",
                    discord_role_id="10",
                    tag="[MEM]",
                    enabled=True,
                    actor_id="900",
                    expected_revision=0,
                    expected_published_version=0,
                    correlation_id="draft",
                )
                await publish(
                    session,
                    guild_id="100",
                    module_key="tags",
                    actor_id="900",
                    expected_revision=1,
                    expected_published_version=0,
                    grants=[],
                    correlation_id="publish",
                )
                tags_instance = (
                    await session.execute(
                        select(ModuleInstance).where(
                            ModuleInstance.guild_id == "100", ModuleInstance.module_key == "tags"
                        )
                    )
                ).scalar_one()
                tags_instance.lifecycle = ModuleLifecycle.active
                await session.commit()

                sync_run = await services.create_sync_run(
                    session,
                    guild_id="100",
                    mode=TagSyncRunMode.effective,
                    reason="manual",
                    actor_id="900",
                    correlation_id="run-1",
                )
                same_run = await services.create_sync_run(
                    session,
                    guild_id="100",
                    mode=TagSyncRunMode.effective,
                    reason="hierarchy_changed",
                    actor_id=None,
                    correlation_id="run-2",
                )
                assert same_run.id == sync_run.id
                planned = await services.plan_sync_run_batch(
                    session, guild_id="100", run_id=sync_run.id
                )
                assert planned.total_items == 2
                assert planned.planned_items == 2
                assert planned.status == TagSyncRunStatus.running
                items = list(
                    (
                        await session.execute(
                            select(TagSyncRunItem).where(TagSyncRunItem.run_id == sync_run.id)
                        )
                    ).scalars()
                )
                assert {item.discord_user_id for item in items} == {"200", "201"}

                with pytest.raises(HTTPException) as conflict:
                    await services.create_sync_run(
                        session,
                        guild_id="100",
                        mode=TagSyncRunMode.base_only,
                        reason="cleanup",
                        actor_id="900",
                        correlation_id="cleanup",
                    )
                assert conflict.value.status_code == 409
                cancelled = await services.cancel_sync_run(
                    session,
                    guild_id="100",
                    run_id=sync_run.id,
                    actor_id="900",
                    correlation_id="cancel",
                )
                assert cancelled.cancel_requested_at is not None
                states = set(
                    (
                        await session.execute(
                            select(TagSyncRunItem.state).where(TagSyncRunItem.run_id == sync_run.id)
                        )
                    ).scalars()
                )
                assert states == {TagSyncState.cancelled}
                finalized = await services.finalize_sync_run(
                    session, guild_id="100", run_id=sync_run.id
                )
                assert finalized.status == TagSyncRunStatus.cancelled
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_registration_approval_enqueues_tags_only_after_durable_identity() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                guild_id = "300"
                registration = ModuleInstance(
                    guild_id=guild_id,
                    module_key="registration",
                    lifecycle=ModuleLifecycle.active,
                    runtime_mode=RuntimeMode.domain,
                    contract_version=2,
                    domain_version="2.0.0",
                )
                session.add(registration)
                await session.flush()
                config = RegistrationConfig(
                    panel_channel_id="3001",
                    approval_channel_id="3002",
                    member_role_id="3003",
                    approver_role_ids=["3004"],
                ).model_dump(mode="json")
                version = ModuleConfigVersion(
                    module_instance_id=registration.id,
                    guild_id=guild_id,
                    module_key="registration",
                    version=1,
                    schema_version=1,
                    data=config,
                    content_hash="d" * 64,
                    published_by="900",
                )
                session.add(version)
                await session.flush()
                registration.published_config_version_id = version.id
                await session.commit()

                await services.upsert_draft_binding(
                    session,
                    guild_id=guild_id,
                    discord_role_id="3010",
                    tag="[MEM]",
                    enabled=True,
                    actor_id="900",
                    expected_revision=0,
                    expected_published_version=0,
                    correlation_id="tags-draft",
                )
                await publish(
                    session,
                    guild_id=guild_id,
                    module_key="tags",
                    actor_id="900",
                    expected_revision=1,
                    expected_published_version=0,
                    grants=[],
                    correlation_id="tags-publish",
                )
                tags_instance = (
                    await session.execute(
                        select(ModuleInstance).where(
                            ModuleInstance.guild_id == guild_id,
                            ModuleInstance.module_key == "tags",
                        )
                    )
                ).scalar_one()
                tags_instance.lifecycle = ModuleLifecycle.active
                await session.commit()

                request = await registration_services.submit_request(
                    session,
                    guild_id=guild_id,
                    actor_id="200",
                    correlation_id="submit",
                    data=RegistrationSubmit(name="Mineiro", player_id="6627"),
                    panel_config_version=1,
                )
                claimed, _ = await registration_services.claim_approval(
                    session,
                    guild_id=guild_id,
                    request_id=request.id,
                    actor_id="900",
                    correlation_id="approval",
                )
                token = claimed.processing_token
                await registration_services.record_preflight(
                    session,
                    guild_id=guild_id,
                    request_id=request.id,
                    actor_id="900",
                    operation_token=token,
                    previous_nickname=None,
                    role_was_present=False,
                    target_nickname="Mineiro | 6627",
                    correlation_id="approval",
                )
                for step in ("nickname", "role"):
                    await registration_services.record_discord_step(
                        session,
                        guild_id=guild_id,
                        request_id=request.id,
                        actor_id="900",
                        operation_token=token,
                        step=step,
                        correlation_id="approval",
                    )
                _, member = await registration_services.complete_approval(
                    session,
                    guild_id=guild_id,
                    request_id=request.id,
                    actor_id="900",
                    correlation_id="approval",
                    operation_token=token,
                )
                intent = (
                    await session.execute(
                        select(TagSyncIntent).where(
                            TagSyncIntent.guild_id == guild_id,
                            TagSyncIntent.discord_user_id == "200",
                        )
                    )
                ).scalar_one()
                task = (
                    await session.execute(
                        select(AutomationTask).where(
                            AutomationTask.guild_id == guild_id,
                            AutomationTask.module_key == "tags",
                            AutomationTask.resource_id == intent.id,
                        )
                    )
                ).scalar_one()
                assert member.id
                assert intent.desired_revision == 1
                assert task.payload["reason"] == "registration_approved"
        finally:
            await engine.dispose()

    asyncio.run(run())
