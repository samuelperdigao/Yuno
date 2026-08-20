"""Teste de concorrencia real, executado somente com banco PostgreSQL de teste explicito."""

import asyncio
import os
import sys
from datetime import datetime, timezone
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
from app.platform.automation import claim_tasks, schedule_task  # noqa: E402
from app.platform.contracts import JobDefinition, ModuleDefinition, ModuleManifest  # noqa: E402
from app.platform.lifecycle import ensure_module_instance, update_lifecycle  # noqa: E402
from app.platform.models import ModuleLifecycle  # noqa: E402
from app.platform.registry import module_registry  # noqa: E402
from app.platform.registry import discover_domain_modules  # noqa: E402
from app.domain_modules.registration import services as registration_services  # noqa: E402
from app.domain_modules.registration.schemas import RegistrationConfig, RegistrationSubmit  # noqa: E402
from app.domain_modules.tags import services as tag_services  # noqa: E402
from app.domain_modules.tags.domain import TagSyncRunMode, TagSyncRunStatus  # noqa: E402
from app.domain_modules.tags.models import TagSyncRun  # noqa: E402
from app.platform.configuration import publish  # noqa: E402
from app.platform.models import ModuleConfigVersion, ModuleInstance, RuntimeMode  # noqa: E402


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
