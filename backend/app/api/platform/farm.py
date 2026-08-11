from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import ActorHeader, CorrelationHeader, require_active_license
from app.core.security import require_bot_token
from app.db import get_session
from app.domain_modules.farm import services
from app.domain_modules.farm.schemas import (
    CycleTransitionCommand,
    CycleCreateCommand,
    ParticipantAssignCommand,
    ProductArchiveCommand,
    ProductCreateCommand,
    ReviewCreateCommand,
    RevisionCommand,
    SubmissionCreateCommand,
    TemplateCreateCommand,
    TicketOpenCommand,
)
from app.platform.permissions import authorize
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
    resource_owner_id: str | None = None,
) -> str:
    if actor.guild_id != guild_id or actor.actor_type != "user" or actor.user_id != actor_header:
        raise HTTPException(status_code=403, detail="Ator autenticado divergente.")
    if correlation_header and correlation_header != actor.correlation_id:
        raise HTTPException(status_code=400, detail="Correlation ID divergente.")
    checked = actor.model_copy(update={"resource_owner_id": resource_owner_id})
    decision = await authorize(
        session,
        guild_id=guild_id,
        module_key="farm",
        capability_key=capability,
        actor=checked,
        resource_id=resource_id,
    )
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)
    return actor.correlation_id


def _product(item) -> dict[str, Any]:
    return {"id": item.id, "guild_id": item.guild_id, "name": item.name, "description": item.description, "unit": item.unit, "precision": item.precision, "status": item.status, "revision": item.revision}


def _template(item) -> dict[str, Any]:
    return {"id": item.id, "guild_id": item.guild_id, "template_key": item.template_key, "version": item.version, "name": item.name, "description": item.description, "status": item.status, "revision": item.revision, "items": [{"id": value.id, "product_id": value.product_id, "quantity": value.quantity, "position": value.position} for value in item.items]}


def _cycle(item) -> dict[str, Any]:
    return {"id": item.id, "guild_id": item.guild_id, "template_id": item.template_id, "title": item.title, "timezone": item.timezone, "starts_at": item.starts_at, "ends_at": item.ends_at, "review_deadline_at": item.review_deadline_at, "participation_mode": item.participation_mode, "proof_required": item.proof_required, "status": item.status, "revision": item.revision, "goals": [{"id": value.id, "product_id": value.product_id, "product_name": value.product_name, "unit": value.unit, "precision": value.precision, "quantity_required": value.quantity_required, "position": value.position} for value in item.goals]}


def _ticket(item) -> dict[str, Any]:
    return {"id": item.id, "guild_id": item.guild_id, "cycle_id": item.cycle_id, "member_id": item.member_id, "member_display_name": item.member_display_name, "status": item.status, "revision": item.revision, "created_by": item.created_by, "created_at": item.created_at}


def _submission(item) -> dict[str, Any]:
    return {"id": item.id, "guild_id": item.guild_id, "ticket_id": item.ticket_id, "correction_of_submission_id": item.correction_of_submission_id, "status": item.status, "revision": item.revision, "submitted_by": item.submitted_by, "note": item.note, "created_at": item.created_at, "decided_at": item.decided_at, "items": [{"goal_id": value.goal_id, "quantity": value.quantity} for value in getattr(item, "items", [])], "proofs": [{"channel_id": value.channel_id, "message_id": value.message_id, "attachment_id": value.attachment_id, "url": value.url} for value in getattr(item, "proofs", [])]}


def _participant(item) -> dict[str, Any]:
    return {"id": item.id, "guild_id": item.guild_id, "cycle_id": item.cycle_id, "member_id": item.member_id, "member_display_name": item.member_display_name, "assigned_by": item.assigned_by, "assigned_at": item.assigned_at}


@router.get("/guilds/{guild_id}/modules/farm/products")
async def products(guild_id: str, session: AsyncSession = Depends(get_session)) -> list[dict]:
    await require_active_license(session, guild_id)
    return [_product(item) for item in await services.list_products(session, guild_id)]


@router.post("/guilds/{guild_id}/modules/farm/products")
async def create_product(guild_id: str, data: ProductCreateCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    correlation = await _permit(session, guild_id=guild_id, capability="farm.manage_catalog", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id)
    return _product(await services.create_product(session, guild_id=guild_id, actor_id=x_yuno_actor_id, correlation_id=correlation, data=data.product))


@router.post("/guilds/{guild_id}/modules/farm/products/{product_id}/archive")
async def archive_product(guild_id: str, product_id: int, data: ProductArchiveCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    correlation = await _permit(session, guild_id=guild_id, capability="farm.manage_catalog", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id, resource_id=str(product_id))
    return _product(await services.archive_product(session, guild_id=guild_id, product_id=product_id, expected_revision=data.expected_revision, actor_id=x_yuno_actor_id, correlation_id=correlation))


@router.get("/guilds/{guild_id}/modules/farm/templates")
async def templates(guild_id: str, session: AsyncSession = Depends(get_session)) -> list[dict]:
    await require_active_license(session, guild_id)
    return [_template(item) for item in await services.list_templates(session, guild_id)]


@router.post("/guilds/{guild_id}/modules/farm/templates")
async def create_template(guild_id: str, data: TemplateCreateCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    correlation = await _permit(session, guild_id=guild_id, capability="farm.manage_catalog", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id)
    return _template(await services.create_template(session, guild_id=guild_id, actor_id=x_yuno_actor_id, correlation_id=correlation, data=data.template))


@router.post("/guilds/{guild_id}/modules/farm/templates/{template_id}/versions")
async def create_template_version(guild_id: str, template_id: int, data: TemplateCreateCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    correlation = await _permit(session, guild_id=guild_id, capability="farm.manage_catalog", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id, resource_id=str(template_id))
    return _template(await services.create_template(session, guild_id=guild_id, actor_id=x_yuno_actor_id, correlation_id=correlation, data=data.template, source_template_id=template_id))


@router.post("/guilds/{guild_id}/modules/farm/templates/{template_id}/activate")
async def activate_template(guild_id: str, template_id: int, data: RevisionCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    correlation = await _permit(session, guild_id=guild_id, capability="farm.manage_catalog", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id, resource_id=str(template_id))
    return _template(await services.activate_template(session, guild_id=guild_id, template_id=template_id, expected_revision=data.expected_revision, actor_id=x_yuno_actor_id, correlation_id=correlation))


@router.post("/guilds/{guild_id}/modules/farm/templates/{template_id}/archive")
async def archive_template(guild_id: str, template_id: int, data: RevisionCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    correlation = await _permit(session, guild_id=guild_id, capability="farm.manage_catalog", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id, resource_id=str(template_id))
    return _template(await services.archive_template(session, guild_id=guild_id, template_id=template_id, expected_revision=data.expected_revision, actor_id=x_yuno_actor_id, correlation_id=correlation))


@router.get("/guilds/{guild_id}/modules/farm/cycles")
async def cycles(guild_id: str, session: AsyncSession = Depends(get_session)) -> list[dict]:
    await require_active_license(session, guild_id)
    return [_cycle(item) for item in await services.list_cycles(session, guild_id)]


@router.post("/guilds/{guild_id}/modules/farm/cycles")
async def create_cycle(guild_id: str, data: CycleCreateCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    correlation = await _permit(session, guild_id=guild_id, capability="farm.manage_cycles", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id)
    return _cycle(await services.create_cycle(session, guild_id=guild_id, actor_id=x_yuno_actor_id, correlation_id=correlation, data=data.cycle))


@router.post("/guilds/{guild_id}/modules/farm/cycles/{cycle_id}/schedule")
async def schedule_cycle(guild_id: str, cycle_id: int, data: RevisionCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    correlation = await _permit(session, guild_id=guild_id, capability="farm.manage_cycles", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id, resource_id=str(cycle_id))
    return _cycle(await services.schedule_cycle(session, guild_id=guild_id, cycle_id=cycle_id, expected_revision=data.expected_revision, actor_id=x_yuno_actor_id, correlation_id=correlation))


@router.post("/guilds/{guild_id}/modules/farm/cycles/{cycle_id}/participants")
async def assign_participant(guild_id: str, cycle_id: int, data: ParticipantAssignCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    correlation = await _permit(session, guild_id=guild_id, capability="farm.manage_cycles", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id, resource_id=str(cycle_id))
    return _participant(await services.assign_participant(session, guild_id=guild_id, cycle_id=cycle_id, member_id=data.member_id, member_display_name=data.member_display_name, actor_id=x_yuno_actor_id, correlation_id=correlation))


@router.post("/guilds/{guild_id}/modules/farm/cycles/{cycle_id}/close")
async def close_cycle(guild_id: str, cycle_id: int, data: CycleTransitionCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    correlation = await _permit(session, guild_id=guild_id, capability="farm.close_cycle", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id, resource_id=str(cycle_id))
    return _cycle(await services.begin_cycle_closing(session, guild_id=guild_id, cycle_id=cycle_id, expected_revision=data.expected_revision, actor_id=x_yuno_actor_id, correlation_id=correlation))


@router.post("/guilds/{guild_id}/modules/farm/cycles/{cycle_id}/cancel")
async def cancel_cycle(guild_id: str, cycle_id: int, data: CycleTransitionCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    correlation = await _permit(session, guild_id=guild_id, capability="farm.manage_cycles", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id, resource_id=str(cycle_id))
    return _cycle(await services.cancel_cycle(session, guild_id=guild_id, cycle_id=cycle_id, expected_revision=data.expected_revision, reason=data.reason or "", actor_id=x_yuno_actor_id, correlation_id=correlation))


@router.post("/guilds/{guild_id}/modules/farm/cycles/{cycle_id}/tickets")
async def open_ticket(guild_id: str, cycle_id: int, data: TicketOpenCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    capability = "farm.open_own_ticket" if data.member_id == x_yuno_actor_id else "farm.open_ticket_for_member"
    correlation = await _permit(session, guild_id=guild_id, capability=capability, actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id, resource_id=str(cycle_id), resource_owner_id=data.member_id)
    return _ticket(await services.open_ticket(session, guild_id=guild_id, cycle_id=cycle_id, member_id=data.member_id, member_display_name=data.member_display_name, actor_id=x_yuno_actor_id, correlation_id=correlation))


@router.get("/guilds/{guild_id}/modules/farm/tickets/{ticket_id}")
async def ticket(guild_id: str, ticket_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    item = await services.get_ticket(session, guild_id, ticket_id)
    result = _ticket(item)
    result["submissions"] = [_submission(value) for value in item.submissions]
    return result


@router.get("/guilds/{guild_id}/modules/farm/tickets")
async def tickets(guild_id: str, cycle_id: int | None = None, member_id: str | None = None, session: AsyncSession = Depends(get_session)) -> list[dict]:
    await require_active_license(session, guild_id)
    return [_ticket(item) for item in await services.list_tickets(session, guild_id=guild_id, cycle_id=cycle_id, member_id=member_id)]


@router.post("/guilds/{guild_id}/modules/farm/tickets/{ticket_id}/submissions")
async def submit(guild_id: str, ticket_id: int, data: SubmissionCreateCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    ticket_item = await services.get_ticket(session, guild_id, ticket_id)
    correlation = await _permit(session, guild_id=guild_id, capability="farm.submit_own", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id, resource_id=str(ticket_id), resource_owner_id=ticket_item.member_id)
    return _submission(await services.create_submission(session, guild_id=guild_id, ticket_id=ticket_id, actor_id=x_yuno_actor_id, correlation_id=correlation, data=data.submission))


@router.get("/guilds/{guild_id}/modules/farm/tickets/{ticket_id}/progress")
async def progress(guild_id: str, ticket_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    snapshot = await services.ticket_progress(session, guild_id=guild_id, ticket_id=ticket_id)
    return {"percent": snapshot.percent, "completed": snapshot.completed, "items": {str(key): {"required": value.required, "approved": value.approved, "percent": value.percent} for key, value in snapshot.items.items()}}


@router.post("/guilds/{guild_id}/modules/farm/submissions/{submission_id}/review")
async def review(guild_id: str, submission_id: int, data: ReviewCreateCommand, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    correlation = await _permit(session, guild_id=guild_id, capability="farm.review", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id, resource_id=str(submission_id))
    return _submission(await services.review_submission(session, guild_id=guild_id, submission_id=submission_id, actor_id=x_yuno_actor_id, correlation_id=correlation, data=data.review))


@router.get("/guilds/{guild_id}/modules/farm/review-queue")
async def review_queue(guild_id: str, cycle_id: int | None = None, session: AsyncSession = Depends(get_session)) -> list[dict]:
    await require_active_license(session, guild_id)
    result = []
    for item in await services.list_review_queue(session, guild_id=guild_id, cycle_id=cycle_id):
        serialized = _submission(item)
        serialized["member_id"] = item.ticket.member_id
        serialized["member_display_name"] = item.ticket.member_display_name
        result.append(serialized)
    return result


@router.post("/guilds/{guild_id}/modules/farm/inventory")
async def inventory(guild_id: str, data: AdministrativeActionIn, x_yuno_actor_id: ActorHeader, x_yuno_correlation_id: CorrelationHeader = None, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    await _permit(session, guild_id=guild_id, capability="farm.configure", actor=data.actor, actor_header=x_yuno_actor_id, correlation_header=x_yuno_correlation_id)
    return await services.legacy_inventory(session, guild_id=guild_id)


@router.post("/guilds/{guild_id}/modules/farm/jobs/{job_key}")
async def run_job(guild_id: str, job_key: str, payload: dict, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    return await services.process_cycle_job(session, guild_id=guild_id, cycle_id=int(payload["cycle_id"]), job_key=job_key, correlation_id=str(payload.get("correlation_id") or "farm-job"))
