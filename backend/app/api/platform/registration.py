from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import ActorHeader, CorrelationHeader, require_active_license
from app.core.security import require_bot_token
from app.db import get_session
from app.domain_modules.registration import services
from app.domain_modules.registration.domain import (
    OrganizationMemberStatus,
    RegistrationRequestStatus,
    render_nickname,
)
from app.domain_modules.registration.schemas import (
    ApprovalClaimCommand,
    ApprovalCompleteCommand,
    ApprovalPreflightCommand,
    ApprovalReleaseCommand,
    ApprovalStepCommand,
    MemberDeactivateCommand,
    RegistrationRejectCommand,
    RegistrationSubmitCommand,
    ReviewMessageCommand,
)
from app.platform.permissions import authorize
from app.platform.models import ModuleConfigVersion
from app.platform.schemas import ActorContextIn, AdministrativeActionIn


router = APIRouter(dependencies=[Depends(require_bot_token)])


async def _permit(
    session: AsyncSession,
    *,
    guild_id: str,
    capability: str,
    actor: ActorContextIn,
    actor_header: str,
    correlation_header: str | None,
    resource_id: str = "",
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
        module_key="registration",
        capability_key=capability,
        actor=actor,
        resource_id=resource_id,
    )
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)
    return actor.correlation_id


def _request(item, *, include_token: bool = False) -> dict[str, Any]:
    result = {
        "id": item.id,
        "guild_id": item.guild_id,
        "discord_user_id": item.discord_user_id,
        "submitted_name": item.submitted_name,
        "player_id_original": item.player_id_original,
        "player_id_normalized": item.player_id_normalized,
        "status": item.status,
        "config_version_submitted_id": item.config_version_submitted_id,
        "config_version_reviewed_id": item.config_version_reviewed_id,
        "review_channel_id": item.review_channel_id,
        "review_message_id": item.review_message_id,
        "reviewed_by": item.reviewed_by,
        "rejection_reason": item.rejection_reason,
        "last_error_code": item.last_error_code,
        "revision": item.revision,
        "processing_actor_id": item.processing_actor_id,
        "processing_started_at": item.processing_started_at,
        "processing_lease_until": item.processing_lease_until,
        "previous_nickname": item.previous_nickname,
        "target_nickname": item.target_nickname,
        "role_was_present": item.role_was_present,
        "nickname_applied": item.nickname_applied,
        "role_applied": item.role_applied,
        "compensation_state": item.compensation_state,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "reviewed_at": item.reviewed_at,
        "approved_at": item.approved_at,
        "rejected_at": item.rejected_at,
    }
    if include_token:
        result["operation_token"] = item.processing_token
    return result


def _member(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "guild_id": item.guild_id,
        "discord_user_id": item.discord_user_id,
        "player_id_original": item.player_id_original,
        "player_id_normalized": item.player_id_normalized,
        "name": item.name,
        "status": item.status,
        "approved_request_id": item.approved_request_id,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "activated_at": item.activated_at,
        "deactivated_at": item.deactivated_at,
    }


@router.get("/guilds/{guild_id}/modules/registration/config")
async def effective_config(
    guild_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    version, config = await services.effective_configuration(
        session, guild_id=guild_id, require_active=False
    )
    return {"version_id": version.id, "version": version.version, "data": config.model_dump(mode="json")}


@router.post("/guilds/{guild_id}/modules/registration/requests")
async def submit_request(
    guild_id: str,
    data: RegistrationSubmitCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="registration.submit",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return _request(
        await services.submit_request(
            session,
            guild_id=guild_id,
            actor_id=x_yuno_actor_id,
            correlation_id=correlation,
            data=data.registration,
            panel_config_version=data.panel_config_version,
        )
    )


@router.get("/guilds/{guild_id}/modules/registration/requests/{request_id}")
async def get_request(
    guild_id: str, request_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    return _request(
        await services.get_request(session, guild_id=guild_id, request_id=request_id)
    )


@router.get("/guilds/{guild_id}/modules/registration/requests")
async def list_requests(
    guild_id: str,
    status: RegistrationRequestStatus | None = None,
    discord_user_id: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    await require_active_license(session, guild_id)
    return [
        _request(item)
        for item in await services.list_requests(
            session,
            guild_id=guild_id,
            status=status,
            discord_user_id=discord_user_id,
            limit=limit,
        )
    ]


@router.post("/guilds/{guild_id}/modules/registration/requests/{request_id}/approval/claim")
async def claim_approval(
    guild_id: str,
    request_id: str,
    data: ApprovalClaimCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="registration.review",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
        resource_id=request_id,
    )
    item, config = await services.claim_approval(
        session,
        guild_id=guild_id,
        request_id=request_id,
        actor_id=x_yuno_actor_id,
        correlation_id=correlation,
        operation_token=data.operation_token,
    )
    return {
        **_request(item, include_token=True),
        "config": config.model_dump(mode="json"),
        "target_nickname": render_nickname(
            config.nickname_template,
            name=item.submitted_name,
            player_id=item.player_id_original,
        ),
    }


@router.post("/guilds/{guild_id}/modules/registration/requests/{request_id}/approval/preflight")
async def approval_preflight(
    guild_id: str,
    request_id: str,
    data: ApprovalPreflightCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="registration.review",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
        resource_id=request_id,
    )
    return _request(
        await services.record_preflight(
            session,
            guild_id=guild_id,
            request_id=request_id,
            actor_id=x_yuno_actor_id,
            operation_token=data.operation_token,
            previous_nickname=data.previous_nickname,
            role_was_present=data.role_was_present,
            target_nickname=data.target_nickname,
            correlation_id=correlation,
        )
    )


@router.post("/guilds/{guild_id}/modules/registration/requests/{request_id}/approval/step")
async def approval_step(
    guild_id: str,
    request_id: str,
    data: ApprovalStepCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="registration.review",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
        resource_id=request_id,
    )
    return _request(
        await services.record_discord_step(
            session,
            guild_id=guild_id,
            request_id=request_id,
            actor_id=x_yuno_actor_id,
            operation_token=data.operation_token,
            step=data.step,
            correlation_id=correlation,
        )
    )


@router.post("/guilds/{guild_id}/modules/registration/requests/{request_id}/approval/complete")
async def approval_complete(
    guild_id: str,
    request_id: str,
    data: ApprovalCompleteCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    capability = "registration.recover" if data.actor.actor_type == "system" else "registration.review"
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability=capability,
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
        resource_id=request_id,
    )
    item, member = await services.complete_approval(
        session,
        guild_id=guild_id,
        request_id=request_id,
        actor_id=x_yuno_actor_id,
        correlation_id=correlation,
        operation_token=data.operation_token,
        recovery=data.actor.actor_type == "system",
    )
    return {"request": _request(item), "member": _member(member)}


@router.post("/guilds/{guild_id}/modules/registration/requests/{request_id}/approval/release")
async def approval_release(
    guild_id: str,
    request_id: str,
    data: ApprovalReleaseCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    capability = "registration.recover" if data.actor.actor_type == "system" else "registration.review"
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability=capability,
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
        resource_id=request_id,
    )
    return _request(
        await services.fail_approval(
            session,
            guild_id=guild_id,
            request_id=request_id,
            actor_id=x_yuno_actor_id,
            correlation_id=correlation,
            operation_token=data.operation_token,
            compensated=data.compensated,
            error_code=data.error_code,
            recovery=data.actor.actor_type == "system",
        )
    )


@router.post("/guilds/{guild_id}/modules/registration/requests/{request_id}/reject")
async def reject_request(
    guild_id: str,
    request_id: str,
    data: RegistrationRejectCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="registration.review",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
        resource_id=request_id,
    )
    return _request(
        await services.reject_request(
            session,
            guild_id=guild_id,
            request_id=request_id,
            actor_id=x_yuno_actor_id,
            correlation_id=correlation,
            reason=data.reason,
        )
    )


@router.patch("/guilds/{guild_id}/modules/registration/requests/{request_id}/review-message")
async def attach_review_message(
    guild_id: str,
    request_id: str,
    data: ReviewMessageCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="registration.recover",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
        resource_id=request_id,
    )
    return _request(
        await services.attach_review_message(
            session,
            guild_id=guild_id,
            request_id=request_id,
            actor_id=x_yuno_actor_id,
            correlation_id=correlation,
            channel_id=data.channel_id,
            message_id=data.message_id,
        )
    )


@router.get("/guilds/{guild_id}/modules/registration/members")
async def list_members(
    guild_id: str,
    status: OrganizationMemberStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    await require_active_license(session, guild_id)
    return [
        _member(item)
        for item in await services.list_members(
            session, guild_id=guild_id, status=status, limit=limit
        )
    ]


@router.post("/guilds/{guild_id}/modules/registration/members/{discord_user_id}/deactivate")
async def deactivate_member(
    guild_id: str,
    discord_user_id: str,
    data: MemberDeactivateCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any] | None:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="registration.deactivate",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
        resource_id=discord_user_id,
    )
    item = await services.deactivate_member(
        session,
        guild_id=guild_id,
        discord_user_id=discord_user_id,
        actor_id=data.actor.user_id,
        correlation_id=correlation,
    )
    return _member(item) if item else None


@router.get("/guilds/{guild_id}/modules/registration/recovery/stale")
async def stale_processing(
    guild_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    await require_active_license(session, guild_id)
    result: list[dict[str, Any]] = []
    for item in await services.stale_processing(session, guild_id=guild_id, limit=limit):
        version = await session.get(ModuleConfigVersion, item.config_version_reviewed_id)
        reviewed_config = (
            dict(version.data or {})
            if version is not None
            and version.guild_id == guild_id
            and version.module_key == "registration"
            else None
        )
        result.append(
            {**_request(item, include_token=True), "reviewed_config": reviewed_config}
        )
    return result


@router.post("/guilds/{guild_id}/modules/registration/inventory")
async def inventory(
    guild_id: str,
    data: AdministrativeActionIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    await _permit(
        session,
        guild_id=guild_id,
        capability="registration.configure",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await services.legacy_inventory(session, guild_id=guild_id)
