from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import ActorHeader, CorrelationHeader, require_active_license
from app.core.security import require_bot_token
from app.db import get_session
from app.domain_modules.bau import services
from app.domain_modules.bau.schemas import (
    BauCategoryCreateCommand,
    BauCategoryRemoveCommand,
    BauCategoryRenameCommand,
    BauClearCommand,
    BauItemCreateCommand,
    BauItemRemoveCommand,
    BauItemRenameCommand,
    BauMovementCommand,
)
from app.platform.permissions import authorize
from app.platform.schemas import ActorContextIn

router = APIRouter(dependencies=[Depends(require_bot_token)])


async def _permit(
    session: AsyncSession,
    *,
    guild_id: str,
    capability: str,
    actor: ActorContextIn,
    actor_header: str,
    correlation_header: str | None,
    resource_id: str = "",
) -> str:
    if actor.guild_id != guild_id:
        raise HTTPException(status_code=403, detail="ActorContext pertence a outra guild.")
    if actor.actor_type == "user" and actor.user_id != actor_header:
        raise HTTPException(status_code=403, detail="Ator autenticado divergente.")
    if correlation_header and correlation_header != actor.correlation_id:
        raise HTTPException(status_code=400, detail="Correlation ID divergente.")
    decision = await authorize(
        session,
        guild_id=guild_id,
        module_key="bau",
        capability_key=capability,
        actor=actor,
        resource_id=resource_id,
    )
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)
    return actor.correlation_id


@router.get("/guilds/{guild_id}/modules/bau/config")
async def effective_config(
    guild_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    version, config = await services.effective_configuration(
        session, guild_id=guild_id, require_active=False
    )
    return {"version_id": version.id, "version": version.version, "data": config.model_dump(mode="json")}


@router.get("/guilds/{guild_id}/modules/bau/catalog")
async def catalog(guild_id: str, session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    await require_active_license(session, guild_id)
    return await services.list_catalog(session, guild_id=guild_id)


@router.get("/guilds/{guild_id}/modules/bau/summary")
async def summary(guild_id: str, session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    await require_active_license(session, guild_id)
    return await services.stock_summary(session, guild_id=guild_id)


@router.post("/guilds/{guild_id}/modules/bau/catalog/seed")
async def seed_catalog(
    guild_id: str,
    data: BauClearCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="bau.manage_catalog",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    created = await services.seed_default_catalog_if_empty(
        session, guild_id=guild_id, actor_id=x_yuno_actor_id, correlation_id=correlation
    )
    return {"categories_created": created}


@router.post("/guilds/{guild_id}/modules/bau/catalog/categories")
async def create_category(
    guild_id: str,
    data: BauCategoryCreateCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="bau.manage_catalog",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    category = await services.add_category(
        session, guild_id=guild_id, actor_id=x_yuno_actor_id, correlation_id=correlation, name=data.name
    )
    return {"id": category.id, "name": category.name}


@router.post("/guilds/{guild_id}/modules/bau/catalog/categories/rename")
async def rename_category(
    guild_id: str,
    data: BauCategoryRenameCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="bau.manage_catalog",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    category = await services.rename_category(
        session,
        guild_id=guild_id,
        actor_id=x_yuno_actor_id,
        correlation_id=correlation,
        name=data.name,
        new_name=data.new_name,
    )
    return {"id": category.id, "name": category.name}


@router.post("/guilds/{guild_id}/modules/bau/catalog/categories/remove")
async def remove_category(
    guild_id: str,
    data: BauCategoryRemoveCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="bau.manage_catalog",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    await services.remove_category(
        session, guild_id=guild_id, actor_id=x_yuno_actor_id, correlation_id=correlation, name=data.name
    )
    return {"removed": True}


@router.post("/guilds/{guild_id}/modules/bau/catalog/items")
async def create_item(
    guild_id: str,
    data: BauItemCreateCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="bau.manage_catalog",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    item = await services.add_item(
        session,
        guild_id=guild_id,
        actor_id=x_yuno_actor_id,
        correlation_id=correlation,
        category_name=data.category_name,
        name=data.name,
    )
    return {"id": item.id, "name": item.name}


@router.post("/guilds/{guild_id}/modules/bau/catalog/items/rename")
async def rename_item(
    guild_id: str,
    data: BauItemRenameCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="bau.manage_catalog",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    item = await services.rename_item(
        session,
        guild_id=guild_id,
        actor_id=x_yuno_actor_id,
        correlation_id=correlation,
        name=data.name,
        new_name=data.new_name,
    )
    return {"id": item.id, "name": item.name}


@router.post("/guilds/{guild_id}/modules/bau/catalog/items/remove")
async def remove_item(
    guild_id: str,
    data: BauItemRemoveCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="bau.manage_catalog",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    await services.remove_item(
        session, guild_id=guild_id, actor_id=x_yuno_actor_id, correlation_id=correlation, name=data.name
    )
    return {"removed": True}


@router.post("/guilds/{guild_id}/modules/bau/movements")
async def movements(
    guild_id: str,
    data: BauMovementCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="bau.move_stock",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    changes = await services.apply_movements(
        session,
        guild_id=guild_id,
        actor_id=x_yuno_actor_id,
        correlation_id=correlation,
        items=[(item.item_id, item.raw) for item in data.items],
    )
    return {"changes": changes}


@router.post("/guilds/{guild_id}/modules/bau/clear")
async def clear(
    guild_id: str,
    data: BauClearCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    if not data.confirm:
        raise HTTPException(status_code=422, detail="Confirmação obrigatória para limpar o estoque.")
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="bau.clear_stock",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    items_reset = await services.clear_stock(
        session, guild_id=guild_id, actor_id=x_yuno_actor_id, correlation_id=correlation
    )
    return {"items_reset": items_reset}
