from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, GuildConfig, License, LicenseStatus, PaymentEvent, Product, RecordStatus, SystemRecord
from app.schemas import MODULES, GuildConfigIn


def module_defaults() -> dict[str, bool]:
    return {module: True for module in MODULES}


async def audit(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    guild_id: str | None = None,
    actor_id: str | None = None,
    entity_id: str | None = None,
    payload: dict | None = None,
) -> None:
    session.add(
        AuditLog(
            guild_id=guild_id,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload or {},
        )
    )


async def get_or_create_config(session: AsyncSession, guild_id: str, guild_name: str | None = None) -> GuildConfig:
    result = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild_id))
    config = result.scalar_one_or_none()
    if config:
        if guild_name and config.guild_name != guild_name:
            config.guild_name = guild_name
        return config
    config = GuildConfig(guild_id=guild_id, guild_name=guild_name, modules=module_defaults())
    session.add(config)
    await session.flush()
    return config


async def active_license_for_guild(session: AsyncSession, guild_id: str) -> License | None:
    result = await session.execute(select(License).where(License.guild_id == guild_id))
    license_record = result.scalar_one_or_none()
    if not license_record or license_record.status != LicenseStatus.active:
        return None
    return license_record


async def activate_license(
    session: AsyncSession,
    *,
    license_key: str,
    guild_id: str,
    guild_name: str | None,
    owner_discord_id: str,
) -> License:
    result = await session.execute(select(License).where(License.key == license_key))
    license_record = result.scalar_one_or_none()
    if not license_record:
        raise ValueError("Licenca nao encontrada.")
    if license_record.status not in {LicenseStatus.pending, LicenseStatus.active}:
        raise ValueError("Licenca bloqueada ou revogada.")
    if license_record.guild_id and license_record.guild_id != guild_id:
        raise ValueError("Licenca ja vinculada a outro servidor.")

    license_record.status = LicenseStatus.active
    license_record.guild_id = guild_id
    license_record.guild_name = guild_name
    license_record.owner_discord_id = owner_discord_id
    license_record.activated_at = datetime.now(timezone.utc)
    await get_or_create_config(session, guild_id, guild_name)
    await audit(
        session,
        action="license.activated",
        entity_type="license",
        entity_id=license_record.key,
        guild_id=guild_id,
        actor_id=owner_discord_id,
        payload={"guild_name": guild_name},
    )
    return license_record


async def upsert_config(session: AsyncSession, guild_id: str, data: GuildConfigIn, actor_id: str | None = None) -> GuildConfig:
    config = await get_or_create_config(session, guild_id, data.guild_name)
    config.guild_name = data.guild_name
    config.admin_role_ids = data.admin_role_ids
    config.log_channel_id = data.log_channel_id
    config.modules = data.modules or module_defaults()
    config.command_permissions = data.command_permissions
    config.messages = data.messages
    config.settings = data.settings
    await audit(
        session,
        action="guild_config.updated",
        entity_type="guild_config",
        entity_id=guild_id,
        guild_id=guild_id,
        actor_id=actor_id,
        payload=data.model_dump(),
    )
    return config


def check_permission(config: GuildConfig, *, module: str, command: str, user_role_ids: list[str], channel_id: str | None, category_id: str | None) -> tuple[bool, str]:
    modules = config.modules or module_defaults()
    if not modules.get(module, False):
        return False, "Modulo desativado para este servidor."

    if set(user_role_ids).intersection(set(config.admin_role_ids or [])):
        return True, "Permitido por cargo administrador do Yuno."

    permissions = config.command_permissions or {}
    rule = permissions.get(f"{module}.{command}") or permissions.get(module) or {}
    allowed_roles = set(rule.get("role_ids") or [])
    allowed_channels = set(rule.get("channel_ids") or [])
    allowed_categories = set(rule.get("category_ids") or [])

    if allowed_roles and not set(user_role_ids).intersection(allowed_roles):
        return False, "Cargo sem permissao para este comando."
    if allowed_channels and channel_id not in allowed_channels:
        return False, "Canal sem permissao para este comando."
    if allowed_categories and category_id not in allowed_categories:
        return False, "Categoria sem permissao para este comando."
    return True, "Permitido."


async def create_pending_license_from_payment(session: AsyncSession, *, reference: str, payload: dict) -> tuple[License, bool]:
    existing_event = await session.execute(select(PaymentEvent).where(PaymentEvent.reference == reference))
    if existing_event.scalar_one_or_none():
        license_result = await session.execute(select(License).where(License.payment_reference == reference))
        license_record = license_result.scalar_one_or_none()
        if license_record:
            return license_record, True

    event = PaymentEvent(provider="mercado_pago", reference=reference, status="approved", raw_payload=payload)
    license_record = License(
        status=LicenseStatus.pending,
        payment_provider="mercado_pago",
        payment_reference=reference,
    )
    session.add_all([event, license_record])
    await session.flush()
    await audit(
        session,
        action="payment.approved",
        entity_type="license",
        entity_id=license_record.key,
        payload={"reference": reference, "provider": "mercado_pago"},
    )
    return license_record, False
