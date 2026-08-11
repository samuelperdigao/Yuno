from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import require_active_license
from app.core.security import require_bot_token
from app.db import get_session
from app.platform import outbox as service
from app.platform.schemas import DeliveryCreateIn, WorkClaimIn, WorkCompleteIn, WorkFailIn, WorkItemOut


router = APIRouter(dependencies=[Depends(require_bot_token)])


def delivery_out(item) -> WorkItemOut:
    return WorkItemOut(
        id=item.id,
        guild_id=item.guild_id,
        module_key=item.module_key,
        key=item.renderer_key,
        resource_type=item.resource_type,
        resource_id=item.resource_id,
        payload={
            "destination_type": item.destination_type,
            "destination_id": item.destination_id,
            "body": item.payload or {},
        },
        state=item.state,
        attempts=item.attempts,
        max_attempts=item.max_attempts,
        correlation_id=item.correlation_id,
    )


@router.post("/guilds/{guild_id}/modules/{module_key}/deliveries", response_model=WorkItemOut)
async def enqueue(
    guild_id: str,
    module_key: str,
    data: DeliveryCreateIn,
    session: AsyncSession = Depends(get_session),
) -> WorkItemOut:
    await require_active_license(session, guild_id)
    return delivery_out(
        await service.enqueue_delivery(
            session, guild_id=guild_id, module_key=module_key, **data.model_dump()
        )
    )


@router.post("/deliveries/claim", response_model=list[WorkItemOut])
async def claim(data: WorkClaimIn, session: AsyncSession = Depends(get_session)) -> list[WorkItemOut]:
    return [delivery_out(item) for item in await service.claim_deliveries(session, **data.model_dump())]


@router.post("/guilds/{guild_id}/deliveries/{delivery_id}/complete", response_model=WorkItemOut)
async def complete(
    guild_id: str,
    delivery_id: str,
    data: WorkCompleteIn,
    session: AsyncSession = Depends(get_session),
) -> WorkItemOut:
    await require_active_license(session, guild_id)
    return delivery_out(
        await service.complete_delivery(
            session,
            guild_id=guild_id,
            delivery_id=delivery_id,
            worker_id=data.worker_id,
            external_id=data.external_id,
        )
    )


@router.post("/guilds/{guild_id}/deliveries/{delivery_id}/fail", response_model=WorkItemOut)
async def fail(
    guild_id: str,
    delivery_id: str,
    data: WorkFailIn,
    session: AsyncSession = Depends(get_session),
) -> WorkItemOut:
    await require_active_license(session, guild_id)
    return delivery_out(
        await service.fail_delivery(
            session, guild_id=guild_id, delivery_id=delivery_id, **data.model_dump()
        )
    )
