from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import ActorHeader, CorrelationHeader, require_active_license
from app.core.security import require_bot_token
from app.db import get_session
from app.domain_modules.anuncio import services
from app.domain_modules.anuncio.schemas import AnuncioPublishCommand
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
        module_key="anuncio",
        capability_key=capability,
        actor=actor,
    )
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)
    return actor.correlation_id


@router.get("/guilds/{guild_id}/modules/anuncio/config")
async def effective_config(
    guild_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    version, config = await services.effective_configuration(
        session, guild_id=guild_id, require_active=False
    )
    return {"version_id": version.id, "version": version.version, "data": config.model_dump(mode="json")}


@router.post("/guilds/{guild_id}/modules/anuncio/publish")
async def publish(
    guild_id: str,
    data: AnuncioPublishCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="anuncio.publish",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    config, version = await services.publish_announcement(
        session,
        guild_id=guild_id,
        actor_id=x_yuno_actor_id,
        correlation_id=correlation,
        titulo=data.anuncio.titulo,
        conteudo=data.anuncio.conteudo,
        mencionar_everyone=data.anuncio.mencionar_everyone,
        anexou_arquivo=data.anuncio.anexou_arquivo,
    )
    return {"config": config.model_dump(mode="json"), "version": version}
