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
from app.domain_modules.adv import services  # noqa: E402
from app.domain_modules.adv.models import Warning  # noqa: E402
from app.domain_modules.adv.schemas import AdvConfig  # noqa: E402
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


async def _configure(session, guild_id: str = "100", *, log_channel_id: str = "1002") -> None:
    config = AdvConfig(
        panel_channel_id="1001",
        log_channel_id=log_channel_id,
        staff_role_ids=["7001"],
    ).model_dump(mode="json")
    instance = ModuleInstance(
        guild_id=guild_id,
        module_key="adv",
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
        module_key="adv",
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


def test_apply_warning_creates_record_and_enqueues_log() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session)
                record, config = await services.apply_warning(
                    session,
                    guild_id="100",
                    moderator_id="500",
                    moderator_display_name="Staff",
                    correlation_id="corr-1",
                    discord_user_id="<@123>",
                    member_display_name="Ana",
                    reason="  spawn de arma proibida  ",
                )
                assert record.discord_user_id == "123"
                assert record.reason == "spawn de arma proibida"
                assert record.revoked_at is None
                assert config.log_channel_id == "1002"

                deliveries = list(
                    (await session.execute(select(DeliveryOutbox))).scalars()
                )
                renderer_keys = {item.renderer_key for item in deliveries}
                assert renderer_keys == {"adv.log"}
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_apply_warning_without_log_channel_skips_delivery() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session, log_channel_id="")
                await services.apply_warning(
                    session,
                    guild_id="100",
                    moderator_id="500",
                    moderator_display_name="Staff",
                    correlation_id="corr-1",
                    discord_user_id="123",
                    member_display_name="Ana",
                    reason="motivo",
                )
                deliveries = list(
                    (await session.execute(select(DeliveryOutbox))).scalars()
                )
                assert deliveries == []
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_apply_warning_rejects_blank_reason() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session)
                with pytest.raises(HTTPException) as exc_info:
                    await services.apply_warning(
                        session,
                        guild_id="100",
                        moderator_id="500",
                        moderator_display_name="Staff",
                        correlation_id="corr-1",
                        discord_user_id="123",
                        member_display_name="Ana",
                        reason="   ",
                    )
                assert exc_info.value.status_code == 422
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_apply_warning_rejects_invalid_target() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session)
                with pytest.raises(HTTPException) as exc_info:
                    await services.apply_warning(
                        session,
                        guild_id="100",
                        moderator_id="500",
                        moderator_display_name="Staff",
                        correlation_id="corr-1",
                        discord_user_id="nao-e-um-id",
                        member_display_name="Ana",
                        reason="motivo",
                    )
                assert exc_info.value.status_code == 422
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_revoke_warning_marks_revoked_once() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session)
                record, _ = await services.apply_warning(
                    session,
                    guild_id="100",
                    moderator_id="500",
                    moderator_display_name="Staff",
                    correlation_id="corr-1",
                    discord_user_id="123",
                    member_display_name="Ana",
                    reason="motivo",
                )
                revoked, _ = await services.revoke_warning(
                    session,
                    guild_id="100",
                    actor_id="999",
                    actor_display_name="Admin",
                    correlation_id="corr-2",
                    warning_id=record.id,
                    reason="aplicada por engano",
                )
                assert revoked.revoked_at is not None
                assert revoked.revoked_by == "999"
                assert revoked.revoke_reason == "aplicada por engano"

                with pytest.raises(HTTPException) as exc_info:
                    await services.revoke_warning(
                        session,
                        guild_id="100",
                        actor_id="999",
                        actor_display_name="Admin",
                        correlation_id="corr-3",
                        warning_id=record.id,
                        reason=None,
                    )
                assert exc_info.value.status_code == 409
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_revoke_warning_rejects_unknown_id() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session)
                with pytest.raises(HTTPException) as exc_info:
                    await services.revoke_warning(
                        session,
                        guild_id="100",
                        actor_id="999",
                        actor_display_name="Admin",
                        correlation_id="corr-1",
                        warning_id="does-not-exist",
                        reason=None,
                    )
                assert exc_info.value.status_code == 404
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_list_recent_orders_newest_first() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session)
                first, _ = await services.apply_warning(
                    session,
                    guild_id="100",
                    moderator_id="500",
                    moderator_display_name="Staff",
                    correlation_id="corr-1",
                    discord_user_id="1",
                    member_display_name="Ana",
                    reason="primeira",
                )
                second, _ = await services.apply_warning(
                    session,
                    guild_id="100",
                    moderator_id="500",
                    moderator_display_name="Staff",
                    correlation_id="corr-2",
                    discord_user_id="2",
                    member_display_name="Bia",
                    reason="segunda",
                )
                recent = await services.list_recent(session, guild_id="100")
                assert [item.id for item in recent][:2] == [second.id, first.id]

                other_guild = list(
                    (
                        await session.execute(
                            select(Warning).where(Warning.guild_id == "other")
                        )
                    ).scalars()
                )
                assert other_guild == []
        finally:
            await engine.dispose()

    asyncio.run(run())
