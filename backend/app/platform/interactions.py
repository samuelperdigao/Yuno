from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.platform.models import InteractionReceipt, WorkState


async def begin_interaction(
    session: AsyncSession,
    *,
    guild_id: str,
    interaction_id: str,
    module_key: str,
    action_key: str,
    resource_type: str,
    resource_id: str,
    correlation_id: str,
) -> tuple[InteractionReceipt, bool]:
    existing = (
        await session.execute(
            select(InteractionReceipt).where(
                InteractionReceipt.guild_id == guild_id,
                InteractionReceipt.interaction_id == interaction_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, True
    receipt = InteractionReceipt(
        guild_id=guild_id,
        interaction_id=interaction_id,
        module_key=module_key,
        action_key=action_key,
        resource_type=resource_type,
        resource_id=resource_id,
        state=WorkState.claimed,
        correlation_id=correlation_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    try:
        async with session.begin_nested():
            session.add(receipt)
            await session.flush()
    except IntegrityError:
        receipt = (
            await session.execute(
                select(InteractionReceipt).where(
                    InteractionReceipt.guild_id == guild_id,
                    InteractionReceipt.interaction_id == interaction_id,
                )
            )
        ).scalar_one()
        return receipt, True
    await session.commit()
    return receipt, False


async def finish_interaction(
    session: AsyncSession,
    *,
    guild_id: str,
    receipt_id: str,
    result: dict,
    error: str | None,
) -> InteractionReceipt | None:
    receipt = (
        await session.execute(
            select(InteractionReceipt)
            .where(InteractionReceipt.id == receipt_id, InteractionReceipt.guild_id == guild_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if receipt is None:
        return None
    if receipt.state in (WorkState.succeeded, WorkState.failed):
        return receipt
    receipt.state = WorkState.failed if error else WorkState.succeeded
    receipt.result = result
    receipt.error = error
    receipt.completed_at = datetime.now(timezone.utc)
    await session.commit()
    return receipt
