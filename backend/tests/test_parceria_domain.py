import asyncio
import io
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
from app.domain_modules.parceria import image_processing
from app.domain_modules.parceria.domain import ParceriaStatus, PublicationStatus, normalize_family
from app.domain_modules.parceria.migration import backfill_legacy
from app.domain_modules.parceria.models import Parceria, ParceriaContact, ParceriaImage, ParceriaPublication, RegistrationAttempt
from app.models import Parceria as LegacyParceria, ParceriaConfig as LegacyConfig
from app.platform.models import AutomationTask, DeliveryOutbox, WorkState
from app.platform.registry import discover_domain_modules


async def database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_parceria_normalization_is_stable():
    assert normalize_family("  Família   São   José ") == "familia sao jose"
    assert normalize_family("FAMILIA SAO JOSE") == "familia sao jose"


def test_parceria_attachment_is_validated_by_content_and_uploaded(monkeypatch):
    image = pytest.importorskip("PIL.Image")

    buffer = io.BytesIO()
    image.new("RGB", (2, 2), color="red").save(buffer, format="PNG")
    content = buffer.getvalue()

    class Response:
        url = "https://cdn.discordapp.com/attachments/1/2/logo.png"
        headers = {"content-length": str(len(content)), "content-type": "text/plain"}

        def raise_for_status(self):
            return None

        async def aiter_bytes(self, _chunk_size):
            yield content

    class Stream:
        async def __aenter__(self):
            return Response()

        async def __aexit__(self, *_args):
            return None

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def stream(self, *_args, **_kwargs):
            return Stream()

    monkeypatch.setattr(image_processing.httpx, "AsyncClient", lambda **_kwargs: Client())

    class Storage:
        def __init__(self):
            self.uploads = []

        async def put_file(self, **kwargs):
            self.uploads.append(kwargs)

        async def delete(self, **_kwargs):
            return None

        async def presign_get(self, **_kwargs):
            return "https://storage.invalid/presigned"

        async def head(self, **_kwargs):
            return {}

    async def scenario():
        storage = Storage()
        stored = await image_processing.ingest_discord_attachment(
            storage,
            source_url="https://cdn.discordapp.com/attachments/1/2/logo.png",
            storage_key="parceria/guild-a/registration/attempt-a",
            original_filename="logo.png",
        )
        assert stored.content_type == "image/png"
        assert stored.size_bytes == len(content)
        assert stored.checksum
        assert storage.uploads[0]["key"] == stored.storage_key
        assert storage.uploads[0]["content_type"] == "image/png"

    asyncio.run(scenario())


def test_parceria_attachment_rejects_non_discord_source(monkeypatch):
    class Storage:
        async def put_file(self, **_kwargs):
            raise AssertionError("nao deveria fazer upload")

    async def scenario():
        with pytest.raises(image_processing.InvalidPartnershipImage):
            await image_processing.ingest_discord_attachment(
                Storage(),
                source_url="https://example.invalid/image.png",
                storage_key="parceria/guild-a/registration/attempt-a",
                original_filename="logo.png",
            )

    asyncio.run(scenario())


def test_parceria_registration_upload_publication_edit_deactivate_and_isolation():
    async def scenario():
        discover_domain_modules()
        engine, sessions = await database()
        try:
            async with sessions() as session:
                attempt = await services.create_registration_attempt(session, guild_id="guild-a", actor_id="user-a", channel_id="10", family_name="Família Azul", product_name="Produto A", contacts=["contato"], idempotency_key="attempt-1", correlation_id="corr-1")
                same = await services.create_registration_attempt(session, guild_id="guild-a", actor_id="user-a", channel_id="10", family_name="Outro", product_name="Outro", contacts=[], idempotency_key="attempt-1", correlation_id="corr-2")
                assert same.id == attempt.id
                expiry_task = (await session.execute(select(AutomationTask).where(AutomationTask.resource_id == attempt.id))).scalar_one()
                assert expiry_task.job_key == "parceria.registration.expire"
                assert expiry_task.payload == {"attempt_id": attempt.id}
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


def test_parceria_backfill_preserves_legacy_data_and_is_repeatable():
    async def scenario():
        discover_domain_modules()
        engine, sessions = await database()
        try:
            async with sessions() as session:
                session.add(
                    LegacyConfig(
                        id=1,
                        guild_id="guild-a",
                        category_id="30",
                        registrar_channel_id="10",
                        ativas_channel_id="20",
                        panel_message_id="100",
                    )
                )
                session.add(
                    LegacyParceria(
                        id=7,
                        guild_id="guild-a",
                        nome_familia="Família Azul",
                        nome_familia_normalizado=normalize_family("Família Azul"),
                        produto="Produto A",
                        contato_01="contato-1",
                        contato_02="contato-2",
                        mensagem_lista_id="200",
                        nome_arquivo_imagem="logo.webp",
                        registrado_por="user-a",
                        ativo=True,
                    )
                )
                await session.flush()
                report = await backfill_legacy(session, guild_id="guild-a", correlation_id="migration-1")
                await session.commit()
                assert report["created"] == 1
                item = (await session.execute(select(Parceria).where(Parceria.guild_id == "guild-a"))).scalar_one()
                contacts = list((await session.execute(select(ParceriaContact).where(ParceriaContact.parceria_id == item.id).order_by(ParceriaContact.position))).scalars())
                publication = (await session.execute(select(ParceriaPublication).where(ParceriaPublication.parceria_id == item.id))).scalar_one()
                image = await session.get(ParceriaImage, item.image_asset_id)
                assert item.public_channel_id == "20"
                assert item.public_message_id == "200"
                assert [row.value for row in contacts] == ["contato-1", "contato-2"]
                assert publication.status == PublicationStatus.published
                assert image.source_kind == "legacy"
                repeated = await backfill_legacy(session, guild_id="guild-a", correlation_id="migration-2")
                await session.commit()
                assert repeated["created"] == 0
                assert repeated["skipped"] == 1
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_parceria_reconciliation_reactivates_a_failed_delivery():
    async def scenario():
        discover_domain_modules()
        engine, sessions = await database()
        try:
            async with sessions() as session:
                attempt = await services.create_registration_attempt(session, guild_id="guild-a", actor_id="user-a", channel_id="10", family_name="Família", product_name="Produto", contacts=[], idempotency_key="attempt-reconcile", correlation_id="corr-1")
                await services.attach_image(session, guild_id="guild-a", attempt_id=attempt.id, actor_id="user-a", channel_id="10", storage_key="s3:guild-a/image", storage_url="https://storage.invalid/image.webp", content_type="image/webp", size_bytes=1024, checksum="abc", original_filename="logo.webp", correlation_id="corr-2")
                item = await services.complete_registration(session, guild_id="guild-a", attempt_id=attempt.id, actor_id="user-a", ativas_channel_id="20", correlation_id="corr-3")
                await session.commit()
                delivery = (await session.execute(select(DeliveryOutbox).where(DeliveryOutbox.resource_id == item.id))).scalar_one()
                delivery.state = WorkState.failed
                delivery.attempts = delivery.max_attempts
                await session.commit()
                count = await services.reconcile_publications(session, guild_id="guild-a", ativas_channel_id="20", correlation_id="corr-4")
                await session.commit()
                assert count == 1
                assert delivery.state == WorkState.pending
                assert delivery.attempts == 0
        finally:
            await engine.dispose()

    asyncio.run(scenario())
