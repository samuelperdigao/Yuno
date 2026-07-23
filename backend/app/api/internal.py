from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_bot_token
from app.db import get_session
from app.models import GuildConfig
from app.schemas import GuildConfigIn, GuildConfigOut, LicenseValidateIn, LicenseValidateOut, PermissionCheckIn, PermissionCheckOut
from app.services import active_license_for_guild, check_permission, get_or_create_config, module_defaults, upsert_config

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_bot_token)])


def config_out(config: GuildConfig) -> GuildConfigOut:
    return GuildConfigOut(
        guild_id=config.guild_id,
        guild_name=config.guild_name,
        admin_role_ids=config.admin_role_ids or [],
        log_channel_id=config.log_channel_id,
        modules=config.modules or module_defaults(),
        command_permissions=config.command_permissions or {},
        messages=config.messages or {},
        settings=config.settings or {},
    )


@router.post("/licenses/validate", response_model=LicenseValidateOut)
async def validate_license(data: LicenseValidateIn, session: AsyncSession = Depends(get_session)) -> LicenseValidateOut:
    license_record = await active_license_for_guild(session, data.guild_id)
    config = await get_or_create_config(session, data.guild_id)
    if not license_record:
        return LicenseValidateOut(allowed=False, status="missing", guild_id=data.guild_id, modules=config.modules or module_defaults())
    return LicenseValidateOut(allowed=True, status=license_record.status, guild_id=data.guild_id, modules=config.modules or module_defaults())


@router.post("/permissions/check", response_model=PermissionCheckOut)
async def permission_check(data: PermissionCheckIn, session: AsyncSession = Depends(get_session)) -> PermissionCheckOut:
    license_record = await active_license_for_guild(session, data.guild_id)
    if not license_record:
        return PermissionCheckOut(allowed=False, reason="Servidor sem licenca ativa.")
    config = await get_or_create_config(session, data.guild_id)
    allowed, reason = check_permission(
        config,
        module=data.module,
        command=data.command,
        user_role_ids=data.user_role_ids,
        channel_id=data.channel_id,
        category_id=data.category_id,
    )
    return PermissionCheckOut(allowed=allowed, reason=reason)


@router.get("/guilds/{guild_id}/config", response_model=GuildConfigOut)
async def get_internal_config(guild_id: str, session: AsyncSession = Depends(get_session)) -> GuildConfigOut:
    if not await active_license_for_guild(session, guild_id):
        raise HTTPException(status_code=403, detail="Servidor sem licenca ativa.")
    config = await get_or_create_config(session, guild_id)
    await session.commit()
    return config_out(config)


@router.put("/guilds/{guild_id}/config", response_model=GuildConfigOut)
async def save_internal_config(guild_id: str, data: GuildConfigIn, session: AsyncSession = Depends(get_session)) -> GuildConfigOut:
    if not await active_license_for_guild(session, guild_id):
        raise HTTPException(status_code=403, detail="Servidor sem licenca ativa.")
    config = await upsert_config(session, guild_id, data, actor_id="discord-bot")
    await session.commit()
    return config_out(config)
