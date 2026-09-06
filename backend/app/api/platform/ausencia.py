from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import ActorHeader, CorrelationHeader, require_active_license
from app.core.security import require_bot_token
from app.db import get_session
from app.domain_modules.ausencia import services
from app.domain_modules.ausencia.schemas import AusenciaRegisterCommand, AusenciaSweepCommand
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
        module_key="ausencia",
        capability_key=capability,
        actor=actor,
        resource_id=resource_id,
    )
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)
    return actor.correlation_id


def _record(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "guild_id": item.guild_id,
        "discord_user_id": item.discord_user_id,
        "member_display_name": item.member_display_name,
        "days": item.days,
        "reason": item.reason,
        "started_at": item.started_at,
        "ends_at": item.ends_at,
        "overdue_notified": item.overdue_notified,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.get("/guilds/{guild_id}/modules/ausencia/config")
async def effective_config(
    guild_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    version, config = await services.effective_configuration(
        session, guild_id=guild_id, require_active=False
    )
    return {"version_id": version.id, "version": version.version, "data": config.model_dump(mode="json")}


@router.post("/guilds/{guild_id}/modules/ausencia/records")
async def register_absence(
    guild_id: str,
    data: AusenciaRegisterCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="ausencia.register",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    record, config, near_limit = await services.register_absence(
        session,
        guild_id=guild_id,
        actor_id=x_yuno_actor_id,
        member_display_name=data.member_display_name,
        correlation_id=correlation,
        dias=data.registro.dias,
        motivo=data.registro.motivo,
    )
    return {
        **_record(record),
        "config": config.model_dump(mode="json"),
        "near_limit": near_limit,
    }


@router.get("/guilds/{guild_id}/modules/ausencia/records")
async def list_active(
    guild_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    await require_active_license(session, guild_id)
    return [
        _record(item)
        for item in await services.list_active(session, guild_id=guild_id, limit=limit)
    ]


@router.post("/guilds/{guild_id}/modules/ausencia/overdue/sweep")
async def sweep_overdue(
    guild_id: str,
    data: AusenciaSweepCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="ausencia.notify",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await services.sweep_overdue(session, guild_id=guild_id, correlation_id=correlation)
