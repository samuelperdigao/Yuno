from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import ActorHeader, CorrelationHeader, require_active_license, require_platform_admin
from app.core.security import require_bot_token
from app.db import get_session
from app.domain_modules.tags import services
from app.domain_modules.tags.domain import MemberDiscordSnapshot, TagSyncRunMode
from app.domain_modules.tags.schemas import (
    TagBindingDeleteIn,
    TagBindingUpsertIn,
    TagMemberCancelIn,
    TagMemberDiagnosticsIn,
    TagMemberSyncRequestIn,
    TagPeriodicEnsureIn,
    TagPreviewIn,
    TagRunJobIn,
    TagSyncCompleteIn,
    TagSyncFailIn,
    TagSyncPrepareIn,
    TagSyncRunCancelIn,
    TagSyncRunCreateIn,
)
from app.platform.permissions import authorize


router = APIRouter(dependencies=[Depends(require_bot_token)])


def _snapshot(data) -> MemberDiscordSnapshot:
    return MemberDiscordSnapshot(
        guild_id=data.guild_id,
        discord_user_id=data.discord_user_id,
        member_found=data.member_found,
        role_ids=tuple(data.role_ids),
        hierarchy_role_ids=tuple(data.hierarchy_role_ids),
        current_nickname=data.current_nickname,
        is_bot=data.is_bot,
        is_owner=data.is_owner,
        manage_nicknames=data.manage_nicknames,
        bot_top_role_id=data.bot_top_role_id,
        target_top_role_id=data.target_top_role_id,
    )


async def _admin(
    session: AsyncSession,
    *,
    guild_id: str,
    actor_header: str,
    actor,
    correlation_header: str | None,
) -> str:
    return await require_platform_admin(
        session,
        guild_id=guild_id,
        actor_header=actor_header,
        actor=actor,
        correlation_header=correlation_header,
    )


async def _permit(
    session: AsyncSession,
    *,
    guild_id: str,
    actor_header: str,
    actor,
    correlation_header: str | None,
    capability: str,
) -> str:
    if actor.guild_id != guild_id:
        raise HTTPException(status_code=403, detail="ActorContext pertence a outra guild.")
    if actor.user_id != actor_header:
        raise HTTPException(status_code=403, detail="Ator autenticado divergente.")
    if correlation_header and correlation_header != actor.correlation_id:
        raise HTTPException(status_code=400, detail="Correlation ID divergente.")
    decision = await authorize(
        session,
        guild_id=guild_id,
        module_key="tags",
        capability_key=capability,
        actor=actor,
    )
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)
    return actor.correlation_id


@router.get("/guilds/{guild_id}/modules/tags/bindings/draft")
async def read_draft_bindings(
    guild_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    draft, items = await services.list_draft_bindings(session, guild_id=guild_id)
    await session.commit()
    return {
        "revision": draft.revision,
        "base_published_version": draft.base_published_version,
        "bindings": [services.binding_dict(item) for item in items],
    }


@router.put("/guilds/{guild_id}/modules/tags/bindings/draft")
async def write_draft_binding(
    guild_id: str,
    data: TagBindingUpsertIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _admin(
        session, guild_id=guild_id, actor_header=x_yuno_actor_id,
        actor=data.actor, correlation_header=x_yuno_correlation_id
    )
    if len(data.guild_role_ids) != len(set(data.guild_role_ids)):
        raise HTTPException(status_code=422, detail="Snapshot de cargos possui IDs duplicados.")
    if data.discord_role_id not in data.guild_role_ids:
        raise HTTPException(status_code=422, detail="Cargo nao existe no snapshot atual desta guild.")
    draft, item = await services.upsert_draft_binding(
        session,
        guild_id=guild_id,
        discord_role_id=data.discord_role_id,
        tag=data.tag,
        enabled=data.enabled,
        actor_id=x_yuno_actor_id,
        expected_revision=data.expected_revision,
        expected_published_version=data.expected_published_version,
        correlation_id=correlation,
    )
    return {"revision": draft.revision, "base_published_version": draft.base_published_version, "binding": services.binding_dict(item)}


@router.delete("/guilds/{guild_id}/modules/tags/bindings/draft/{discord_role_id}")
async def remove_draft_binding(
    guild_id: str,
    discord_role_id: str,
    data: TagBindingDeleteIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _admin(
        session, guild_id=guild_id, actor_header=x_yuno_actor_id,
        actor=data.actor, correlation_header=x_yuno_correlation_id
    )
    draft = await services.delete_draft_binding(
        session,
        guild_id=guild_id,
        discord_role_id=discord_role_id,
        actor_id=x_yuno_actor_id,
        expected_revision=data.expected_revision,
        expected_published_version=data.expected_published_version,
        correlation_id=correlation,
    )
    return {"revision": draft.revision, "base_published_version": draft.base_published_version}


@router.get("/guilds/{guild_id}/modules/tags/bindings/effective")
async def read_effective_bindings(
    guild_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    instance, items = await services.effective_bindings(session, guild_id=guild_id)
    return {
        "config_version_id": instance.published_config_version_id if instance else None,
        "bindings": [services.binding_dict(item) for item in items],
    }


@router.post("/guilds/{guild_id}/modules/tags/preview")
async def preview_member(
    guild_id: str,
    data: TagPreviewIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    await _admin(
        session, guild_id=guild_id, actor_header=x_yuno_actor_id,
        actor=data.actor, correlation_header=x_yuno_correlation_id
    )
    resolution, metadata = await services.preview(
        session,
        guild_id=guild_id,
        discord_user_id=data.snapshot.discord_user_id,
        snapshot=_snapshot(data.snapshot),
        source=data.source,
        base_only=data.base_only,
    )
    return {
        "status": resolution.status,
        "expected_nickname": resolution.expected_nickname,
        "winning_role_id": resolution.winning_role_id,
        "winning_tag": resolution.winning_tag,
        "blocker": resolution.blocker,
        "reason": resolution.reason,
        **metadata,
    }


@router.post("/guilds/{guild_id}/modules/tags/member-sync")
async def request_member_sync(
    guild_id: str,
    data: TagMemberSyncRequestIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session, guild_id=guild_id, actor_header=x_yuno_actor_id,
        actor=data.actor, correlation_header=x_yuno_correlation_id, capability="tags.sync"
    )
    intent = await services.request_member_sync(
        session,
        guild_id=guild_id,
        discord_user_id=data.discord_user_id,
        observed_fingerprint=data.observed_fingerprint,
        reason=data.reason,
        correlation_id=correlation,
    )
    return {"scheduled": intent is not None, "intent": services.intent_dict(intent) if intent else None}


@router.post("/guilds/{guild_id}/modules/tags/sync/prepare")
async def prepare_member_sync(
    guild_id: str,
    data: TagSyncPrepareIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    await _permit(
        session, guild_id=guild_id, actor_header=x_yuno_actor_id,
        actor=data.actor, correlation_header=x_yuno_correlation_id, capability="tags.sync"
    )
    return await services.prepare_member_sync(
        session,
        guild_id=guild_id,
        intent_id=data.intent_id,
        revision=data.revision,
        run_item_id=data.run_item_id,
        snapshot=_snapshot(data.snapshot),
    )


@router.post("/guilds/{guild_id}/modules/tags/sync/complete")
async def complete_member_sync(
    guild_id: str,
    data: TagSyncCompleteIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    await _permit(
        session, guild_id=guild_id, actor_header=x_yuno_actor_id,
        actor=data.actor, correlation_header=x_yuno_correlation_id, capability="tags.sync"
    )
    intent = await services.complete_member_sync(
        session, guild_id=guild_id, **data.model_dump(exclude={"actor"})
    )
    return services.intent_dict(intent)


@router.post("/guilds/{guild_id}/modules/tags/sync/fail")
async def fail_member_sync(
    guild_id: str,
    data: TagSyncFailIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    await _permit(
        session, guild_id=guild_id, actor_header=x_yuno_actor_id,
        actor=data.actor, correlation_header=x_yuno_correlation_id, capability="tags.sync"
    )
    intent = await services.fail_member_sync(
        session, guild_id=guild_id, **data.model_dump(exclude={"actor"})
    )
    return services.intent_dict(intent)


@router.post("/guilds/{guild_id}/modules/tags/sync-runs")
async def create_sync_run(
    guild_id: str,
    data: TagSyncRunCreateIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session, guild_id=guild_id, actor_header=x_yuno_actor_id,
        actor=data.actor, correlation_header=x_yuno_correlation_id, capability="tags.sync"
    )
    run = await services.create_sync_run(
        session,
        guild_id=guild_id,
        mode=data.mode,
        reason=data.reason,
        actor_id=x_yuno_actor_id if data.actor.actor_type == "user" else None,
        correlation_id=correlation,
    )
    return services.run_dict(run)


@router.get("/guilds/{guild_id}/modules/tags/sync-runs/{run_id}")
async def read_sync_run(
    guild_id: str, run_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    return services.run_dict(await services.get_sync_run(session, guild_id=guild_id, run_id=run_id))


@router.post("/guilds/{guild_id}/modules/tags/sync-runs/{run_id}/cancel")
async def cancel_sync_run(
    guild_id: str,
    run_id: str,
    data: TagSyncRunCancelIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    correlation = await _admin(
        session, guild_id=guild_id, actor_header=x_yuno_actor_id,
        actor=data.actor, correlation_header=x_yuno_correlation_id
    )
    run = await services.cancel_sync_run(
        session, guild_id=guild_id, run_id=run_id,
        actor_id=x_yuno_actor_id, correlation_id=correlation
    )
    return services.run_dict(run)


@router.post("/guilds/{guild_id}/modules/tags/jobs")
async def execute_run_job(
    guild_id: str,
    data: TagRunJobIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    await _permit(
        session, guild_id=guild_id, actor_header=x_yuno_actor_id,
        actor=data.actor, correlation_header=x_yuno_correlation_id, capability="tags.sync"
    )
    if data.job_key == "tags.retention":
        return await services.purge_expired_runs(session, guild_id=guild_id)
    run_id = str(data.payload.get("run_id") or "")
    if not run_id:
        raise HTTPException(status_code=422, detail="run_id obrigatorio.")
    run = (
        await services.plan_sync_run_batch(session, guild_id=guild_id, run_id=run_id)
        if data.job_key == "tags.run.plan"
        else await services.finalize_sync_run(session, guild_id=guild_id, run_id=run_id)
    )
    return services.run_dict(run)


@router.post("/guilds/{guild_id}/modules/tags/periodic/ensure")
async def ensure_periodic(
    guild_id: str,
    data: TagPeriodicEnsureIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    await _permit(
        session, guild_id=guild_id, actor_header=x_yuno_actor_id,
        actor=data.actor, correlation_header=x_yuno_correlation_id, capability="tags.sync"
    )
    run = await services.ensure_periodic_run(session, guild_id=guild_id, day_key=data.day_key)
    return {"scheduled": run is not None, "run": services.run_dict(run) if run else None}


@router.post("/guilds/{guild_id}/modules/tags/members/cancel")
async def cancel_member(
    guild_id: str,
    data: TagMemberCancelIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    await _permit(
        session, guild_id=guild_id, actor_header=x_yuno_actor_id,
        actor=data.actor, correlation_header=x_yuno_correlation_id, capability="tags.sync"
    )
    intent = await services.cancel_member_intents(
        session, guild_id=guild_id, discord_user_id=data.discord_user_id
    )
    return {"cancelled": intent is not None}


@router.get("/guilds/{guild_id}/modules/tags/members/{discord_user_id}/diagnostics")
async def member_diagnostics(
    guild_id: str, discord_user_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    return await services.member_diagnostics(
        session, guild_id=guild_id, discord_user_id=discord_user_id
    )


@router.post("/guilds/{guild_id}/modules/tags/members/{discord_user_id}/diagnostics")
async def live_member_diagnostics(
    guild_id: str,
    discord_user_id: str,
    data: TagMemberDiagnosticsIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    await _admin(
        session, guild_id=guild_id, actor_header=x_yuno_actor_id,
        actor=data.actor, correlation_header=x_yuno_correlation_id
    )
    if data.snapshot.discord_user_id != discord_user_id:
        raise HTTPException(status_code=403, detail="Snapshot pertence a outro membro.")
    current = await services.member_diagnostics(
        session, guild_id=guild_id, discord_user_id=discord_user_id
    )
    resolution, metadata = await services.preview(
        session,
        guild_id=guild_id,
        discord_user_id=discord_user_id,
        snapshot=_snapshot(data.snapshot),
        source="effective",
        base_only=False,
    )
    return {
        **current,
        "discord": {
            "role_ids": data.snapshot.role_ids,
            "current_nickname": data.snapshot.current_nickname,
            "manage_nicknames": data.snapshot.manage_nicknames,
        },
        "resolution": {
            "status": resolution.status,
            "expected_nickname": resolution.expected_nickname,
            "winning_role_id": resolution.winning_role_id,
            "winning_tag": resolution.winning_tag,
            "blocker": resolution.blocker,
        },
        **metadata,
    }


@router.get("/guilds/{guild_id}/modules/tags/operational-diagnostics")
async def module_diagnostics(
    guild_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    await require_active_license(session, guild_id)
    return await services.module_diagnostics(session, guild_id=guild_id)
