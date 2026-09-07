from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import (
    ActorHeader,
    CorrelationHeader,
    require_active_license,
)
from app.core.security import require_bot_token
from app.db import get_session
from app.domain_modules.chest import services
from app.domain_modules.chest.schemas import (
    ActorCommand,
    CatalogPublishCommand,
    ChestDraftUpsert,
    ExternalDepositCommand,
    HistoryCommand,
    ItemDraftUpsert,
    LinkDraftUpsert,
    MovementCommand,
    RecoveryCommand,
    ResourceDeletedCommand,
    SettingsDraftCommand,
    StockCommand,
)
from app.platform.schemas import ActorContextIn

router = APIRouter(dependencies=[Depends(require_bot_token)])


def _check_actor(
    guild_id: str,
    actor: ActorContextIn,
    actor_header: str,
    correlation_header: str | None,
) -> None:
    if actor.guild_id != guild_id:
        raise HTTPException(
            status_code=403, detail="ActorContext pertence a outra guild."
        )
    if actor.actor_type == "user" and actor.user_id != actor_header:
        raise HTTPException(
            status_code=403, detail="Ator autenticado diverge do payload."
        )
    if correlation_header and correlation_header != actor.correlation_id:
        raise HTTPException(status_code=400, detail="Correlation ID divergente.")


async def _prepare(
    session: AsyncSession,
    *,
    guild_id: str,
    actor: ActorContextIn,
    actor_header: str,
    correlation_header: str | None,
) -> None:
    await require_active_license(session, guild_id)
    _check_actor(guild_id, actor, actor_header, correlation_header)


@router.post("/guilds/{guild_id}/modules/chest/catalog/draft")
async def read_catalog_draft(
    guild_id: str,
    data: ActorCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _prepare(
        session,
        guild_id=guild_id,
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    result = await services.authorized_catalog_draft(
        session, guild_id=guild_id, actor=data.actor
    )
    await session.commit()
    return result


@router.put("/guilds/{guild_id}/modules/chest/configuration/draft")
async def save_settings(
    guild_id: str,
    data: SettingsDraftCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _prepare(
        session,
        guild_id=guild_id,
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await services.save_settings(
        session,
        guild_id=guild_id,
        **data.model_dump(exclude={"actor", "data"}),
        data=data.data.model_dump(),
        actor=data.actor,
    )


@router.put("/guilds/{guild_id}/modules/chest/catalog/draft/chests")
async def upsert_chest(
    guild_id: str,
    data: ChestDraftUpsert,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _prepare(
        session,
        guild_id=guild_id,
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await services.upsert_draft_chest(
        session,
        guild_id=guild_id,
        **data.model_dump(exclude={"actor"}),
        actor=data.actor,
    )


@router.put("/guilds/{guild_id}/modules/chest/catalog/draft/items")
async def upsert_item(
    guild_id: str,
    data: ItemDraftUpsert,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _prepare(
        session,
        guild_id=guild_id,
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await services.upsert_draft_item(
        session,
        guild_id=guild_id,
        **data.model_dump(exclude={"actor"}),
        actor=data.actor,
    )


@router.put("/guilds/{guild_id}/modules/chest/catalog/draft/links")
async def upsert_link(
    guild_id: str,
    data: LinkDraftUpsert,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _prepare(
        session,
        guild_id=guild_id,
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await services.upsert_draft_link(
        session,
        guild_id=guild_id,
        **data.model_dump(exclude={"actor"}),
        actor=data.actor,
    )


@router.post("/guilds/{guild_id}/modules/chest/catalog/publish")
async def publish_catalog(
    guild_id: str,
    data: CatalogPublishCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _prepare(
        session,
        guild_id=guild_id,
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await services.publish_catalog(
        session,
        guild_id=guild_id,
        **data.model_dump(exclude={"actor"}),
        actor=data.actor,
    )


@router.post("/guilds/{guild_id}/modules/chest/catalog/published")
async def read_published_catalog(
    guild_id: str,
    data: ActorCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _prepare(
        session,
        guild_id=guild_id,
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await services.authorized_catalog(
        session, guild_id=guild_id, actor=data.actor
    )


@router.post("/guilds/{guild_id}/modules/chest/admin-summary")
async def admin_summary(
    guild_id: str,
    data: ActorCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _prepare(
        session,
        guild_id=guild_id,
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await services.admin_summary(session, guild_id=guild_id, actor=data.actor)


@router.post("/guilds/{guild_id}/modules/chest/stock")
async def read_stock(
    guild_id: str,
    data: StockCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _prepare(
        session,
        guild_id=guild_id,
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await services.stock(
        session, guild_id=guild_id, chest_id=data.chest_id, actor=data.actor
    )


@router.post("/guilds/{guild_id}/modules/chest/movements")
async def create_movement(
    guild_id: str,
    data: MovementCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _prepare(
        session,
        guild_id=guild_id,
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    movement = await services.record_movement(
        session,
        guild_id=guild_id,
        chest_id=data.chest_id,
        item_id=data.item_id,
        movement_type=data.movement_type,
        amount=data.quantity,
        observation=data.observation,
        idempotency_key=data.idempotency_key,
        origin=data.origin,
        actor=data.actor,
    )
    return services.movement_out(movement)


@router.post("/guilds/{guild_id}/modules/chest/history")
async def read_history(
    guild_id: str,
    data: HistoryCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    await _prepare(
        session,
        guild_id=guild_id,
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    rows = await services.history(
        session,
        guild_id=guild_id,
        **data.model_dump(exclude={"actor"}),
        actor=data.actor,
    )
    return [services.movement_out(row) for row in rows]


@router.post("/guilds/{guild_id}/modules/chest/external-deposits")
async def external_deposit(
    guild_id: str,
    data: ExternalDepositCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _prepare(
        session,
        guild_id=guild_id,
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    movement = await services.record_external_deposit(
        session,
        guild_id=guild_id,
        source_module=data.source_module,
        source_event_id=data.source_event_id,
        chest_id=data.chest_id,
        item_id=data.item_id,
        amount=data.quantity,
        observation=data.observation,
        actor=data.actor,
    )
    return services.movement_out(movement)


@router.post("/guilds/{guild_id}/modules/chest/recovery")
async def recover(
    guild_id: str,
    data: RecoveryCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _prepare(
        session,
        guild_id=guild_id,
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    if data.action == "create_missing_balances":
        return await services.create_missing_balances(
            session,
            guild_id=guild_id,
            actor=data.actor,
            idempotency_key=data.idempotency_key,
        )
    return await services.queue_panel_recovery(
        session,
        guild_id=guild_id,
        actor=data.actor,
        idempotency_key=data.idempotency_key,
    )


@router.post("/guilds/{guild_id}/modules/chest/resources/deleted")
async def resource_deleted(
    guild_id: str,
    data: ResourceDeletedCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _prepare(
        session,
        guild_id=guild_id,
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await services.record_resource_deleted(
        session,
        guild_id=guild_id,
        **data.model_dump(exclude={"actor"}),
        actor=data.actor,
    )
