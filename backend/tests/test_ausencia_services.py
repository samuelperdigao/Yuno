import asyncio
import sys
from datetime import datetime, timedelta, timezone
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
from app.domain_modules.ausencia import services  # noqa: E402
from app.domain_modules.ausencia.models import AbsenceRecord  # noqa: E402
from app.domain_modules.ausencia.schemas import AusenciaConfig  # noqa: E402
from app.platform.models import (  # noqa: E402
    DeliveryOutbox,
    ModuleConfigVersion,
    ModuleInstance,
    ModuleLifecycle,
    RuntimeMode,
)
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
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    return engine, sessions


async def _configure(session, guild_id: str = "100", *, max_dias: int = 7) -> None:
    config = AusenciaConfig(
        panel_channel_id="1001",
        log_channel_id="1002",
        max_dias=max_dias,
    ).model_dump(mode="json")
    instance = ModuleInstance(
        guild_id=guild_id,
        module_key="ausencia",
        lifecycle=ModuleLifecycle.active,
        runtime_mode=RuntimeMode.domain,
        contract_version=1,
        domain_version="1.0.0",
    )
    session.add(instance)
    await session.flush()
    version = ModuleConfigVersion(
        module_instance_id=instance.id,
        guild_id=guild_id,
        module_key="ausencia",
        version=1,
        schema_version=1,
        data=config,
        content_hash="x",
        published_by="1",
    )
    session.add(version)
    await session.flush()
    instance.published_config_version_id = version.id
    await session.commit()


def test_register_absence_creates_record_and_enqueues_deliveries() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session)
                record, config, near_limit = await services.register_absence(
                    session,
                    guild_id="100",
                    actor_id="500",
                    member_display_name="Ana",
                    correlation_id="corr-1",
                    dias=2,
                    motivo="  viagem  ",
                )
                assert record.days == 2
                assert record.reason == "viagem"
                assert near_limit is False
                assert config.max_dias == 7

                deliveries = list(
                    (await session.execute(select(DeliveryOutbox))).scalars()
                )
                renderer_keys = {item.renderer_key for item in deliveries}
                assert renderer_keys == {"ausencia.confirmation", "ausencia.log"}
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_register_absence_overwrites_previous_active_record() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session)
                first, _, _ = await services.register_absence(
                    session,
                    guild_id="100",
                    actor_id="500",
                    member_display_name="Ana",
                    correlation_id="corr-1",
                    dias=2,
                    motivo=None,
                )
                second, _, near_limit = await services.register_absence(
                    session,
                    guild_id="100",
                    actor_id="500",
                    member_display_name="Ana",
                    correlation_id="corr-2",
                    dias=5,
                    motivo="renovando",
                )
                assert second.id == first.id
                assert second.days == 5
                assert second.reason == "renovando"
                assert near_limit is True

                total = list((await session.execute(select(AbsenceRecord))).scalars())
                assert len(total) == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_register_absence_rejects_above_max_days() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session, max_dias=7)
                with pytest.raises(HTTPException) as exc_info:
                    await services.register_absence(
                        session,
                        guild_id="100",
                        actor_id="500",
                        member_display_name="Ana",
                        correlation_id="corr-1",
                        dias=8,
                        motivo=None,
                    )
                assert exc_info.value.status_code == 422
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_list_active_excludes_expired_records() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session)
                now = datetime.now(timezone.utc)
                session.add(
                    AbsenceRecord(
                        guild_id="100",
                        discord_user_id="1",
                        member_display_name="Ativa",
                        days=3,
                        reason=None,
                        started_at=now - timedelta(days=1),
                        ends_at=now + timedelta(days=2),
                    )
                )
                session.add(
                    AbsenceRecord(
                        guild_id="100",
                        discord_user_id="2",
                        member_display_name="Vencida",
                        days=3,
                        reason=None,
                        started_at=now - timedelta(days=5),
                        ends_at=now - timedelta(days=1),
                    )
                )
                await session.commit()

                active = await services.list_active(session, guild_id="100")
                assert [item.discord_user_id for item in active] == ["1"]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_sweep_overdue_notifies_once_and_marks_flag() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session)
                now = datetime.now(timezone.utc)
                session.add(
                    AbsenceRecord(
                        guild_id="100",
                        discord_user_id="1",
                        member_display_name="Vencida",
                        days=3,
                        reason=None,
                        started_at=now - timedelta(days=5),
                        ends_at=now - timedelta(days=1),
                    )
                )
                await session.commit()

                result = await services.sweep_overdue(
                    session, guild_id="100", correlation_id="sweep-1", now=now
                )
                assert result["notified"] == 1

                deliveries = list(
                    (
                        await session.execute(
                            select(DeliveryOutbox).where(
                                DeliveryOutbox.renderer_key == "ausencia.overdue_reminder"
                            )
                        )
                    ).scalars()
                )
                assert len(deliveries) == 1

                record = (await session.execute(select(AbsenceRecord))).scalar_one()
                assert record.overdue_notified is True

                again = await services.sweep_overdue(
                    session, guild_id="100", correlation_id="sweep-2", now=now
                )
                assert again["notified"] == 0
        finally:
            await engine.dispose()

    asyncio.run(run())
