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
from app.domain_modules.anuncio import services  # noqa: E402
from app.domain_modules.anuncio.schemas import AnuncioConfig  # noqa: E402
from app.platform.models import (  # noqa: E402
    AuditEntry,
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


async def _configure(
    session,
    guild_id: str = "100",
    *,
    enabled: bool = True,
    lifecycle: ModuleLifecycle = ModuleLifecycle.active,
) -> None:
    config = AnuncioConfig(
        enabled=enabled,
        channel_id="2001",
        log_channel_id="2002",
    ).model_dump(mode="json")
    instance = ModuleInstance(
        guild_id=guild_id,
        module_key="anuncio",
        lifecycle=lifecycle,
        runtime_mode=RuntimeMode.domain,
        contract_version=1,
        domain_version="1.0.0",
    )
    session.add(instance)
    await session.flush()
    version = ModuleConfigVersion(
        module_instance_id=instance.id,
        guild_id=guild_id,
        module_key="anuncio",
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


def test_publish_announcement_writes_audit_entry() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session)
                config, version = await services.publish_announcement(
                    session,
                    guild_id="100",
                    actor_id="500",
                    correlation_id="corr-1",
                    titulo="  Manutenção agendada  ",
                    conteudo="O servidor fica offline às 3h.",
                    mencionar_everyone=True,
                    anexou_arquivo=False,
                )
                assert config.channel_id == "2001"
                assert version == 1

                entries = list((await session.execute(select(AuditEntry))).scalars())
                assert len(entries) == 1
                entry = entries[0]
                assert entry.action == "anuncio.published"
                assert entry.module_key == "anuncio"
                assert entry.actor_id == "500"
                assert entry.after["titulo"] == "Manutenção agendada"
                assert entry.after["mencionou_everyone"] is True
                assert entry.after["anexou_arquivo"] is False
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_publish_announcement_rejects_empty_title() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session)
                with pytest.raises(HTTPException) as excinfo:
                    await services.publish_announcement(
                        session,
                        guild_id="100",
                        actor_id="500",
                        correlation_id="corr-1",
                        titulo="   ",
                        conteudo="conteúdo válido",
                        mencionar_everyone=False,
                        anexou_arquivo=False,
                    )
                assert excinfo.value.status_code == 422
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_publish_announcement_requires_published_configuration() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                with pytest.raises(HTTPException) as excinfo:
                    await services.publish_announcement(
                        session,
                        guild_id="100",
                        actor_id="500",
                        correlation_id="corr-1",
                        titulo="Aviso",
                        conteudo="conteúdo",
                        mencionar_everyone=False,
                        anexou_arquivo=False,
                    )
                assert excinfo.value.status_code == 409
                assert excinfo.value.detail["code"] == "anuncio.not_configured"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_publish_announcement_rejects_disabled_module() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session, enabled=False)
                with pytest.raises(HTTPException) as excinfo:
                    await services.publish_announcement(
                        session,
                        guild_id="100",
                        actor_id="500",
                        correlation_id="corr-1",
                        titulo="Aviso",
                        conteudo="conteúdo",
                        mencionar_everyone=False,
                        anexou_arquivo=False,
                    )
                assert excinfo.value.status_code == 409
                assert excinfo.value.detail["code"] == "anuncio.disabled"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_effective_configuration_returns_published_data() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session)
                version, config = await services.effective_configuration(
                    session, guild_id="100", require_active=False
                )
                assert version.version == 1
                assert config.channel_id == "2001"
                assert config.log_channel_id == "2002"
        finally:
            await engine.dispose()

    asyncio.run(run())
