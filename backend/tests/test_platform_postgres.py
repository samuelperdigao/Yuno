"""Teste de concorrencia real, executado somente com banco PostgreSQL de teste explicito."""

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
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
