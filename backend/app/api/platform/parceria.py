from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import ActorHeader, CorrelationHeader, require_active_license
from app.core.security import require_bot_token
from app.db import get_session
from app.domain_modules.parceria.domain import PublicationStatus
from app.domain_modules.parceria import image_processing, services
from app.domain_modules.parceria.models import Parceria, ParceriaContact, ParceriaFamily, ParceriaImage, ParceriaProduct, RegistrationAttempt
from app.domain_modules.parceria.schemas import AutomationCommand, ImageAttachCommand, PartnershipDeactivateCommand, PartnershipEditCommand, PublicationResultCommand, RegistrationAttemptCommand, RegistrationCompleteCommand
from app.platform.configuration import effective_configuration
from app.platform.permissions import authorize
from app.platform.schemas import ActorContextIn
from app.object_storage import ObjectStorageError, get_object_storage


router = APIRouter(dependencies=[Depends(require_bot_token)])


def _check_actor(guild_id: str, actor: ActorContextIn) -> None:
    if actor.guild_id != guild_id:
        raise HTTPException(status_code=403, detail="ActorContext pertence a outra guild.")


async def _permit(session: AsyncSession, *, guild_id: str, capability: str, actor: ActorContextIn, actor_header: str, correlation_header: str | None, resource_id: str = "") -> None:
    _check_actor(guild_id, actor)
    if actor.actor_type == "user" and actor.user_id != actor_header:
        raise HTTPException(status_code=403, detail="Ator autenticado divergente.")
    if correlation_header and correlation_header != actor.correlation_id:
        raise HTTPException(status_code=400, detail="Correlation ID divergente.")
    decision = await authorize(session, guild_id=guild_id, module_key="parceria", capability_key=capability, actor=actor, resource_id=resource_id)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)


async def _active_config(session: AsyncSession, guild_id: str) -> dict:
    version = await effective_configuration(session, guild_id=guild_id, module_key="parceria")
    if version is None:
        raise HTTPException(status_code=422, detail="Parcerias ainda não possuem configuração publicada.")
    return version.data or {}


async def _out(session: AsyncSession, item) -> dict:
    family = await session.get(ParceriaFamily, item.family_id)
    product = (await session.execute(select(ParceriaProduct).where(ParceriaProduct.guild_id == item.guild_id, ParceriaProduct.parceria_id == item.id))).scalar_one()
    contacts = list((await session.execute(select(ParceriaContact).where(ParceriaContact.guild_id == item.guild_id, ParceriaContact.parceria_id == item.id).order_by(ParceriaContact.position))).scalars())
    image = await session.get(ParceriaImage, item.image_asset_id)
    storage_url = image.storage_url if image else None
    if image and not storage_url and image.source_kind != "legacy":
        try:
            storage_url = await get_object_storage().presign_get(key=image.storage_key)
        except ObjectStorageError:
            storage_url = None
    return {
        "id": item.id,
        "guild_id": item.guild_id,
        "family_name": family.name if family else "",
        "family_normalized": family.name_normalized if family else "",
        "product_name": product.name,
        "contacts": [contact.value for contact in contacts],
        "status": item.status.value,
        "registered_by": item.registered_by,
        "image": {
            "id": image.id if image else None,
            "storage_key": image.storage_key if image else None,
            "storage_url": storage_url,
            "content_type": image.content_type if image else None,
            "size_bytes": image.size_bytes if image else None,
            "original_filename": image.original_filename if image else None,
        },
        "public_channel_id": item.public_channel_id,
        "public_message_id": item.public_message_id,
        "publication_revision": item.publication_revision,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _attempt_out(item: RegistrationAttempt) -> dict:
    return {
        "id": item.id,
        "guild_id": item.guild_id,
        "actor_id": item.actor_id,
        "channel_id": item.channel_id,
        "family_name": item.family_name,
        "product_name": item.product_name,
        "contacts": [value for value in (item.contact_01, item.contact_02) if value],
        "status": item.status.value,
        "expires_at": item.expires_at,
        "image_asset_id": item.image_asset_id,
        "completed_parceria_id": item.completed_parceria_id,
    }


@router.post("/guilds/{guild_id}/modules/parceria/registration-attempts")
async def begin_registration(guild_id: str, data: RegistrationAttemptCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    await _permit(session, guild_id=guild_id, capability="parceria.register", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id)
    config = await _active_config(session, guild_id)
    if data.channel_id != str(config["registrar_channel_id"]):
        raise HTTPException(status_code=422, detail="O cadastro deve iniciar no canal de registro publicado.")
    item = await services.create_registration_attempt(session, guild_id=guild_id, actor_id=data.actor.user_id or x_yuno_actor_id, channel_id=data.channel_id, family_name=data.family_name, product_name=data.product_name, contacts=data.contacts, idempotency_key=data.idempotency_key, correlation_id=x_yuno_correlation_id or data.actor.correlation_id)
    await session.commit()
    return _attempt_out(item)


@router.post("/guilds/{guild_id}/modules/parceria/registration-attempts/{attempt_id}/image")
async def attach_registration_image(guild_id: str, attempt_id: str, data: ImageAttachCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    await _permit(session, guild_id=guild_id, capability="parceria.register", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id)
    image_data = data.model_dump(exclude={"actor", "source_url"})
    storage = None
    if data.source_url:
        try:
            storage = get_object_storage()
            stored = await image_processing.ingest_discord_attachment(
                storage,
                source_url=data.source_url,
                storage_key=f"parceria/{guild_id}/registration/{attempt_id}",
                original_filename=data.original_filename,
            )
        except ObjectStorageError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except image_processing.InvalidPartnershipImage as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        image_data = {
            "storage_key": stored.storage_key,
            "storage_url": None,
            "content_type": stored.content_type,
            "size_bytes": stored.size_bytes,
            "checksum": stored.checksum,
            "original_filename": stored.original_filename,
        }
    try:
        item = await services.attach_image(session, guild_id=guild_id, attempt_id=attempt_id, actor_id=data.actor.user_id or x_yuno_actor_id, channel_id=data.actor.channel_id or "", correlation_id=x_yuno_correlation_id or data.actor.correlation_id, **image_data)
    except Exception:
        if storage is not None:
            try:
                await storage.delete(key=f"parceria/{guild_id}/registration/{attempt_id}")
            except Exception:
                pass
        raise
    await session.commit()
    return _attempt_out(item)


@router.post("/guilds/{guild_id}/modules/parceria/registration-attempts/{attempt_id}/complete")
async def complete_registration(guild_id: str, attempt_id: str, data: RegistrationCompleteCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    await _permit(session, guild_id=guild_id, capability="parceria.register", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id)
    config = await _active_config(session, guild_id)
    item = await services.complete_registration(session, guild_id=guild_id, attempt_id=attempt_id, actor_id=data.actor.user_id or x_yuno_actor_id, ativas_channel_id=str(config["ativas_channel_id"]), correlation_id=x_yuno_correlation_id or data.actor.correlation_id)
    await session.commit()
    return await _out(session, item)


@router.get("/guilds/{guild_id}/modules/parceria/partnerships")
async def list_partnerships(guild_id: str, session: AsyncSession = Depends(get_session)) -> list[dict]:
    await require_active_license(session, guild_id)
    items = list((await session.execute(select(Parceria).where(Parceria.guild_id == guild_id).order_by(Parceria.created_at.desc()))).scalars())
    return [await _out(session, item) for item in items]


@router.get("/guilds/{guild_id}/modules/parceria/partnerships/{parceria_id}")
async def read_partnership(guild_id: str, parceria_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    return await _out(session, await services.get_partnership(session, guild_id=guild_id, parceria_id=parceria_id))


@router.patch("/guilds/{guild_id}/modules/parceria/partnerships/{parceria_id}")
async def edit_partnership(guild_id: str, parceria_id: str, data: PartnershipEditCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    await _permit(session, guild_id=guild_id, capability="parceria.edit", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id, resource_id=parceria_id)
    config = await _active_config(session, guild_id)
    item = await services.edit_partnership(session, guild_id=guild_id, parceria_id=parceria_id, actor_id=data.actor.user_id or x_yuno_actor_id, ativas_channel_id=str(config["ativas_channel_id"]), correlation_id=x_yuno_correlation_id or data.actor.correlation_id, **data.model_dump(exclude={"actor"}))
    await session.commit()
    return await _out(session, item)


@router.post("/guilds/{guild_id}/modules/parceria/partnerships/{parceria_id}/deactivate")
async def deactivate_partnership(guild_id: str, parceria_id: str, data: PartnershipDeactivateCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    await _permit(session, guild_id=guild_id, capability="parceria.deactivate", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id, resource_id=parceria_id)
    config = await _active_config(session, guild_id)
    item = await services.deactivate_partnership(session, guild_id=guild_id, parceria_id=parceria_id, actor_id=data.actor.user_id or x_yuno_actor_id, ativas_channel_id=str(config["ativas_channel_id"]), expected_revision=data.expected_revision, correlation_id=x_yuno_correlation_id or data.actor.correlation_id)
    await session.commit()
    return await _out(session, item)


@router.post("/guilds/{guild_id}/modules/parceria/recovery/expire")
async def expire_registration_attempts(guild_id: str, data: AutomationCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    await _permit(session, guild_id=guild_id, capability="parceria.automation", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id)
    count = await services.expire_attempts(session, guild_id=guild_id, attempt_id=data.attempt_id, correlation_id=data.actor.correlation_id)
    await session.commit()
    return {"expired": count}


@router.post("/guilds/{guild_id}/modules/parceria/recovery/publications")
async def reconcile_publications(guild_id: str, data: AutomationCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    await _permit(session, guild_id=guild_id, capability="parceria.automation", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id)
    config = await _active_config(session, guild_id)
    count = await services.reconcile_publications(session, guild_id=guild_id, ativas_channel_id=str(config["ativas_channel_id"]), correlation_id=data.actor.correlation_id)
    await session.commit()
    return {"reconciled": count}


@router.get("/guilds/{guild_id}/modules/parceria/registration-attempts/awaiting-image")
async def awaiting_image(guild_id: str, actor_id: str, channel_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    item = (await session.execute(select(RegistrationAttempt).where(RegistrationAttempt.guild_id == guild_id, RegistrationAttempt.actor_id == actor_id, RegistrationAttempt.channel_id == channel_id, RegistrationAttempt.status == "awaiting_image").order_by(RegistrationAttempt.created_at.desc()))).scalars().first()
    return {"attempt": _attempt_out(item) if item else None}


@router.post("/guilds/{guild_id}/modules/parceria/publications/{parceria_id}/result")
async def publication_result(guild_id: str, parceria_id: str, data: PublicationResultCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    await _permit(session, guild_id=guild_id, capability="parceria.automation", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id, resource_id=parceria_id)
    await services.mark_publication_result(session, guild_id=guild_id, parceria_id=parceria_id, revision=data.revision, status=PublicationStatus(data.status), channel_id=data.channel_id, message_id=data.message_id, error=data.error, correlation_id=data.actor.correlation_id)
    await session.commit()
    return {"ok": True}
