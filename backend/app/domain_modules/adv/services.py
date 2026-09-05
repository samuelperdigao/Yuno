from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain_modules.adv.domain import (
    AdvDomainError,
    normalize_discord_id,
    normalize_optional_reason,
    normalize_reason,
)
from app.domain_modules.adv.models import Warning
from app.domain_modules.adv.schemas import AdvConfig
from app.platform.audit import write_audit
from app.platform.models import ModuleConfigVersion, ModuleInstance, ModuleLifecycle
from app.platform.outbox import enqueue_delivery

log = logging.getLogger("yuno.adv")


def _http(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


async def _published_configuration(
    session: AsyncSession, guild_id: str, *, require_active: bool = True
) -> tuple[ModuleInstance, ModuleConfigVersion, AdvConfig]:
    query = (
        select(ModuleInstance, ModuleConfigVersion)
        .join(
            ModuleConfigVersion,
            ModuleConfigVersion.id == ModuleInstance.published_config_version_id,
        )
        .where(
            ModuleInstance.guild_id == guild_id,
            ModuleInstance.module_key == "adv",
            ModuleConfigVersion.guild_id == guild_id,
            ModuleConfigVersion.module_key == "adv",
        )
    )
    row = (await session.execute(query)).one_or_none()
    if row is None:
        raise _http(409, "adv.not_configured", "Advertência ainda não foi publicada.")
    instance, version = row
    if require_active and instance.lifecycle != ModuleLifecycle.active:
        raise _http(409, "adv.not_active", "Advertência não está ativa.")
    config = AdvConfig.model_validate(version.data or {})
    if require_active and not config.enabled:
        raise _http(409, "adv.disabled", "Advertência está desabilitada.")
    return instance, version, config


async def effective_configuration(
    session: AsyncSession, *, guild_id: str, require_active: bool = True
) -> tuple[ModuleConfigVersion, AdvConfig]:
    _, version, config = await _published_configuration(
        session, guild_id, require_active=require_active
    )
    return version, config


async def apply_warning(
    session: AsyncSession,
    *,
    guild_id: str,
    moderator_id: str,
    moderator_display_name: str,
    correlation_id: str,
    discord_user_id: str,
    member_display_name: str,
    reason: str,
) -> tuple[Warning, AdvConfig]:
    _, version, config = await _published_configuration(session, guild_id)
    try:
        target = normalize_discord_id(discord_user_id, field_name="membro advertido")
        clean_reason = normalize_reason(reason)
    except AdvDomainError as exc:
        raise _http(422, "adv.invalid_input", str(exc)) from exc

    now = datetime.now(timezone.utc)
    record = Warning(
        guild_id=guild_id,
        discord_user_id=target,
        member_display_name=member_display_name,
        moderator_id=moderator_id,
        moderator_display_name=moderator_display_name,
        reason=clean_reason,
    )
    session.add(record)
    await session.flush()

    await write_audit(
        session,
        guild_id=guild_id,
        module_key="adv",
        actor_type="user",
        actor_id=moderator_id,
        action="adv.applied",
        resource_type="warning",
        resource_id=record.id,
        correlation_id=correlation_id,
        after={"discord_user_id": target, "reason": clean_reason},
        config_version=version.version,
    )

    if config.log_channel_id:
        await enqueue_delivery(
            session,
            guild_id=guild_id,
            module_key="adv",
            renderer_key="adv.log",
            destination_type="channel",
            destination_id=config.log_channel_id,
            resource_type="warning",
            resource_id=record.id,
            payload={
                "record_id": record.id,
                "discord_user_id": record.discord_user_id,
                "member_display_name": record.member_display_name,
                "moderator_id": record.moderator_id,
                "moderator_display_name": record.moderator_display_name,
                "reason": record.reason,
                "created_at": record.created_at.isoformat() if record.created_at else now.isoformat(),
                "log_title": config.log_title,
                "kind": "applied",
            },
            priority=100,
            available_at=now,
            idempotency_key=f"{record.id}:adv.log:applied",
            correlation_id=correlation_id,
            max_attempts=10,
        )

    await session.commit()
    await session.refresh(record)
    return record, config


async def revoke_warning(
    session: AsyncSession,
    *,
    guild_id: str,
    actor_id: str,
    actor_display_name: str,
    correlation_id: str,
    warning_id: str,
    reason: str | None,
) -> tuple[Warning, AdvConfig]:
    _, version, config = await _published_configuration(session, guild_id, require_active=False)
    try:
        clean_reason = normalize_optional_reason(reason)
    except AdvDomainError as exc:
        raise _http(422, "adv.invalid_input", str(exc)) from exc

    record = (
        await session.execute(
            select(Warning)
            .where(Warning.guild_id == guild_id, Warning.id == warning_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if record is None:
        raise _http(404, "adv.not_found", "Advertência não encontrada.")
    if record.revoked_at is not None:
        raise _http(409, "adv.already_revoked", "Esta advertência já foi revogada.")

    now = datetime.now(timezone.utc)
    record.revoked_at = now
    record.revoked_by = actor_id
    record.revoke_reason = clean_reason
    await session.flush()

    await write_audit(
        session,
        guild_id=guild_id,
        module_key="adv",
        actor_type="user",
        actor_id=actor_id,
        action="adv.revoked",
        resource_type="warning",
        resource_id=record.id,
        correlation_id=correlation_id,
        before={"revoked_at": None},
        after={"revoked_at": now.isoformat()},
        config_version=version.version,
    )

    if config.log_channel_id:
        await enqueue_delivery(
            session,
            guild_id=guild_id,
            module_key="adv",
            renderer_key="adv.log",
            destination_type="channel",
            destination_id=config.log_channel_id,
            resource_type="warning",
            resource_id=record.id,
            payload={
                "record_id": record.id,
                "discord_user_id": record.discord_user_id,
                "member_display_name": record.member_display_name,
                "moderator_id": actor_id,
                "moderator_display_name": actor_display_name,
                "reason": clean_reason,
                "created_at": now.isoformat(),
                "log_title": config.revoke_log_title,
                "kind": "revoked",
            },
            priority=100,
            available_at=now,
            idempotency_key=f"{record.id}:adv.log:revoked",
            correlation_id=correlation_id,
            max_attempts=10,
        )

    await session.commit()
    await session.refresh(record)
    return record, config


async def list_recent(
    session: AsyncSession, *, guild_id: str, limit: int = 50
) -> list[Warning]:
    return list(
        (
            await session.execute(
                select(Warning)
                .where(Warning.guild_id == guild_id)
                .order_by(Warning.created_at.desc())
                .limit(limit)
            )
        ).scalars()
    )
