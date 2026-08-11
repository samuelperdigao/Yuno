from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.platform.models import DeliveryAttempt, DeliveryOutbox, WorkState
from app.platform.registry import module_registry


async def enqueue_delivery(
    session: AsyncSession,
    *,
    guild_id: str,
    module_key: str,
    renderer_key: str,
    destination_type: str,
    destination_id: str,
    resource_type: str,
    resource_id: str,
    payload: dict,
    priority: int,
    available_at: datetime,
    idempotency_key: str,
    correlation_id: str,
    max_attempts: int,
) -> DeliveryOutbox:
    if module_registry.get(module_key) is None:
        raise HTTPException(status_code=404, detail="Modulo desconhecido.")
    definition = module_registry.get(module_key)
    notification = definition.notification(renderer_key) if definition else None
    if notification is None:
        raise HTTPException(status_code=422, detail="Notificacao nao declarada pelo modulo.")
    if destination_type not in notification.destination_types:
        raise HTTPException(status_code=422, detail="Destino nao permitido para esta notificacao.")
    if available_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="available_at precisa incluir timezone.")
    existing = (
        await session.execute(
            select(DeliveryOutbox).where(
                DeliveryOutbox.guild_id == guild_id,
                DeliveryOutbox.module_key == module_key,
                DeliveryOutbox.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    delivery = DeliveryOutbox(
        guild_id=guild_id,
        module_key=module_key,
        renderer_key=renderer_key,
        destination_type=destination_type,
        destination_id=destination_id,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=payload,
        priority=priority,
        available_at=available_at,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        max_attempts=max_attempts,
    )
    try:
        async with session.begin_nested():
            session.add(delivery)
            await session.flush()
    except IntegrityError:
        delivery = (
            await session.execute(
                select(DeliveryOutbox).where(
                    DeliveryOutbox.guild_id == guild_id,
                    DeliveryOutbox.module_key == module_key,
                    DeliveryOutbox.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one()
    await session.commit()
    return delivery


async def claim_deliveries(
    session: AsyncSession, *, worker_id: str, limit: int, lease_seconds: int
) -> list[DeliveryOutbox]:
    now = datetime.now(timezone.utc)
    query = (
        select(DeliveryOutbox)
        .where(
            DeliveryOutbox.available_at <= now,
            or_(
                DeliveryOutbox.state.in_([WorkState.pending, WorkState.retry]),
                (DeliveryOutbox.state == WorkState.claimed) & (DeliveryOutbox.lease_until < now),
            ),
        )
        .order_by(DeliveryOutbox.priority, DeliveryOutbox.available_at, DeliveryOutbox.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    deliveries = list((await session.execute(query)).scalars())
    for delivery in deliveries:
        delivery.state = WorkState.claimed
        delivery.lease_owner = worker_id
        delivery.lease_until = now + timedelta(seconds=lease_seconds)
        delivery.attempts += 1
        session.add(
            DeliveryAttempt(
                delivery_id=delivery.id,
                attempt=delivery.attempts,
                worker_id=worker_id,
            )
        )
    await session.commit()
    return deliveries


async def _claimed_delivery(
    session: AsyncSession, *, guild_id: str, delivery_id: str, worker_id: str
) -> DeliveryOutbox:
    delivery = (
        await session.execute(
            select(DeliveryOutbox).where(
                DeliveryOutbox.id == delivery_id,
                DeliveryOutbox.guild_id == guild_id,
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if delivery is None:
        raise HTTPException(status_code=404, detail="Entrega nao encontrada.")
    if delivery.state != WorkState.claimed or delivery.lease_owner != worker_id:
        raise HTTPException(status_code=409, detail="Lease da entrega nao pertence a este worker.")
    lease_until = delivery.lease_until
    if lease_until is None:
        raise HTTPException(status_code=409, detail="Lease da entrega expirou.")
    if lease_until.tzinfo is None:
        lease_until = lease_until.replace(tzinfo=timezone.utc)
    if lease_until < datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="Lease da entrega expirou.")
    return delivery


async def complete_delivery(
    session: AsyncSession,
    *,
    guild_id: str,
    delivery_id: str,
    worker_id: str,
    external_id: str | None,
) -> DeliveryOutbox:
    delivery = await _claimed_delivery(
        session, guild_id=guild_id, delivery_id=delivery_id, worker_id=worker_id
    )
    delivery.state = WorkState.succeeded
    delivery.lease_owner = None
    delivery.lease_until = None
    attempt = (
        await session.execute(
            select(DeliveryAttempt).where(
                DeliveryAttempt.delivery_id == delivery.id,
                DeliveryAttempt.attempt == delivery.attempts,
            )
        )
    ).scalar_one()
    attempt.state = WorkState.succeeded
    attempt.external_id = external_id
    attempt.finished_at = datetime.now(timezone.utc)
    await session.commit()
    return delivery


async def fail_delivery(
    session: AsyncSession,
    *,
    guild_id: str,
    delivery_id: str,
    worker_id: str,
    error: str,
    retry_at: datetime | None,
) -> DeliveryOutbox:
    if retry_at is not None and retry_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="retry_at precisa incluir timezone.")
    delivery = await _claimed_delivery(
        session, guild_id=guild_id, delivery_id=delivery_id, worker_id=worker_id
    )
    exhausted = delivery.attempts >= delivery.max_attempts
    delivery.state = WorkState.failed if exhausted else WorkState.retry
    delivery.last_error = error
    delivery.available_at = retry_at or datetime.now(timezone.utc) + timedelta(
        seconds=min(900, 2 ** delivery.attempts)
    )
    delivery.lease_owner = None
    delivery.lease_until = None
    attempt = (
        await session.execute(
            select(DeliveryAttempt).where(
                DeliveryAttempt.delivery_id == delivery.id,
                DeliveryAttempt.attempt == delivery.attempts,
            )
        )
    ).scalar_one()
    attempt.state = delivery.state
    attempt.error = error
    attempt.finished_at = datetime.now(timezone.utc)
    await session.commit()
    return delivery
