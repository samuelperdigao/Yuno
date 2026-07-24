from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_bot_token
from app.db import get_session
from app.models import Ausencia, GuildConfig
from app.schemas import (
    AusenciaMessagePatch,
    AusenciaOut,
    AusenciaUpsertIn,
    GuildConfigIn,
    GuildConfigOut,
    LicenseValidateIn,
    LicenseValidateOut,
    PermissionCheckIn,
    PermissionCheckOut,
)
from app.services import active_license_for_guild, audit, check_permission, get_or_create_config, module_defaults, upsert_config

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


def ausencia_out(ausencia: Ausencia) -> AusenciaOut:
    return AusenciaOut(
        guild_id=ausencia.guild_id,
        user_id=ausencia.user_id,
        nome=ausencia.nome,
        dias=ausencia.dias,
        motivo=ausencia.motivo,
        inicio=ausencia.inicio,
        fim=ausencia.fim,
        avisado=ausencia.avisado,
        message_id=ausencia.message_id,
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


@router.post("/guilds/{guild_id}/ausencias", response_model=AusenciaOut)
async def upsert_ausencia(guild_id: str, data: AusenciaUpsertIn, session: AsyncSession = Depends(get_session)) -> AusenciaOut:
    if not await active_license_for_guild(session, guild_id):
        raise HTTPException(status_code=403, detail="Servidor sem licenca ativa.")

    ausencia = await session.get(Ausencia, {"guild_id": guild_id, "user_id": data.user_id})
    if not ausencia:
        ausencia = Ausencia(guild_id=guild_id, user_id=data.user_id)
        session.add(ausencia)

    ausencia.nome = data.nome
    ausencia.dias = data.dias
    ausencia.motivo = data.motivo
    ausencia.inicio = data.inicio
    ausencia.fim = data.fim
    ausencia.avisado = 0

    await audit(
        session,
        action="ausencia.upserted",
        entity_type="ausencia",
        entity_id=data.user_id,
        guild_id=guild_id,
        actor_id=data.user_id,
        payload={"dias": data.dias, "motivo": data.motivo, "fim": data.fim.isoformat()},
    )
    await session.commit()
    return ausencia_out(ausencia)


@router.get("/guilds/{guild_id}/ausencias", response_model=list[AusenciaOut])
async def list_ausencias(
    guild_id: str,
    active_only: bool = False,
    pending_notice_only: bool = False,
    session: AsyncSession = Depends(get_session),
) -> list[AusenciaOut]:
    if not await active_license_for_guild(session, guild_id):
        raise HTTPException(status_code=403, detail="Servidor sem licenca ativa.")

    now = datetime.now(timezone.utc)
    query = select(Ausencia).where(Ausencia.guild_id == guild_id)
    if active_only:
        query = query.where(Ausencia.fim > now)
    if pending_notice_only:
        query = query.where(Ausencia.fim <= now, Ausencia.avisado == 0)
    result = await session.execute(query.order_by(Ausencia.fim.asc()))
    return [ausencia_out(ausencia) for ausencia in result.scalars()]


@router.patch("/guilds/{guild_id}/ausencias/{user_id}/message", response_model=AusenciaOut)
async def update_ausencia_message(
    guild_id: str,
    user_id: str,
    data: AusenciaMessagePatch,
    session: AsyncSession = Depends(get_session),
) -> AusenciaOut:
    if not await active_license_for_guild(session, guild_id):
        raise HTTPException(status_code=403, detail="Servidor sem licenca ativa.")
    ausencia = await session.get(Ausencia, {"guild_id": guild_id, "user_id": user_id})
    if not ausencia:
        raise HTTPException(status_code=404, detail="Ausencia nao encontrada.")
    ausencia.message_id = data.message_id
    await session.commit()
    return ausencia_out(ausencia)


@router.patch("/guilds/{guild_id}/ausencias/{user_id}/avisado", response_model=AusenciaOut)
async def mark_ausencia_avisado(guild_id: str, user_id: str, session: AsyncSession = Depends(get_session)) -> AusenciaOut:
    if not await active_license_for_guild(session, guild_id):
        raise HTTPException(status_code=403, detail="Servidor sem licenca ativa.")
    ausencia = await session.get(Ausencia, {"guild_id": guild_id, "user_id": user_id})
    if not ausencia:
        raise HTTPException(status_code=404, detail="Ausencia nao encontrada.")
    ausencia.avisado = 1
    await session.commit()
    return ausencia_out(ausencia)
