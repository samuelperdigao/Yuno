from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain_modules.parceria.domain import (
    ParceriaStatus,
    PublicationStatus,
    RegistrationAttemptStatus,
    can_transition,
    normalize_family,
    validate_image,
)
from app.domain_modules.parceria.models import (
    Parceria,
    ParceriaContact,
    ParceriaFamily,
    ParceriaImage,
    ParceriaProduct,
    ParceriaPublication,
    RegistrationAttempt,
)
from app.platform.audit import write_audit
from app.platform.automation import schedule_task
from app.platform.models import WorkState
from app.platform.outbox import enqueue_delivery


UPLOAD_TTL = timedelta(minutes=5)
PUBLICATION_MAX_ATTEMPTS = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def get_family(session: AsyncSession, *, guild_id: str, family_name: str) -> ParceriaFamily | None:
    return (
        await session.execute(
            select(ParceriaFamily).where(
                ParceriaFamily.guild_id == guild_id,
                ParceriaFamily.name_normalized == normalize_family(family_name),
            )
        )
    ).scalar_one_or_none()


async def get_partnership(session: AsyncSession, *, guild_id: str, parceria_id: str, for_update: bool = False) -> Parceria:
    query = select(Parceria).where(Parceria.guild_id == guild_id, Parceria.id == parceria_id)
    if for_update:
        query = query.with_for_update()
    item = (await session.execute(query)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Parceria não encontrada nesta guild.")
    return item


async def get_attempt(session: AsyncSession, *, guild_id: str, attempt_id: str, for_update: bool = False) -> RegistrationAttempt:
    query = select(RegistrationAttempt).where(
        RegistrationAttempt.guild_id == guild_id,
        RegistrationAttempt.id == attempt_id,
    )
    if for_update:
        query = query.with_for_update()
    item = (await session.execute(query)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Sessão de registro não encontrada nesta guild.")
    return item


async def _schedule_publication(
    session: AsyncSession,
    *,
    guild_id: str,
    parceria: Parceria,
    channel_id: str,
    actor_id: str,
    correlation_id: str,
    reason: str,
) -> None:
    key = f"parceria:{guild_id}:{parceria.id}:publication:{parceria.publication_revision}"
    publication = (
        await session.execute(
            select(ParceriaPublication).where(
                ParceriaPublication.guild_id == guild_id,
                ParceriaPublication.idempotency_key == key,
            )
        )
    ).scalar_one_or_none()
    if publication is None:
        publication = ParceriaPublication(
            guild_id=guild_id,
            parceria_id=parceria.id,
            channel_id=channel_id,
            message_id=parceria.public_message_id,
            revision=parceria.publication_revision,
            status=PublicationStatus.pending,
            idempotency_key=key,
        )
        session.add(publication)
    else:
        publication.channel_id = channel_id
        publication.status = PublicationStatus.pending
    delivery = await enqueue_delivery(
        session,
        guild_id=guild_id,
        module_key="parceria",
        renderer_key="parceria.publication",
        destination_type="channel",
        destination_id=channel_id,
        resource_type="parceria",
        resource_id=parceria.id,
        payload={
            "schema_version": 1,
            "parceria_id": parceria.id,
            "revision": parceria.publication_revision,
            "reason": reason,
            "status": parceria.status.value,
            "family_name": parceria.family_id,
        },
        priority=20,
        available_at=_now(),
        idempotency_key=key,
        correlation_id=correlation_id,
        max_attempts=PUBLICATION_MAX_ATTEMPTS,
        commit=False,
    )
    if delivery.state == WorkState.failed:
        delivery.state = WorkState.pending
        delivery.attempts = 0
        delivery.available_at = _now()
        delivery.last_error = None
        delivery.lease_owner = None
        delivery.lease_until = None
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="parceria",
        action="parceria.publication_scheduled",
        resource_type="parceria",
        resource_id=parceria.id,
        actor_id=actor_id,
        after={"revision": parceria.publication_revision, "channel_id": channel_id, "reason": reason},
        correlation_id=correlation_id,
    )


async def create_registration_attempt(
    session: AsyncSession,
    *,
    guild_id: str,
    actor_id: str,
    channel_id: str,
    family_name: str,
    product_name: str,
    contacts: list[str],
    idempotency_key: str,
    correlation_id: str,
    expires_at: datetime | None = None,
) -> RegistrationAttempt:
    existing = (
        await session.execute(
            select(RegistrationAttempt).where(
                RegistrationAttempt.guild_id == guild_id,
                RegistrationAttempt.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    if len(contacts) > 2:
        raise HTTPException(status_code=422, detail="No máximo dois contatos são permitidos.")
    attempt = RegistrationAttempt(
        guild_id=guild_id,
        actor_id=actor_id,
        channel_id=channel_id,
        family_name=" ".join(family_name.strip().split()),
        family_normalized=normalize_family(family_name),
        product_name=" ".join(product_name.strip().split()),
        contact_01=contacts[0] if contacts else None,
        contact_02=contacts[1] if len(contacts) > 1 else None,
        expires_at=expires_at or (_now() + UPLOAD_TTL),
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
    )
    session.add(attempt)
    await session.flush()
    await schedule_task(
        session,
        guild_id=guild_id,
        module_key="parceria",
        job_key="parceria.registration.expire",
        resource_type="registration_attempt",
        resource_id=attempt.id,
        payload={"attempt_id": attempt.id},
        due_at=attempt.expires_at,
        idempotency_key=f"parceria:registration-expire:{guild_id}:{attempt.id}",
        correlation_id=correlation_id,
        max_attempts=3,
        commit=False,
    )
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="parceria",
        action="parceria.registration_attempt_created",
        resource_type="registration_attempt",
        resource_id=attempt.id,
        actor_id=actor_id,
        after={"status": attempt.status.value, "expires_at": attempt.expires_at.isoformat()},
        correlation_id=correlation_id,
    )
    return attempt


async def attach_image(
    session: AsyncSession,
    *,
    guild_id: str,
    attempt_id: str,
    actor_id: str,
    channel_id: str,
    storage_key: str,
    storage_url: str | None,
    content_type: str,
    size_bytes: int,
    checksum: str | None,
    original_filename: str | None,
    correlation_id: str,
) -> RegistrationAttempt:
    attempt = await get_attempt(session, guild_id=guild_id, attempt_id=attempt_id, for_update=True)
    if attempt.actor_id != actor_id or attempt.channel_id != channel_id:
        raise HTTPException(status_code=403, detail="Esta sessão não pertence a você ou a este canal.")
    if attempt.status != RegistrationAttemptStatus.awaiting_image:
        return attempt
    if attempt.image_asset_id:
        return attempt
    if attempt.expires_at <= _now():
        attempt.status = RegistrationAttemptStatus.expired
        await write_audit(
            session,
            guild_id=guild_id,
            module_key="parceria",
            action="parceria.registration_attempt_expired",
            resource_type="registration_attempt",
            resource_id=attempt.id,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        raise HTTPException(status_code=410, detail="A sessão de upload expirou.")
    errors = validate_image(content_type=content_type, size_bytes=size_bytes)
    if errors:
        raise HTTPException(status_code=422, detail={"detail": "Imagem inválida.", "errors": errors})
    image = ParceriaImage(
        guild_id=guild_id,
        storage_key=storage_key,
        storage_url=storage_url,
        content_type=content_type.casefold(),
        size_bytes=size_bytes,
        checksum=checksum,
        original_filename=original_filename,
        uploaded_by=actor_id,
    )
    session.add(image)
    await session.flush()
    attempt.image_asset_id = image.id
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="parceria",
        action="parceria.registration_image_attached",
        resource_type="registration_attempt",
        resource_id=attempt.id,
        actor_id=actor_id,
        after={"image_asset_id": image.id, "content_type": image.content_type, "size_bytes": size_bytes},
        correlation_id=correlation_id,
    )
    return attempt


async def complete_registration(
    session: AsyncSession,
    *,
    guild_id: str,
    attempt_id: str,
    actor_id: str,
    ativas_channel_id: str,
    correlation_id: str,
) -> Parceria:
    attempt = await get_attempt(session, guild_id=guild_id, attempt_id=attempt_id, for_update=True)
    if attempt.actor_id != actor_id:
        raise HTTPException(status_code=403, detail="Esta sessão não pertence a você.")
    if attempt.status == RegistrationAttemptStatus.completed and attempt.completed_parceria_id:
        return await get_partnership(session, guild_id=guild_id, parceria_id=attempt.completed_parceria_id)
    if attempt.status != RegistrationAttemptStatus.awaiting_image or not attempt.image_asset_id:
        raise HTTPException(status_code=422, detail="Envie uma imagem válida antes de concluir o registro.")
    if attempt.expires_at <= _now():
        attempt.status = RegistrationAttemptStatus.expired
        raise HTTPException(status_code=410, detail="A sessão de upload expirou.")
    family = await get_family(session, guild_id=guild_id, family_name=attempt.family_name)
    if family is not None:
        raise HTTPException(status_code=409, detail="Já existe uma família com esse nome nesta guild.")
    family = ParceriaFamily(
        guild_id=guild_id,
        name=attempt.family_name,
        name_normalized=attempt.family_normalized,
        active=True,
    )
    session.add(family)
    await session.flush()
    parceria = Parceria(
        guild_id=guild_id,
        family_id=family.id,
        status=ParceriaStatus.publication_pending,
        registered_by=attempt.actor_id,
        image_asset_id=attempt.image_asset_id,
    )
    session.add(parceria)
    await session.flush()
    session.add(ParceriaProduct(guild_id=guild_id, parceria_id=parceria.id, name=attempt.product_name))
    for position, value in enumerate((attempt.contact_01, attempt.contact_02), start=1):
        if value:
            session.add(ParceriaContact(guild_id=guild_id, parceria_id=parceria.id, position=position, value=value))
    attempt.status = RegistrationAttemptStatus.completed
    attempt.completed_parceria_id = parceria.id
    await _schedule_publication(
        session,
        guild_id=guild_id,
        parceria=parceria,
        channel_id=ativas_channel_id,
        actor_id=actor_id,
        correlation_id=correlation_id,
        reason="created",
    )
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="parceria",
        action="parceria.created",
        resource_type="parceria",
        resource_id=parceria.id,
        actor_id=actor_id,
        after={"status": parceria.status.value, "family_id": family.id},
        correlation_id=correlation_id,
    )
    return parceria


async def edit_partnership(
    session: AsyncSession,
    *,
    guild_id: str,
    parceria_id: str,
    actor_id: str,
    family_name: str,
    product_name: str,
    contacts: list[str],
    expected_revision: int,
    ativas_channel_id: str,
    correlation_id: str,
) -> Parceria:
    parceria = await get_partnership(session, guild_id=guild_id, parceria_id=parceria_id, for_update=True)
    if parceria.publication_revision != expected_revision:
        raise HTTPException(status_code=409, detail={"detail": "Parceria alterada por outra sessão.", "current_revision": parceria.publication_revision})
    family = await get_family(session, guild_id=guild_id, family_name=family_name)
    if family is None or family.id != parceria.family_id:
        raise HTTPException(status_code=409, detail="A família informada já existe ou não pode ser trocada nesta edição.")
    if len(contacts) > 2:
        raise HTTPException(status_code=422, detail="No máximo dois contatos são permitidos.")
    product = (await session.execute(select(ParceriaProduct).where(ParceriaProduct.guild_id == guild_id, ParceriaProduct.parceria_id == parceria.id))).scalar_one()
    old = {"product_name": product.name, "contacts": [item.value for item in (await session.execute(select(ParceriaContact).where(ParceriaContact.guild_id == guild_id, ParceriaContact.parceria_id == parceria.id).order_by(ParceriaContact.position))).scalars()]}
    product.name = product_name
    contacts_rows = list((await session.execute(select(ParceriaContact).where(ParceriaContact.guild_id == guild_id, ParceriaContact.parceria_id == parceria.id))).scalars())
    for row in contacts_rows:
        await session.delete(row)
    await session.flush()
    for position, value in enumerate(contacts, start=1):
        session.add(ParceriaContact(guild_id=guild_id, parceria_id=parceria.id, position=position, value=value))
    if parceria.status not in {ParceriaStatus.active, ParceriaStatus.degraded, ParceriaStatus.publication_pending}:
        raise HTTPException(status_code=422, detail="Parceria inativa não pode ser editada sem reativação explícita.")
    parceria.status = ParceriaStatus.publication_pending
    parceria.publication_revision += 1
    await _schedule_publication(session, guild_id=guild_id, parceria=parceria, channel_id=ativas_channel_id, actor_id=actor_id, correlation_id=correlation_id, reason="edited")
    await write_audit(session, guild_id=guild_id, module_key="parceria", action="parceria.edited", resource_type="parceria", resource_id=parceria.id, actor_id=actor_id, before=old, after={"product_name": product_name, "contacts": contacts, "revision": parceria.publication_revision}, correlation_id=correlation_id)
    return parceria


async def deactivate_partnership(session: AsyncSession, *, guild_id: str, parceria_id: str, actor_id: str, ativas_channel_id: str, expected_revision: int, correlation_id: str) -> Parceria:
    parceria = await get_partnership(session, guild_id=guild_id, parceria_id=parceria_id, for_update=True)
    if parceria.publication_revision != expected_revision:
        raise HTTPException(status_code=409, detail={"detail": "Parceria alterada por outra sessão.", "current_revision": parceria.publication_revision})
    if parceria.status == ParceriaStatus.inactive:
        return parceria
    if not can_transition(parceria.status, ParceriaStatus.inactive):
        raise HTTPException(status_code=422, detail="Transição de desativação inválida.")
    parceria.status = ParceriaStatus.inactive
    parceria.publication_revision += 1
    await _schedule_publication(session, guild_id=guild_id, parceria=parceria, channel_id=ativas_channel_id, actor_id=actor_id, correlation_id=correlation_id, reason="deactivated")
    await write_audit(session, guild_id=guild_id, module_key="parceria", action="parceria.deactivated", resource_type="parceria", resource_id=parceria.id, actor_id=actor_id, after={"status": parceria.status.value, "revision": parceria.publication_revision}, correlation_id=correlation_id)
    return parceria


async def expire_attempts(
    session: AsyncSession,
    *,
    guild_id: str | None = None,
    attempt_id: str | None = None,
    correlation_id: str,
) -> int:
    query = select(RegistrationAttempt).where(RegistrationAttempt.status == RegistrationAttemptStatus.awaiting_image, RegistrationAttempt.expires_at <= _now())
    if guild_id:
        query = query.where(RegistrationAttempt.guild_id == guild_id)
    if attempt_id:
        query = query.where(RegistrationAttempt.id == attempt_id)
    items = list((await session.execute(query.with_for_update())).scalars())
    for item in items:
        item.status = RegistrationAttemptStatus.expired
        await write_audit(session, guild_id=item.guild_id, module_key="parceria", action="parceria.registration_attempt_expired", resource_type="registration_attempt", resource_id=item.id, actor_id=None, correlation_id=correlation_id)
    return len(items)


async def reconcile_publications(
    session: AsyncSession, *, guild_id: str, ativas_channel_id: str, correlation_id: str
) -> int:
    items = list(
        (
            await session.execute(
                select(Parceria)
                .where(
                    Parceria.guild_id == guild_id,
                    Parceria.status.in_((ParceriaStatus.publication_pending, ParceriaStatus.degraded)),
                )
                .with_for_update()
            )
        ).scalars()
    )
    for item in items:
        await _schedule_publication(
            session,
            guild_id=guild_id,
            parceria=item,
            channel_id=ativas_channel_id,
            actor_id="system",
            correlation_id=correlation_id,
            reason="reconciled",
        )
    return len(items)


async def mark_publication_result(session: AsyncSession, *, guild_id: str, parceria_id: str, revision: int, status: PublicationStatus, channel_id: str, message_id: str | None, error: str | None, correlation_id: str) -> None:
    parceria = await get_partnership(session, guild_id=guild_id, parceria_id=parceria_id, for_update=True)
    key = f"parceria:{guild_id}:{parceria_id}:publication:{revision}"
    publication = (
        await session.execute(
            select(ParceriaPublication).where(
                ParceriaPublication.guild_id == guild_id,
                ParceriaPublication.parceria_id == parceria_id,
                ParceriaPublication.idempotency_key == key,
            )
        )
    ).scalar_one_or_none()
    if publication:
        publication.status = status
        publication.channel_id = channel_id
        publication.message_id = message_id
        publication.last_error = error
    if revision != parceria.publication_revision:
        return
    if status == PublicationStatus.published and parceria.status != ParceriaStatus.inactive and not message_id:
        raise HTTPException(status_code=422, detail="Publicacao ativa precisa retornar o ID da mensagem.")
    parceria.public_channel_id = channel_id
    parceria.public_message_id = message_id
    parceria.status = ParceriaStatus.active if status == PublicationStatus.published and parceria.status == ParceriaStatus.publication_pending else parceria.status
    if status == PublicationStatus.failed:
        parceria.status = ParceriaStatus.degraded
    await write_audit(session, guild_id=guild_id, module_key="parceria", action="parceria.publication_result", resource_type="parceria", resource_id=parceria_id, actor_id=None, after={"status": status.value, "revision": revision, "message_id": message_id, "error": error}, correlation_id=correlation_id)
