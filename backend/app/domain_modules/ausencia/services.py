from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain_modules.ausencia.domain import (
    AusenciaDomainError,
    compute_window,
    is_near_limit,
    normalize_reason,
    validate_days,
)
from app.domain_modules.ausencia.models import AbsenceRecord
from app.domain_modules.ausencia.schemas import AusenciaConfig
from app.platform.audit import write_audit
from app.platform.models import ModuleConfigVersion, ModuleInstance, ModuleLifecycle
from app.platform.outbox import enqueue_delivery

log = logging.getLogger("yuno.ausencia")


def _http(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


async def _published_configuration(
    session: AsyncSession, guild_id: str, *, require_active: bool = True
) -> tuple[ModuleInstance, ModuleConfigVersion, AusenciaConfig]:
    query = (
        select(ModuleInstance, ModuleConfigVersion)
        .join(
            ModuleConfigVersion,
            ModuleConfigVersion.id == ModuleInstance.published_config_version_id,
        )
        .where(
            ModuleInstance.guild_id == guild_id,
            ModuleInstance.module_key == "ausencia",
            ModuleConfigVersion.guild_id == guild_id,
            ModuleConfigVersion.module_key == "ausencia",
        )
    )
    row = (await session.execute(query)).one_or_none()
    if row is None:
        raise _http(409, "ausencia.not_configured", "Ausencia ainda nao foi publicada.")
    instance, version = row
    if require_active and instance.lifecycle != ModuleLifecycle.active:
        raise _http(409, "ausencia.not_active", "Ausencia nao esta ativa.")
    config = AusenciaConfig.model_validate(version.data or {})
    if require_active and not config.enabled:
        raise _http(409, "ausencia.disabled", "Ausencia esta desabilitada.")
    return instance, version, config


async def effective_configuration(
    session: AsyncSession, *, guild_id: str, require_active: bool = True
) -> tuple[ModuleConfigVersion, AusenciaConfig]:
    _, version, config = await _published_configuration(
        session, guild_id, require_active=require_active
    )
    return version, config


async def register_absence(
    session: AsyncSession,
    *,
    guild_id: str,
    actor_id: str,
    member_display_name: str,
    correlation_id: str,
    dias: int,
    motivo: str | None,
) -> tuple[AbsenceRecord, AusenciaConfig, bool]:
    _, version, config = await _published_configuration(session, guild_id)
    try:
        days = validate_days(dias, max_days=config.max_dias)
        reason = normalize_reason(motivo)
    except AusenciaDomainError as exc:
        raise _http(422, "ausencia.invalid_input", str(exc)) from exc

    now = datetime.now(timezone.utc)
    started_at, ends_at = compute_window(days, now=now)

    record = (
        await session.execute(
            select(AbsenceRecord)
            .where(
                AbsenceRecord.guild_id == guild_id,
                AbsenceRecord.discord_user_id == actor_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    before = None
    if record is None:
        record = AbsenceRecord(
            guild_id=guild_id,
            discord_user_id=actor_id,
            member_display_name=member_display_name,
            days=days,
            reason=reason,
            started_at=started_at,
            ends_at=ends_at,
            overdue_notified=False,
        )
        session.add(record)
    else:
        before = {"days": record.days, "ends_at": record.ends_at.isoformat()}
        record.member_display_name = member_display_name
        record.days = days
        record.reason = reason
        record.started_at = started_at
        record.ends_at = ends_at
        record.overdue_notified = False
    await session.flush()

    await write_audit(
        session,
        guild_id=guild_id,
        module_key="ausencia",
        actor_type="user",
        actor_id=actor_id,
        action="ausencia.registered",
        resource_type="absence_record",
        resource_id=record.id,
        correlation_id=correlation_id,
        before=before,
        after={"days": record.days, "ends_at": record.ends_at.isoformat()},
        config_version=version.version,
    )

    payload = {
        "record_id": record.id,
        "discord_user_id": record.discord_user_id,
        "member_display_name": record.member_display_name,
        "days": record.days,
        "reason": record.reason,
        "started_at": record.started_at.isoformat(),
        "ends_at": record.ends_at.isoformat(),
        "near_limit": is_near_limit(days),
    }
    for renderer_key, destination_type, destination_id in (
        ("ausencia.confirmation", "channel", config.panel_channel_id),
        ("ausencia.log", "channel", config.log_channel_id),
    ):
        if not destination_id:
            continue
        await enqueue_delivery(
            session,
            guild_id=guild_id,
            module_key="ausencia",
            renderer_key=renderer_key,
            destination_type=destination_type,
            destination_id=destination_id,
            resource_type="absence_record",
            resource_id=record.id,
            payload=payload,
            priority=100,
            available_at=now,
            idempotency_key=f"{record.id}:{renderer_key}:{ends_at.isoformat()}",
            correlation_id=correlation_id,
            max_attempts=10,
        )

    await session.commit()
    await session.refresh(record)
    return record, config, is_near_limit(days)


async def list_active(
    session: AsyncSession, *, guild_id: str, now: datetime | None = None, limit: int = 200
) -> list[AbsenceRecord]:
    current = now or datetime.now(timezone.utc)
    return list(
        (
            await session.execute(
                select(AbsenceRecord)
                .where(
                    AbsenceRecord.guild_id == guild_id,
                    AbsenceRecord.ends_at > current,
                )
                .order_by(AbsenceRecord.ends_at.asc())
                .limit(limit)
            )
        ).scalars()
    )


async def sweep_overdue(
    session: AsyncSession,
    *,
    guild_id: str,
    correlation_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    _, version, config = await _published_configuration(session, guild_id, require_active=False)
    current = now or datetime.now(timezone.utc)
    overdue = list(
        (
            await session.execute(
                select(AbsenceRecord)
                .where(
                    AbsenceRecord.guild_id == guild_id,
                    AbsenceRecord.overdue_notified.is_(False),
                    AbsenceRecord.ends_at <= current,
                )
                .with_for_update()
            )
        ).scalars()
    )
    notified = 0
    for record in overdue:
        await enqueue_delivery(
            session,
            guild_id=guild_id,
            module_key="ausencia",
            renderer_key="ausencia.overdue_reminder",
            destination_type="user",
            destination_id=record.discord_user_id,
            resource_type="absence_record",
            resource_id=record.id,
            payload={
                "record_id": record.id,
                "discord_user_id": record.discord_user_id,
                "member_display_name": record.member_display_name,
                "days": record.days,
                "ends_at": record.ends_at.isoformat(),
            },
            priority=100,
            available_at=current,
            idempotency_key=f"{record.id}:overdue:{record.ends_at.isoformat()}",
            correlation_id=correlation_id,
            max_attempts=10,
        )
        record.overdue_notified = True
        await write_audit(
            session,
            guild_id=guild_id,
            module_key="ausencia",
            actor_type="system",
            actor_id=None,
            action="ausencia.overdue_notified",
            resource_type="absence_record",
            resource_id=record.id,
            correlation_id=correlation_id,
            after={"ends_at": record.ends_at.isoformat()},
            config_version=version.version,
        )
        notified += 1
    await session.commit()
    return {"checked_at": current.isoformat(), "notified": notified}
