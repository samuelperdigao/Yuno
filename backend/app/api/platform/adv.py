from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import ActorHeader, CorrelationHeader, require_active_license
from app.core.security import require_bot_token
from app.db import get_session
from app.domain_modules.adv import services
from app.domain_modules.adv.schemas import AdvApplyCommand, AdvRevokeCommand
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
        module_key="adv",
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
        "moderator_id": item.moderator_id,
        "moderator_display_name": item.moderator_display_name,
        "reason": item.reason,
        "created_at": item.created_at,
        "revoked_at": item.revoked_at,
        "revoked_by": item.revoked_by,
        "revoke_reason": item.revoke_reason,
    }


@router.get("/guilds/{guild_id}/modules/adv/config")
async def effective_config(
    guild_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    version, config = await services.effective_configuration(
        session, guild_id=guild_id, require_active=False
    )
    return {"version_id": version.id, "version": version.version, "data": config.model_dump(mode="json")}


@router.post("/guilds/{guild_id}/modules/adv/warnings")
async def apply_warning(
    guild_id: str,
    data: AdvApplyCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="adv.apply",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    record, config = await services.apply_warning(
        session,
        guild_id=guild_id,
        moderator_id=x_yuno_actor_id,
        moderator_display_name=data.moderator_display_name,
        correlation_id=correlation,
        discord_user_id=data.apply.discord_user_id,
        member_display_name=data.member_display_name,
        reason=data.apply.reason,
    )
    return {**_record(record), "config": config.model_dump(mode="json")}


@router.get("/guilds/{guild_id}/modules/adv/warnings")
async def list_recent(
    guild_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    await require_active_license(session, guild_id)
    return [
        _record(item)
        for item in await services.list_recent(session, guild_id=guild_id, limit=limit)
    ]


@router.post("/guilds/{guild_id}/modules/adv/warnings/revoke")
async def revoke_warning(
    guild_id: str,
    data: AdvRevokeCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="adv.revoke",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    record, config = await services.revoke_warning(
        session,
        guild_id=guild_id,
        actor_id=x_yuno_actor_id,
        actor_display_name=data.actor_display_name,
        correlation_id=correlation,
        warning_id=data.revoke.warning_id,
        reason=data.revoke.reason,
    )
    return {**_record(record), "config": config.model_dump(mode="json")}
