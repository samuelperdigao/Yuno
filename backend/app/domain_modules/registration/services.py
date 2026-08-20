from __future__ import annotations

import secrets
import unicodedata
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain_modules.registration.domain import (
    CompensationState,
    OrganizationMemberStatus,
    RegistrationDomainError,
    RegistrationRequestStatus,
    ensure_request_transition,
    normalize_name,
    validate_player_id,
)
from app.domain_modules.registration.models import OrganizationMember, RegistrationRequest
from app.domain_modules.registration.schemas import RegistrationConfig, RegistrationSubmit
from app.platform.audit import write_audit
from app.platform.models import (
    AutomationTask,
    DeliveryOutbox,
    ModuleConfigVersion,
    ModuleInstance,
    ModuleLifecycle,
)


CLAIM_LEASE = timedelta(minutes=5)
log = logging.getLogger("yuno.registration")


def _log_phase(
    phase: str,
    *,
    guild_id: str,
    request_id: str,
    correlation_id: str,
    level: int = logging.INFO,
) -> None:
    log.log(
        level,
        "registration_phase",
        extra={
            "guild_id": guild_id,
            "registration_request_id": request_id,
            "correlation_id": correlation_id,
            "operational_phase": phase,
        },
    )


def _http(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


async def _commit_refresh(session: AsyncSession, *items: Any) -> None:
    """Commit and eagerly reload server-generated timestamps for async callers."""
    await session.commit()
    for item in items:
        await session.refresh(item)


async def _owned_request(
    session: AsyncSession,
    *,
    guild_id: str,
    request_id: str,
    lock: bool = False,
) -> RegistrationRequest:
    query = select(RegistrationRequest).where(
        RegistrationRequest.guild_id == guild_id,
        RegistrationRequest.id == request_id,
    )
    if lock:
        query = query.with_for_update()
    item = (await session.execute(query)).scalar_one_or_none()
    if item is None:
        raise _http(404, "registration.request_not_found", "Solicitacao nao encontrada nesta guild.")
    return item


async def _published_configuration(
    session: AsyncSession, guild_id: str, *, require_active: bool = True
) -> tuple[ModuleInstance, ModuleConfigVersion, RegistrationConfig]:
    query = (
        select(ModuleInstance, ModuleConfigVersion)
        .join(
            ModuleConfigVersion,
            ModuleConfigVersion.id == ModuleInstance.published_config_version_id,
        )
        .where(
            ModuleInstance.guild_id == guild_id,
            ModuleInstance.module_key == "registration",
            ModuleConfigVersion.guild_id == guild_id,
            ModuleConfigVersion.module_key == "registration",
        )
    )
    row = (await session.execute(query)).one_or_none()
    if row is None:
        raise _http(409, "registration.not_configured", "Registro ainda nao foi publicado.")
    instance, version = row
    if require_active and instance.lifecycle != ModuleLifecycle.active:
        raise _http(409, "registration.not_active", "Registro nao esta ativo.")
    config = RegistrationConfig.model_validate(version.data or {})
    if require_active and not config.enabled:
        raise _http(409, "registration.disabled", "Registro esta desabilitado.")
    return instance, version, config


async def effective_configuration(
    session: AsyncSession, *, guild_id: str, require_active: bool = True
) -> tuple[ModuleConfigVersion, RegistrationConfig]:
    _, version, config = await _published_configuration(
        session, guild_id, require_active=require_active
    )
    return version, config


async def _audit(
    session: AsyncSession,
    *,
    guild_id: str,
    actor_id: str | None,
    action: str,
    request_id: str,
    correlation_id: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    config_version: int | None = None,
    result: str = "success",
) -> None:
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="registration",
        actor_type="user" if actor_id else "system",
        actor_id=actor_id,
        action=action,
        resource_type="registration_request",
        resource_id=request_id,
        correlation_id=correlation_id,
        before=before,
        after=after,
        config_version=config_version,
        result=result,
    )


async def _queue(
    session: AsyncSession,
    *,
    guild_id: str,
    renderer_key: str,
    destination_type: str,
    destination_id: str | None,
    request_id: str,
    event: str,
    payload: dict[str, Any],
    correlation_id: str,
    max_attempts: int = 5,
) -> None:
    if not destination_id:
        return
    key = f"{request_id}:{event}:{destination_type}:{destination_id}"
    exists = await session.scalar(
        select(DeliveryOutbox.id).where(
            DeliveryOutbox.guild_id == guild_id,
            DeliveryOutbox.module_key == "registration",
            DeliveryOutbox.idempotency_key == key,
        )
    )
    if exists:
        return
    session.add(
        DeliveryOutbox(
            guild_id=guild_id,
            module_key="registration",
            renderer_key=renderer_key,
            destination_type=destination_type,
            destination_id=destination_id,
            resource_type="registration_request",
            resource_id=request_id,
            payload=payload,
            available_at=datetime.now(timezone.utc),
            idempotency_key=key,
            correlation_id=correlation_id,
            max_attempts=max_attempts,
        )
    )


async def get_request(
    session: AsyncSession, *, guild_id: str, request_id: str
) -> RegistrationRequest:
    return await _owned_request(session, guild_id=guild_id, request_id=request_id)


async def list_requests(
    session: AsyncSession,
    *,
    guild_id: str,
    status: RegistrationRequestStatus | None = None,
    discord_user_id: str | None = None,
    limit: int = 100,
) -> list[RegistrationRequest]:
    query = select(RegistrationRequest).where(RegistrationRequest.guild_id == guild_id)
    if status is not None:
        query = query.where(RegistrationRequest.status == status)
    if discord_user_id is not None:
        query = query.where(RegistrationRequest.discord_user_id == discord_user_id)
    return list(
        (
            await session.execute(
                query.order_by(RegistrationRequest.created_at.desc()).limit(limit)
            )
        ).scalars()
    )


async def submit_request(
    session: AsyncSession,
    *,
    guild_id: str,
    actor_id: str,
    correlation_id: str,
    data: RegistrationSubmit,
    panel_config_version: int | None = None,
) -> RegistrationRequest:
    instance, current_version, current_config = await _published_configuration(session, guild_id)
    if panel_config_version is None or panel_config_version == current_version.version:
        version, config = current_version, current_config
    else:
        version = (
            await session.execute(
                select(ModuleConfigVersion).where(
                    ModuleConfigVersion.module_instance_id == instance.id,
                    ModuleConfigVersion.guild_id == guild_id,
                    ModuleConfigVersion.module_key == "registration",
                    ModuleConfigVersion.version == panel_config_version,
                )
            )
        ).scalar_one_or_none()
        if version is None:
            raise _http(409, "registration.panel_outdated", "Versao do painel indisponivel.")
        config = RegistrationConfig.model_validate(version.data or {})
        if not config.enabled:
            raise _http(409, "registration.disabled", "Registro esta desabilitado.")
    name = normalize_name(data.name)
    if not config.name_min_length <= len(name) <= config.name_max_length:
        raise _http(
            422,
            "registration.invalid_name",
            f"O nome deve conter entre {config.name_min_length} e {config.name_max_length} caracteres.",
        )
    try:
        player_id = validate_player_id(
            data.player_id,
            numeric_only=config.player_id_numeric_only,
            min_length=config.player_id_min_length,
            max_length=config.player_id_max_length,
        )
    except RegistrationDomainError as exc:
        raise _http(422, "registration.invalid_player_id", str(exc)) from exc
    original_player_id = unicodedata.normalize("NFKC", data.player_id).strip()

    active_member = (
        await session.execute(
            select(OrganizationMember).where(
                OrganizationMember.guild_id == guild_id,
                OrganizationMember.discord_user_id == actor_id,
                OrganizationMember.status == OrganizationMemberStatus.active,
            )
        )
    ).scalar_one_or_none()
    if active_member is not None:
        raise _http(409, "registration.already_registered", config.already_registered_message)
    open_request = (
        await session.execute(
            select(RegistrationRequest).where(
                RegistrationRequest.guild_id == guild_id,
                RegistrationRequest.discord_user_id == actor_id,
                RegistrationRequest.status.in_(
                    [RegistrationRequestStatus.pending, RegistrationRequestStatus.processing]
                ),
            )
        )
    ).scalar_one_or_none()
    if open_request is not None:
        raise _http(409, "registration.already_pending", config.already_pending_message)
    if not config.allow_resubmit_after_rejection:
        rejected = await session.scalar(
            select(func.count(RegistrationRequest.id)).where(
                RegistrationRequest.guild_id == guild_id,
                RegistrationRequest.discord_user_id == actor_id,
                RegistrationRequest.status == RegistrationRequestStatus.rejected,
            )
        )
        if rejected:
            raise _http(
                409,
                "registration.resubmit_not_allowed",
                config.resubmit_not_allowed_message,
            )
    duplicate = await session.scalar(
        select(OrganizationMember.id).where(
            OrganizationMember.guild_id == guild_id,
            OrganizationMember.player_id_normalized == player_id,
            OrganizationMember.status == OrganizationMemberStatus.active,
        )
    )
    if duplicate is not None:
        raise _http(409, "registration.duplicate_player_id", config.duplicate_id_message)

    request = RegistrationRequest(
        guild_id=guild_id,
        discord_user_id=actor_id,
        submitted_name=name,
        player_id_original=original_player_id,
        player_id_normalized=player_id,
        status=RegistrationRequestStatus.pending,
        config_version_submitted_id=version.id,
    )
    session.add(request)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise _http(409, "registration.already_pending", config.already_pending_message) from exc
    await _audit(
        session,
        guild_id=guild_id,
        actor_id=actor_id,
        action="registration.request_submitted",
        request_id=request.id,
        correlation_id=correlation_id,
        after={"status": request.status.value, "config_version_id": version.id},
        config_version=version.version,
    )
    await _queue(
        session,
        guild_id=guild_id,
        renderer_key="registration.review_request",
        destination_type="panel",
        destination_id=config.approval_channel_id,
        request_id=request.id,
        event="submitted",
        payload={"request_id": request.id, "config_version_id": version.id},
        correlation_id=correlation_id,
        max_attempts=10,
    )
    await _commit_refresh(session, request)
    _log_phase(
        "submitted",
        guild_id=guild_id,
        request_id=request.id,
        correlation_id=correlation_id,
    )
    return request


async def claim_approval(
    session: AsyncSession,
    *,
    guild_id: str,
    request_id: str,
    actor_id: str,
    correlation_id: str,
    operation_token: str | None = None,
) -> tuple[RegistrationRequest, RegistrationConfig]:
    request = await _owned_request(
        session, guild_id=guild_id, request_id=request_id, lock=True
    )
    if request.status == RegistrationRequestStatus.approved and operation_token:
        if secrets.compare_digest(request.processing_token or "", operation_token):
            _, config = await effective_configuration(session, guild_id=guild_id)
            return request, config
    if request.status == RegistrationRequestStatus.processing:
        if operation_token and secrets.compare_digest(
            request.processing_token or "", operation_token
        ):
            version = await session.get(ModuleConfigVersion, request.config_version_reviewed_id)
            if version is None or version.guild_id != guild_id:
                raise _http(409, "registration.config_changed", "Configuracao revisada indisponivel.")
            return request, RegistrationConfig.model_validate(version.data or {})
        raise _http(
            409,
            "registration.already_processing",
            "Solicitacao ja processada ou em processamento.",
        )
    if request.status != RegistrationRequestStatus.pending:
        raise _http(
            409,
            "registration.already_decided",
            "Solicitacao ja processada ou em processamento.",
        )
    _, version, config = await _published_configuration(session, guild_id)
    duplicate_member = await session.scalar(
        select(OrganizationMember.id).where(
            OrganizationMember.guild_id == guild_id,
            OrganizationMember.player_id_normalized == request.player_id_normalized,
            OrganizationMember.status == OrganizationMemberStatus.active,
            OrganizationMember.discord_user_id != request.discord_user_id,
        )
    )
    if duplicate_member is not None:
        raise _http(409, "registration.duplicate_player_id", config.duplicate_id_message)
    competing = await session.scalar(
        select(RegistrationRequest.id).where(
            RegistrationRequest.guild_id == guild_id,
            RegistrationRequest.player_id_normalized == request.player_id_normalized,
            RegistrationRequest.status == RegistrationRequestStatus.processing,
            RegistrationRequest.id != request.id,
        )
    )
    if competing is not None:
        raise _http(
            409,
            "registration.player_id_processing",
            "Este ID esta em processamento por outra solicitacao.",
        )
    ensure_request_transition(request.status, RegistrationRequestStatus.processing)
    now = datetime.now(timezone.utc)
    request.status = RegistrationRequestStatus.processing
    request.processing_token = operation_token or secrets.token_urlsafe(32)
    request.processing_actor_id = actor_id
    request.processing_started_at = now
    request.processing_lease_until = now + CLAIM_LEASE
    request.config_version_reviewed_id = version.id
    request.revision += 1
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _http(
            409,
            "registration.player_id_processing",
            "Este ID esta em processamento por outra solicitacao.",
        ) from exc
    await session.refresh(request)
    _log_phase(
        "claimed",
        guild_id=guild_id,
        request_id=request.id,
        correlation_id=correlation_id,
    )
    return request, config


async def record_preflight(
    session: AsyncSession,
    *,
    guild_id: str,
    request_id: str,
    actor_id: str,
    operation_token: str,
    previous_nickname: str | None,
    role_was_present: bool,
    target_nickname: str,
    correlation_id: str,
) -> RegistrationRequest:
    request = await _owned_request(
        session, guild_id=guild_id, request_id=request_id, lock=True
    )
    _require_claim(request, actor_id=actor_id, operation_token=operation_token)
    request.previous_nickname = previous_nickname
    request.target_nickname = target_nickname
    request.role_was_present = role_was_present
    request.compensation_state = CompensationState.prepared
    request.revision += 1
    await _commit_refresh(session, request)
    _log_phase(
        "discord_preflight_recorded",
        guild_id=guild_id,
        request_id=request.id,
        correlation_id=correlation_id,
    )
    return request


def _require_claim(
    request: RegistrationRequest,
    *,
    actor_id: str,
    operation_token: str,
    recovery: bool = False,
) -> None:
    if request.status == RegistrationRequestStatus.approved and secrets.compare_digest(
        request.processing_token or "", operation_token
    ):
        return
    if request.status != RegistrationRequestStatus.processing:
        raise _http(409, "registration.not_processing", "Solicitacao nao esta em processamento.")
    if not secrets.compare_digest(request.processing_token or "", operation_token):
        raise _http(409, "registration.invalid_claim", "Claim de aprovacao invalido.")
    if not recovery and request.processing_actor_id != actor_id:
        raise _http(409, "registration.invalid_actor", "Claim pertence a outro administrador.")


async def record_discord_step(
    session: AsyncSession,
    *,
    guild_id: str,
    request_id: str,
    actor_id: str,
    operation_token: str,
    step: str,
    correlation_id: str,
) -> RegistrationRequest:
    request = await _owned_request(
        session, guild_id=guild_id, request_id=request_id, lock=True
    )
    _require_claim(request, actor_id=actor_id, operation_token=operation_token)
    if request.compensation_state != CompensationState.prepared:
        raise _http(409, "registration.preflight_missing", "Snapshot de compensacao ausente.")
    if step == "nickname":
        request.nickname_applied = True
    elif step == "role":
        if not request.nickname_applied:
            raise _http(409, "registration.step_order", "Aplique o nickname antes do cargo.")
        request.role_applied = True
    else:
        raise _http(422, "registration.invalid_step", "Passo Discord desconhecido.")
    request.revision += 1
    await _commit_refresh(session, request)
    _log_phase(
        f"discord_{step}_recorded",
        guild_id=guild_id,
        request_id=request.id,
        correlation_id=correlation_id,
    )
    return request


async def complete_approval(
    session: AsyncSession,
    *,
    guild_id: str,
    request_id: str,
    actor_id: str,
    correlation_id: str,
    operation_token: str,
    recovery: bool = False,
) -> tuple[RegistrationRequest, OrganizationMember]:
    request = await _owned_request(
        session, guild_id=guild_id, request_id=request_id, lock=True
    )
    _require_claim(
        request,
        actor_id=actor_id,
        operation_token=operation_token,
        recovery=recovery,
    )
    existing_member = (
        await session.execute(
            select(OrganizationMember).where(
                OrganizationMember.guild_id == guild_id,
                OrganizationMember.discord_user_id == request.discord_user_id,
            )
        )
    ).scalar_one_or_none()
    if request.status == RegistrationRequestStatus.approved:
        if existing_member is None:
            raise _http(409, "registration.member_missing", "Cadastro aprovado sem identidade duravel.")
        return request, existing_member
    if not request.nickname_applied or not request.role_applied:
        raise _http(409, "registration.discord_incomplete", "Passos Discord obrigatorios incompletos.")
    _, version, config = await _published_configuration(session, guild_id)
    if version.id != request.config_version_reviewed_id:
        raise _http(409, "registration.config_changed", "A configuracao publicada mudou durante a aprovacao.")
    duplicate_member = await session.scalar(
        select(OrganizationMember.id).where(
            OrganizationMember.guild_id == guild_id,
            OrganizationMember.player_id_normalized == request.player_id_normalized,
            OrganizationMember.status == OrganizationMemberStatus.active,
            OrganizationMember.discord_user_id != request.discord_user_id,
        )
    )
    if duplicate_member is not None:
        raise _http(409, "registration.duplicate_player_id", config.duplicate_id_message)
    now = datetime.now(timezone.utc)
    if existing_member is None:
        existing_member = OrganizationMember(
            guild_id=guild_id,
            discord_user_id=request.discord_user_id,
            player_id_original=request.player_id_original,
            player_id_normalized=request.player_id_normalized,
            name=request.submitted_name,
            status=OrganizationMemberStatus.active,
            approved_request_id=request.id,
            activated_at=now,
        )
        session.add(existing_member)
    else:
        existing_member.player_id_original = request.player_id_original
        existing_member.player_id_normalized = request.player_id_normalized
        existing_member.name = request.submitted_name
        existing_member.status = OrganizationMemberStatus.active
        existing_member.approved_request_id = request.id
        existing_member.activated_at = now
        existing_member.deactivated_at = None
    ensure_request_transition(request.status, RegistrationRequestStatus.approved)
    request.status = RegistrationRequestStatus.approved
    request.reviewed_by = actor_id
    request.reviewed_at = now
    request.approved_at = now
    request.processing_lease_until = None
    request.compensation_state = CompensationState.none
    request.revision += 1
    await session.flush()
    await _audit(
        session,
        guild_id=guild_id,
        actor_id=actor_id,
        action="registration.request_approved",
        request_id=request.id,
        correlation_id=correlation_id,
        before={"status": RegistrationRequestStatus.processing.value},
        after={"status": request.status.value, "member_id": existing_member.id},
        config_version=version.version,
    )
    await _decision_deliveries(
        session,
        request=request,
        config=config,
        event="approved",
        correlation_id=correlation_id,
        dm_message=config.approved_message,
    )
    try:
        async with session.begin_nested():
            from app.domain_modules.tags.services import request_member_sync

            await request_member_sync(
                session,
                guild_id=guild_id,
                discord_user_id=request.discord_user_id,
                observed_fingerprint=None,
                reason="registration_approved",
                correlation_id=correlation_id,
                commit=False,
            )
    except Exception:
        log.exception(
            "tags_sync_enqueue_failed guild_id=%s request_id=%s correlation_id=%s",
            guild_id,
            request.id,
            correlation_id,
        )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _http(409, "registration.duplicate_player_id", config.duplicate_id_message) from exc
    await session.refresh(request)
    await session.refresh(existing_member)
    _log_phase(
        "approved",
        guild_id=guild_id,
        request_id=request.id,
        correlation_id=correlation_id,
    )
    return request, existing_member


async def _decision_deliveries(
    session: AsyncSession,
    *,
    request: RegistrationRequest,
    config: RegistrationConfig,
    event: str,
    correlation_id: str,
    dm_message: str,
) -> None:
    common = {
        "request_id": request.id,
        "decision": event,
        "reason": request.rejection_reason,
    }
    await _queue(
        session,
        guild_id=request.guild_id,
        renderer_key="registration.review_update",
        destination_type="panel",
        destination_id=request.review_channel_id or config.approval_channel_id,
        request_id=request.id,
        event=f"review-{event}",
        payload=common,
        correlation_id=correlation_id,
        max_attempts=10,
    )
    await _queue(
        session,
        guild_id=request.guild_id,
        renderer_key=f"registration.log_{event}",
        destination_type="channel",
        destination_id=config.log_channel_id,
        request_id=request.id,
        event=f"log-{event}",
        payload=common,
        correlation_id=correlation_id,
    )
    await _queue(
        session,
        guild_id=request.guild_id,
        renderer_key=f"registration.member_{event}",
        destination_type="user",
        destination_id=request.discord_user_id,
        request_id=request.id,
        event=f"dm-{event}",
        payload={**common, "message": dm_message},
        correlation_id=correlation_id,
    )


async def fail_approval(
    session: AsyncSession,
    *,
    guild_id: str,
    request_id: str,
    actor_id: str,
    correlation_id: str,
    operation_token: str,
    compensated: bool,
    error_code: str,
    recovery: bool = False,
) -> RegistrationRequest:
    request = await _owned_request(
        session, guild_id=guild_id, request_id=request_id, lock=True
    )
    _require_claim(
        request,
        actor_id=actor_id,
        operation_token=operation_token,
        recovery=recovery,
    )
    request.last_error_code = error_code
    before = {"status": request.status.value}
    if compensated:
        ensure_request_transition(request.status, RegistrationRequestStatus.pending)
        request.status = RegistrationRequestStatus.pending
        request.processing_token = None
        request.processing_actor_id = None
        request.processing_started_at = None
        request.processing_lease_until = None
        request.config_version_reviewed_id = None
        request.previous_nickname = None
        request.target_nickname = None
        request.role_was_present = None
        request.nickname_applied = False
        request.role_applied = False
        request.compensation_state = CompensationState.complete
    else:
        request.compensation_state = CompensationState.failed
        key = f"approval-recovery:{request.id}:{request.revision}"
        existing = await session.scalar(
            select(AutomationTask.id).where(
                AutomationTask.guild_id == guild_id,
                AutomationTask.module_key == "registration",
                AutomationTask.job_key == "registration.processing.recover",
                AutomationTask.idempotency_key == key,
            )
        )
        if existing is None:
            session.add(
                AutomationTask(
                    guild_id=guild_id,
                    module_key="registration",
                    job_key="registration.processing.recover",
                    resource_type="registration_request",
                    resource_id=request.id,
                    payload={"request_id": request.id},
                    due_at=request.processing_lease_until or datetime.now(timezone.utc),
                    idempotency_key=key,
                    correlation_id=correlation_id,
                    max_attempts=10,
                )
            )
    request.revision += 1
    await _audit(
        session,
        guild_id=guild_id,
        actor_id=actor_id,
        action="registration.approval_failed",
        request_id=request.id,
        correlation_id=correlation_id,
        before=before,
        after={
            "status": request.status.value,
            "compensated": compensated,
            "error_code": error_code,
        },
        result="failed",
    )
    await _commit_refresh(session, request)
    _log_phase(
        "approval_failed_compensated" if compensated else "approval_failed_recovery_required",
        guild_id=guild_id,
        request_id=request.id,
        correlation_id=correlation_id,
        level=logging.WARNING,
    )
    return request


async def reject_request(
    session: AsyncSession,
    *,
    guild_id: str,
    request_id: str,
    actor_id: str,
    correlation_id: str,
    reason: str,
) -> RegistrationRequest:
    clean_reason = reason.strip()
    if not 1 <= len(clean_reason) <= 1000:
        raise _http(422, "registration.invalid_reason", "Informe um motivo de 1 a 1000 caracteres.")
    request = await _owned_request(
        session, guild_id=guild_id, request_id=request_id, lock=True
    )
    if request.status != RegistrationRequestStatus.pending:
        raise _http(
            409,
            "registration.already_processing",
            "Solicitacao ja processada ou em processamento.",
        )
    _, version, config = await _published_configuration(session, guild_id)
    ensure_request_transition(request.status, RegistrationRequestStatus.rejected)
    now = datetime.now(timezone.utc)
    request.status = RegistrationRequestStatus.rejected
    request.reviewed_by = actor_id
    request.rejection_reason = clean_reason
    request.reviewed_at = now
    request.rejected_at = now
    request.config_version_reviewed_id = version.id
    request.revision += 1
    await _audit(
        session,
        guild_id=guild_id,
        actor_id=actor_id,
        action="registration.request_rejected",
        request_id=request.id,
        correlation_id=correlation_id,
        before={"status": RegistrationRequestStatus.pending.value},
        after={"status": request.status.value},
        config_version=version.version,
    )
    await _decision_deliveries(
        session,
        request=request,
        config=config,
        event="rejected",
        correlation_id=correlation_id,
        dm_message=f"{config.rejected_message}\nMotivo: {clean_reason}",
    )
    await _commit_refresh(session, request)
    _log_phase(
        "rejected",
        guild_id=guild_id,
        request_id=request.id,
        correlation_id=correlation_id,
    )
    return request


async def attach_review_message(
    session: AsyncSession,
    *,
    guild_id: str,
    request_id: str,
    actor_id: str,
    correlation_id: str,
    channel_id: str,
    message_id: str,
) -> RegistrationRequest:
    request = await _owned_request(
        session, guild_id=guild_id, request_id=request_id, lock=True
    )
    request.review_channel_id = channel_id
    request.review_message_id = message_id
    request.revision += 1
    await _audit(
        session,
        guild_id=guild_id,
        actor_id=actor_id,
        action="registration.review_message_attached",
        request_id=request.id,
        correlation_id=correlation_id,
        after={"channel_id": channel_id, "message_id": message_id},
    )
    await _commit_refresh(session, request)
    return request


async def list_members(
    session: AsyncSession,
    *,
    guild_id: str,
    status: OrganizationMemberStatus | None = None,
    limit: int = 100,
) -> list[OrganizationMember]:
    query = select(OrganizationMember).where(OrganizationMember.guild_id == guild_id)
    if status is not None:
        query = query.where(OrganizationMember.status == status)
    return list(
        (
            await session.execute(
                query.order_by(OrganizationMember.updated_at.desc()).limit(limit)
            )
        ).scalars()
    )


async def deactivate_member(
    session: AsyncSession,
    *,
    guild_id: str,
    discord_user_id: str,
    actor_id: str | None,
    correlation_id: str,
) -> OrganizationMember | None:
    member = (
        await session.execute(
            select(OrganizationMember)
            .where(
                OrganizationMember.guild_id == guild_id,
                OrganizationMember.discord_user_id == discord_user_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if member is None:
        return None
    if member.status == OrganizationMemberStatus.inactive:
        await _commit_refresh(session, member)
        return member
    member.status = OrganizationMemberStatus.inactive
    member.deactivated_at = datetime.now(timezone.utc)
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="registration",
        actor_type="user" if actor_id else "system",
        actor_id=actor_id,
        action="registration.member_deactivated",
        resource_type="organization_member",
        resource_id=member.id,
        correlation_id=correlation_id,
        before={"status": OrganizationMemberStatus.active.value},
        after={"status": OrganizationMemberStatus.inactive.value},
    )
    await _commit_refresh(session, member)
    return member


async def stale_processing(
    session: AsyncSession, *, guild_id: str, now: datetime | None = None, limit: int = 100
) -> list[RegistrationRequest]:
    current = now or datetime.now(timezone.utc)
    return list(
        (
            await session.execute(
                select(RegistrationRequest)
                .where(
                    RegistrationRequest.guild_id == guild_id,
                    RegistrationRequest.status == RegistrationRequestStatus.processing,
                    RegistrationRequest.processing_lease_until <= current,
                )
                .order_by(RegistrationRequest.processing_lease_until)
                .limit(limit)
            )
        ).scalars()
    )


async def legacy_inventory(session: AsyncSession, *, guild_id: str) -> dict[str, Any]:
    from app.models import GuildConfig, SystemRecord

    config = await session.scalar(select(GuildConfig).where(GuildConfig.guild_id == guild_id))
    records = int(
        await session.scalar(
            select(func.count(SystemRecord.id)).where(
                SystemRecord.guild_id == guild_id, SystemRecord.module == "set"
            )
        )
        or 0
    )
    modules = dict(config.modules or {}) if config else {}
    permissions = dict(config.command_permissions or {}) if config else {}
    settings_text = str(config.settings or {}).casefold() if config else ""
    warnings = []
    if records or "set" in modules or "set" in settings_text or any(
        key.startswith("set.") for key in permissions
    ):
        warnings.append(
            "Dados legados de set foram encontrados e serao preservados sem backfill automatico."
        )
    return {
        "guild_id": guild_id,
        "legacy_module": "set",
        "system_records": records,
        "catalog_enabled": modules.get("set") is True,
        "settings_reference": "set" in settings_text,
        "permission_keys": sum(1 for key in permissions if key.startswith("set.")),
        "backfill": False,
        "warnings": warnings,
    }
