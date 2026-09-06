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

import app.models  # noqa: F401
from app.db import Base
from app.domain_modules.parceria import services
from app.domain_modules.parceria.domain import ParceriaStatus, PublicationStatus, normalize_family
from app.domain_modules.parceria.models import Parceria, RegistrationAttempt
from app.platform.models import DeliveryOutbox
from app.platform.registry import discover_domain_modules


async def database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_parceria_normalization_is_stable():
    assert normalize_family("  Família   São   José ") == "familia sao jose"
    assert normalize_family("FAMILIA SAO JOSE") == "familia sao jose"


def test_parceria_registration_upload_publication_edit_deactivate_and_isolation():
    async def scenario():
        discover_domain_modules()
        engine, sessions = await database()
        try:
            async with sessions() as session:
                attempt = await services.create_registration_attempt(session, guild_id="guild-a", actor_id="user-a", channel_id="10", family_name="Família Azul", product_name="Produto A", contacts=["contato"], idempotency_key="attempt-1", correlation_id="corr-1")
                same = await services.create_registration_attempt(session, guild_id="guild-a", actor_id="user-a", channel_id="10", family_name="Outro", product_name="Outro", contacts=[], idempotency_key="attempt-1", correlation_id="corr-2")
                assert same.id == attempt.id
                await services.attach_image(session, guild_id="guild-a", attempt_id=attempt.id, actor_id="user-a", channel_id="10", storage_key="s3:guild-a/image-1", storage_url="https://storage.invalid/image-1.webp", content_type="image/webp", size_bytes=1024, checksum="abc", original_filename="logo.webp", correlation_id="corr-2")
                parceria = await services.complete_registration(session, guild_id="guild-a", attempt_id=attempt.id, actor_id="user-a", ativas_channel_id="20", correlation_id="corr-3")
                await session.commit()
                assert parceria.status == ParceriaStatus.publication_pending
                deliveries = list((await session.execute(select(DeliveryOutbox).where(DeliveryOutbox.guild_id == "guild-a"))).scalars())
                assert len(deliveries) == 1
                assert deliveries[0].idempotency_key == f"parceria:guild-a:{parceria.id}:publication:1"
                await services.mark_publication_result(session, guild_id="guild-a", parceria_id=parceria.id, revision=1, status=PublicationStatus.published, channel_id="20", message_id="200", error=None, correlation_id="corr-4")
                await session.commit()
                assert parceria.status == ParceriaStatus.active
                edited = await services.edit_partnership(session, guild_id="guild-a", parceria_id=parceria.id, actor_id="manager", family_name="Família Azul", product_name="Produto B", contacts=["novo"], expected_revision=1, ativas_channel_id="20", correlation_id="corr-5")
                assert edited.status == ParceriaStatus.publication_pending
                assert edited.publication_revision == 2
                deactivated = await services.deactivate_partnership(session, guild_id="guild-a", parceria_id=parceria.id, actor_id="manager", ativas_channel_id="20", expected_revision=2, correlation_id="corr-6")
                assert deactivated.status == ParceriaStatus.inactive
                with pytest.raises(HTTPException) as cross_guild:
                    await services.get_partnership(session, guild_id="guild-b", parceria_id=parceria.id)
                assert cross_guild.value.status_code == 404
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_parceria_expiration_is_persisted_and_idempotent():
    async def scenario():
        discover_domain_modules()
        engine, sessions = await database()
        try:
            async with sessions() as session:
                attempt = await services.create_registration_attempt(session, guild_id="guild-a", actor_id="user-a", channel_id="10", family_name="Família", product_name="Produto", contacts=[], idempotency_key="attempt-expire", correlation_id="corr", expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
                count = await services.expire_attempts(session, guild_id="guild-a", correlation_id="expire")
                again = await services.expire_attempts(session, guild_id="guild-a", correlation_id="expire-again")
                await session.commit()
                assert count == 1
                assert again == 0
                stored = await session.get(RegistrationAttempt, attempt.id)
                assert stored.status.value == "expired"
        finally:
            await engine.dispose()

    asyncio.run(scenario())
