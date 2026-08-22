from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import ActorHeader, CorrelationHeader, require_active_license
from app.core.security import require_bot_token
from app.db import get_session
from app.domain_modules.meta import contracts, services
from app.domain_modules.meta.schemas import (
    MetaActivateCycleCommand,
    MetaCycleTransitionCommand,
    MetaDraftOpenCommand,
    MetaDraftPatchCommand,
    MetaDraftSubmitCommand,
    MetaMemberRemoveCommand,
    MetaPrepareLaunchCommand,
    MetaRecoveryCommand,
    MetaSettingsCommand,
)
from app.platform.permissions import authorize
from app.platform.schemas import ActorContextIn


router = APIRouter(dependencies=[Depends(require_bot_token)])


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _event_out(item: contracts.GoalEvent) -> dict[str, Any]:
    return {
        "event_id": item.event_id,
        "sequence": item.sequence,
        "event_type": item.event_type,
        "event_version": item.event_version,
        "occurred_at": item.occurred_at,
        "causation_id": item.causation_id,
        "deduplication_key": item.deduplication_key,
        "payload": _plain(item.payload),
    }


async def _permit(
    session: AsyncSession,
    *,
    guild_id: str,
    capability: str,
    actor: ActorContextIn,
    actor_header: str,
    correlation_header: str | None,
) -> str:
    if actor.guild_id != guild_id or actor.actor_type != "user" or actor.user_id != actor_header:
        raise HTTPException(status_code=403, detail="Ator autenticado divergente.")
    if correlation_header and correlation_header != actor.correlation_id:
        raise HTTPException(status_code=400, detail="Correlation ID divergente.")
    decision = await authorize(
        session,
        guild_id=guild_id,
        module_key="meta",
        capability_key=capability,
        actor=actor,
        resource_id="",
    )
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)
    return actor.correlation_id


@router.get("/guilds/{guild_id}/modules/meta/settings")
async def settings(guild_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    return await services.get_settings(session, guild_id=guild_id)


@router.put("/guilds/{guild_id}/modules/meta/settings")
async def save_settings(
    guild_id: str,
    data: MetaSettingsCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="meta.configure",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await services.save_settings(
        session,
        guild_id=guild_id,
        notice_channel_id=data.notice_channel_id,
        expected_revision=data.expected_revision,
        actor_id=x_yuno_actor_id,
        correlation_id=correlation,
    )


@router.get("/guilds/{guild_id}/modules/meta/goals")
async def goals(
    guild_id: str,
    page: int = Query(default=0, ge=0),
    page_size: int = Query(default=23, ge=1, le=23),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    return await services.list_goals(session, guild_id=guild_id, page=page, page_size=page_size)


@router.get("/guilds/{guild_id}/modules/meta/goals/{goal_id}")
async def goal(guild_id: str, goal_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    return await services.get_goal_detail(session, guild_id=guild_id, goal_id=goal_id)


@router.get("/guilds/{guild_id}/modules/meta/draft")
async def draft(
    guild_id: str,
    x_yuno_actor_id: ActorHeader,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    return await services.get_draft(session, guild_id=guild_id, admin_id=x_yuno_actor_id)


@router.post("/guilds/{guild_id}/modules/meta/draft/open")
async def open_draft(
    guild_id: str,
    data: MetaDraftOpenCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    await _permit(
        session,
        guild_id=guild_id,
        capability="meta.manage_goals",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await services.open_draft(
        session, guild_id=guild_id, admin_id=x_yuno_actor_id, goal_id=data.goal_id
    )


@router.patch("/guilds/{guild_id}/modules/meta/draft")
async def patch_draft(
    guild_id: str,
    data: MetaDraftPatchCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    await _permit(
        session,
        guild_id=guild_id,
        capability="meta.manage_goals",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await services.patch_draft(
        session,
        guild_id=guild_id,
        admin_id=x_yuno_actor_id,
        expected_revision=data.expected_revision,
        step=data.step,
        patch=data.patch,
    )


@router.post("/guilds/{guild_id}/modules/meta/draft/submit")
async def submit_draft(
    guild_id: str,
    data: MetaDraftSubmitCommand,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    correlation = await _permit(
        session,
        guild_id=guild_id,
        capability="meta.manage_goals",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await services.submit_draft(
        session,
        guild_id=guild_id,
        admin_id=x_yuno_actor_id,
        expected_revision=data.expected_revision,
        correlation_id=correlation,
    )


@router.post("/guilds/{guild_id}/modules/meta/goals/{goal_id}/prepare-launch")
async def prepare_launch(
    guild_id: str,
    goal_id: int,
    data: MetaPrepareLaunchCommand,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    return await services.prepare_launch(
        session,
        guild_id=guild_id,
        goal_id=goal_id,
        members=data.members,
        notice_channel_id=data.notice_channel_id,
        causation_id=data.causation_id,
    )


@router.post("/guilds/{guild_id}/modules/meta/cycles/{cycle_id}/activate")
async def activate_cycle(
    guild_id: str,
    cycle_id: int,
    data: MetaActivateCycleCommand,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    if data.cycle_id != cycle_id:
        raise HTTPException(status_code=422, detail="Ciclo divergente.")
    return await services.activate_cycle(
        session,
        guild_id=guild_id,
        cycle_id=cycle_id,
        members=data.members,
        notice_channel_id=data.notice_channel_id,
        notice_message_id=data.notice_message_id,
        causation_id=data.causation_id,
    )


@router.patch("/guilds/{guild_id}/modules/meta/cycles/{cycle_id}/notice")
async def record_notice(
    guild_id: str,
    cycle_id: int,
    data: dict,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    channel_id = str(data.get("notice_channel_id") or "")
    message_id = str(data.get("notice_message_id") or "")
    if not channel_id or not message_id:
        raise HTTPException(status_code=422, detail="Referencia do aviso obrigatoria.")
    return await services.record_pending_notice(
        session,
        guild_id=guild_id,
        cycle_id=cycle_id,
        notice_channel_id=channel_id,
        notice_message_id=message_id,
    )


@router.post("/guilds/{guild_id}/modules/meta/cycles/{cycle_id}/transition")
async def transition_cycle(
    guild_id: str,
    cycle_id: int,
    data: MetaCycleTransitionCommand,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    if data.cycle_id != cycle_id:
        raise HTTPException(status_code=422, detail="Ciclo divergente.")
    return await services.close_cycle(
        session, guild_id=guild_id, cycle_id=cycle_id, causation_id=data.causation_id
    )


@router.post("/guilds/{guild_id}/modules/meta/members/remove")
async def remove_member(
    guild_id: str,
    data: MetaMemberRemoveCommand,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    return await services.remove_member(
        session,
        guild_id=guild_id,
        member_id=data.member_id,
        causation_id=data.causation_id,
    )


@router.post("/guilds/{guild_id}/modules/meta/recovery")
async def recovery(
    guild_id: str,
    data: MetaRecoveryCommand,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    return await services.reconcile(
        session, guild_id=guild_id, causation_id=data.causation_id
    )


@router.get("/guilds/{guild_id}/modules/meta/events")
async def events(
    guild_id: str,
    after_sequence: int = Query(default=0, ge=0),
    event_type: list[str] = Query(default=[]),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    page = await contracts.read_goal_events(
        session,
        guild_id=guild_id,
        after_sequence=after_sequence,
        event_types=tuple(event_type),
        limit=limit,
    )
    return {
        "events": [_event_out(item) for item in page.events],
        "next_sequence": page.next_sequence,
        "has_more": page.has_more,
    }
