from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import ActorHeader, CorrelationHeader, require_active_license, require_platform_admin
from app.core.security import require_bot_token
from app.db import get_session
from app.platform.schemas import GuildAdminRolesIn, GuildProfileOut, GuildProfileUpdateIn
from app.platform.tenancy import get_or_create_profile, read_admin_roles, replace_admin_roles, update_profile


router = APIRouter(dependencies=[Depends(require_bot_token)])


async def profile_out(session: AsyncSession, item) -> GuildProfileOut:
    return GuildProfileOut(
        guild_id=item.guild_id,
        name=item.name,
        locale=item.locale,
        timezone=item.timezone,
        preferences=item.preferences or {},
        admin_role_ids=await read_admin_roles(session, guild_id=item.guild_id),
    )


@router.get("/guilds/{guild_id}/profile", response_model=GuildProfileOut)
async def read_profile(
    guild_id: str, session: AsyncSession = Depends(get_session)
) -> GuildProfileOut:
    await require_active_license(session, guild_id)
    profile = await get_or_create_profile(session, guild_id=guild_id)
    await session.commit()
    return await profile_out(session, profile)


@router.put("/guilds/{guild_id}/profile", response_model=GuildProfileOut)
async def write_profile(
    guild_id: str,
    data: GuildProfileUpdateIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> GuildProfileOut:
    await require_active_license(session, guild_id)
    correlation = await require_platform_admin(
        session, guild_id=guild_id, actor_header=x_yuno_actor_id, actor=data.actor,
        correlation_header=x_yuno_correlation_id,
    )
    profile = await update_profile(
        session,
        guild_id=guild_id,
        actor_id=x_yuno_actor_id,
        name=data.name,
        locale=data.locale,
        timezone_name=data.timezone,
        preferences=data.preferences,
        correlation_id=correlation,
    )
    return await profile_out(session, profile)


@router.put("/guilds/{guild_id}/admin-roles", response_model=GuildProfileOut)
async def write_admin_roles(
    guild_id: str,
    data: GuildAdminRolesIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> GuildProfileOut:
    await require_active_license(session, guild_id)
    correlation = await require_platform_admin(
        session, guild_id=guild_id, actor_header=x_yuno_actor_id, actor=data.actor,
        correlation_header=x_yuno_correlation_id,
    )
    profile = await get_or_create_profile(session, guild_id=guild_id)
    await replace_admin_roles(
        session,
        guild_id=guild_id,
        actor_id=x_yuno_actor_id,
        role_ids=data.role_ids,
        correlation_id=correlation,
    )
    return await profile_out(session, profile)
