from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin_token
from app.db import get_session
from app.schemas import GuildConfigIn, GuildConfigOut
from app.services import get_or_create_config, upsert_config

router = APIRouter(prefix="/guilds", tags=["guilds"], dependencies=[Depends(require_admin_token)])


@router.get("/{guild_id}/config", response_model=GuildConfigOut)
async def get_config(guild_id: str, session: AsyncSession = Depends(get_session)) -> GuildConfigOut:
    config = await get_or_create_config(session, guild_id)
    await session.commit()
    return GuildConfigOut(
        guild_id=config.guild_id,
        guild_name=config.guild_name,
        admin_role_ids=config.admin_role_ids or [],
        log_channel_id=config.log_channel_id,
        modules=config.modules or {},
        command_permissions=config.command_permissions or {},
        messages=config.messages or {},
        settings=config.settings or {},
    )


@router.put("/{guild_id}/config", response_model=GuildConfigOut)
async def save_config(guild_id: str, data: GuildConfigIn, session: AsyncSession = Depends(get_session)) -> GuildConfigOut:
    config = await upsert_config(session, guild_id, data, actor_id="dashboard-admin")
    await session.commit()
    return GuildConfigOut(
        guild_id=config.guild_id,
        guild_name=config.guild_name,
        admin_role_ids=config.admin_role_ids or [],
        log_channel_id=config.log_channel_id,
        modules=config.modules or {},
        command_permissions=config.command_permissions or {},
        messages=config.messages or {},
        settings=config.settings or {},
    )
