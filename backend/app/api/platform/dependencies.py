from __future__ import annotations

from typing import Annotated
from fastapi import Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.models import GuildAdminRole
from app.platform.schemas import ActorContextIn
from app.services import active_license_for_guild
from sqlalchemy import select


ActorHeader = Annotated[str, Header(alias="x-yuno-actor-id", min_length=1, max_length=32, pattern=r"^\d+$")]
CorrelationHeader = Annotated[str | None, Header(alias="x-yuno-correlation-id", max_length=80)]


async def require_active_license(session: AsyncSession, guild_id: str) -> None:
    if not await active_license_for_guild(session, guild_id):
        raise HTTPException(status_code=403, detail="Servidor sem licenca ativa.")


async def require_platform_admin(
    session: AsyncSession,
    *,
    guild_id: str,
    actor_header: str,
    actor: ActorContextIn,
    correlation_header: str | None = None,
    allow_system: bool = False,
) -> str:
    if correlation_header and correlation_header != actor.correlation_id:
        raise HTTPException(status_code=400, detail="Correlation ID divergente.")
    if actor.guild_id != guild_id:
        raise HTTPException(status_code=403, detail="ActorContext pertence a outra guild.")
    if actor.actor_type == "system":
        if allow_system:
            return actor.correlation_id
        raise HTTPException(status_code=403, detail="Automacao nao pode executar esta acao administrativa.")
    if actor.user_id != actor_header:
        raise HTTPException(status_code=403, detail="Ator do payload nao corresponde ao ator autenticado.")
    if actor.is_guild_owner or "administrator" in actor.discord_permissions or "manage_guild" in actor.discord_permissions:
        return actor.correlation_id
    admin_roles = set(
        (
            await session.execute(
                select(GuildAdminRole.role_id).where(GuildAdminRole.guild_id == guild_id)
            )
        ).scalars()
    )
    if admin_roles.intersection(actor.role_ids):
        return actor.correlation_id
    raise HTTPException(status_code=403, detail="Ator nao administra a Central desta guild.")
