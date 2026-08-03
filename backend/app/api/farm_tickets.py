from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import require_bot_token
from app.db import get_session
from app.farm_tickets import (
    ACTIVE_TICKET_STATUSES,
    add_action,
    active_goal,
    finalize_ticket,
    get_config,
    get_ticket,
    has_pending_review,
    refresh_ticket_progress,
    reserve_ticket,
    weekly_ranking,
    upsert_config,
    upsert_goal,
)
from app.models import FarmTicket, FarmTicketAction, FarmTicketEntry
from app.schemas import (
    FarmTicketActionIn,
    FarmTicketActionLogPatch,
    FarmTicketActionOut,
    FarmTicketApproveIn,
    FarmTicketChannelPatch,
    FarmTicketConfigIn,
    FarmTicketConfigOut,
    FarmTicketEntryIn,
    FarmTicketFinalizeIn,
    FarmTicketOut,
    FarmTicketReserveIn,
    FarmTicketReserveOut,
    FarmTicketReviewIn,
    FarmRankingOut,
    FarmWeeklyGoalIn,
    FarmWeeklyGoalOut,
)
from app.services import active_license_for_guild

router = APIRouter(prefix="/internal/farm-tickets", tags=["farm-tickets"], dependencies=[Depends(require_bot_token)])


async def assert_license(session: AsyncSession, guild_id: str) -> None:
    if not await active_license_for_guild(session, guild_id):
        raise HTTPException(status_code=403, detail="Servidor sem licenca ativa.")


def config_out(config) -> FarmTicketConfigOut:
    return FarmTicketConfigOut(
        guild_id=config.guild_id,
        category_ids=config.category_ids or [],
        admin_role_ids=config.admin_role_ids or [],
        log_channel_id=config.log_channel_id,
        panel_channel_id=config.panel_channel_id,
        folders_category_id=config.folders_category_id,
        participant_role_ids=config.participant_role_ids or [],
    )


def goal_out(goal) -> FarmWeeklyGoalOut:
    return FarmWeeklyGoalOut(
        id=goal.id,
        guild_id=goal.guild_id,
        week_id=goal.week_id,
        items=goal.items or [],
        active=goal.active,
        created_by=goal.created_by,
        created_at=goal.created_at,
    )


def entry_out(entry: FarmTicketEntry) -> dict:
    return {
        "id": entry.id,
        "ticket_id": entry.ticket_id,
        "guild_id": entry.guild_id,
        "values": entry.values or {},
        "proof_channel_id": entry.proof_channel_id,
        "proof_message_id": entry.proof_message_id,
        "proof_url": entry.proof_url,
        "log_proof_url": entry.log_proof_url,
        "observacao": entry.observacao,
        "status": entry.status,
        "reviewed_by": entry.reviewed_by,
        "review_reason": entry.review_reason,
        "created_at": entry.created_at,
    }


def ticket_out(ticket: FarmTicket) -> FarmTicketOut:
    entries = ticket.__dict__.get("entries") or []
    return FarmTicketOut(
        id=ticket.id,
        guild_id=ticket.guild_id,
        week_id=ticket.week_id,
        user_id=ticket.user_id,
        member_name=ticket.member_name,
        folder_channel_id=ticket.folder_channel_id,
        folder_slot=ticket.folder_slot,
        game_id=ticket.game_id,
        folder_nickname=ticket.folder_nickname,
        channel_id=ticket.channel_id,
        panel_message_id=ticket.panel_message_id,
        status=ticket.status,
        assigned_to=ticket.assigned_to,
        goal_items=ticket.goal_items or [],
        progress=ticket.progress or {},
        created_at=ticket.created_at,
        finalized_at=ticket.finalized_at,
        finalized_by=ticket.finalized_by,
        finalization_reason=ticket.finalization_reason,
        deleted_at=ticket.deleted_at,
        entries=[entry_out(entry) for entry in entries],
    )


def action_out(action: FarmTicketAction) -> FarmTicketActionOut:
    return FarmTicketActionOut(
        id=action.id,
        ticket_id=action.ticket_id,
        guild_id=action.guild_id,
        action=action.action,
        actor_id=action.actor_id,
        event_id=action.event_id,
        payload=action.payload or {},
        created_at=action.created_at,
        log_sent_at=action.log_sent_at,
        log_message_id=action.log_message_id,
        log_attempts=action.log_attempts or 0,
    )


@router.put("/guilds/{guild_id}/config", response_model=FarmTicketConfigOut)
async def save_config(guild_id: str, data: FarmTicketConfigIn, session: AsyncSession = Depends(get_session)) -> FarmTicketConfigOut:
    await assert_license(session, guild_id)
    config = await upsert_config(session, guild_id, data)
    await session.commit()
    return config_out(config)


@router.get("/guilds/{guild_id}/config", response_model=FarmTicketConfigOut)
async def read_config(guild_id: str, session: AsyncSession = Depends(get_session)) -> FarmTicketConfigOut:
    await assert_license(session, guild_id)
    return config_out(await get_config(session, guild_id))


@router.put("/guilds/{guild_id}/goals", response_model=FarmWeeklyGoalOut)
async def save_goal(guild_id: str, data: FarmWeeklyGoalIn, session: AsyncSession = Depends(get_session)) -> FarmWeeklyGoalOut:
    await assert_license(session, guild_id)
    goal = await upsert_goal(session, guild_id, data)
    await session.commit()
    return goal_out(goal)


@router.get("/guilds/{guild_id}/goals/{week_id}", response_model=FarmWeeklyGoalOut)
async def read_goal(guild_id: str, week_id: str, session: AsyncSession = Depends(get_session)) -> FarmWeeklyGoalOut:
    await assert_license(session, guild_id)
    return goal_out(await active_goal(session, guild_id, week_id))


@router.get("/guilds/{guild_id}/ranking/{week_id}", response_model=FarmRankingOut)
async def read_ranking(
    guild_id: str,
    week_id: str,
    limit: int = 10,
    session: AsyncSession = Depends(get_session),
) -> FarmRankingOut:
    await assert_license(session, guild_id)
    safe_limit = max(1, min(limit, 25))
    result = await session.execute(
        select(FarmTicket)
        .where(
            FarmTicket.guild_id == guild_id,
            FarmTicket.week_id == week_id,
            FarmTicket.deleted_at.is_(None),
        )
        .options(selectinload(FarmTicket.entries))
    )
    tickets = list(result.scalars().unique())
    return FarmRankingOut(
        guild_id=guild_id,
        week_id=week_id,
        participants=len({ticket.user_id for ticket in tickets}),
        ranking=weekly_ranking(tickets, limit=safe_limit),
    )


@router.post("/guilds/{guild_id}/tickets/reserve", response_model=FarmTicketReserveOut)
async def reserve(guild_id: str, data: FarmTicketReserveIn, session: AsyncSession = Depends(get_session)) -> FarmTicketReserveOut:
    await assert_license(session, guild_id)
    ticket, existing = await reserve_ticket(
        session,
        guild_id=guild_id,
        week_id=data.week_id,
        user_id=data.user_id,
        member_name=data.member_name,
        open_payload=data.open_payload,
        folder_channel_id=data.folder_channel_id,
        folder_slot=data.folder_slot,
        game_id=data.game_id,
        folder_nickname=data.folder_nickname,
    )
    await session.commit()
    return FarmTicketReserveOut(ticket=ticket_out(ticket), existing=existing)


@router.patch("/tickets/{ticket_id}/channel", response_model=FarmTicketOut)
async def set_ticket_channel(ticket_id: int, data: FarmTicketChannelPatch, session: AsyncSession = Depends(get_session)) -> FarmTicketOut:
    ticket = await get_ticket(session, ticket_id)
    await assert_license(session, ticket.guild_id)
    ticket.channel_id = data.channel_id
    ticket.panel_message_id = data.panel_message_id
    ticket.status = data.status
    await add_action(session, ticket, "ticket_canal_criado", actor_id=ticket.user_id, payload={"channel_id": data.channel_id})
    await session.commit()
    return ticket_out(ticket)


@router.post("/tickets/{ticket_id}/cancel", response_model=FarmTicketOut)
async def cancel_ticket(ticket_id: int, data: FarmTicketActionIn, session: AsyncSession = Depends(get_session)) -> FarmTicketOut:
    ticket = await get_ticket(session, ticket_id)
    await assert_license(session, ticket.guild_id)
    ticket.status = "cancelado"
    ticket.deleted_at = datetime.now(timezone.utc)
    await add_action(session, ticket, "ticket_cancelado", actor_id=data.actor_id, payload=data.payload)
    await session.commit()
    return ticket_out(ticket)


@router.get("/guilds/{guild_id}/tickets/active", response_model=FarmTicketOut | None)
async def active_ticket(guild_id: str, week_id: str, user_id: str, session: AsyncSession = Depends(get_session)) -> FarmTicketOut | None:
    await assert_license(session, guild_id)
    result = await session.execute(
        select(FarmTicket)
        .where(
            FarmTicket.guild_id == guild_id,
            FarmTicket.week_id == week_id,
            FarmTicket.user_id == user_id,
            FarmTicket.status.in_(ACTIVE_TICKET_STATUSES),
            FarmTicket.deleted_at.is_(None),
        )
        .options(selectinload(FarmTicket.entries))
    )
    ticket = result.scalar_one_or_none()
    return ticket_out(ticket) if ticket else None


@router.get("/tickets/{ticket_id}", response_model=FarmTicketOut)
async def read_ticket(ticket_id: int, session: AsyncSession = Depends(get_session)) -> FarmTicketOut:
    ticket = await get_ticket(session, ticket_id)
    await assert_license(session, ticket.guild_id)
    return ticket_out(ticket)


@router.post("/tickets/{ticket_id}/entries", response_model=FarmTicketOut)
async def create_entry(ticket_id: int, data: FarmTicketEntryIn, session: AsyncSession = Depends(get_session)) -> FarmTicketOut:
    ticket = await get_ticket(session, ticket_id)
    await assert_license(session, ticket.guild_id)
    if ticket.status not in ACTIVE_TICKET_STATUSES:
        raise HTTPException(status_code=409, detail="Ticket ja finalizado.")
    entry = FarmTicketEntry(
        ticket_id=ticket.id,
        guild_id=ticket.guild_id,
        values=data.values,
        proof_channel_id=data.proof_channel_id,
        proof_message_id=data.proof_message_id,
        proof_url=data.proof_url,
        observacao=data.observacao,
    )
    session.add(entry)
    await session.flush()
    ticket.entries.append(entry)
    await refresh_ticket_progress(ticket)
    await add_action(
        session,
        ticket,
        "lancamento_registrado",
        actor_id=data.actor_id,
        payload={"entry_id": entry.id, "values": data.values, "proof_url": data.proof_url, "observacao": data.observacao},
    )
    await session.commit()
    return ticket_out(ticket)


@router.post("/tickets/{ticket_id}/assign", response_model=FarmTicketOut)
async def assign_ticket(ticket_id: int, data: FarmTicketApproveIn, session: AsyncSession = Depends(get_session)) -> FarmTicketOut:
    ticket = await get_ticket(session, ticket_id)
    await assert_license(session, ticket.guild_id)
    if not ticket.assigned_to:
        ticket.assigned_to = data.actor_id
    await add_action(session, ticket, "ticket_assumido", actor_id=data.actor_id, payload={"assigned_to": ticket.assigned_to})
    await session.commit()
    return ticket_out(ticket)


@router.post("/tickets/{ticket_id}/review", response_model=FarmTicketOut)
async def review_entry(ticket_id: int, data: FarmTicketReviewIn, session: AsyncSession = Depends(get_session)) -> FarmTicketOut:
    ticket = await get_ticket(session, ticket_id)
    await assert_license(session, ticket.guild_id)
    entry = next((item for item in ticket.entries or [] if item.id == data.entry_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail="Lancamento nao encontrado.")
    entry.status = "revisao"
    entry.reviewed_by = data.actor_id
    entry.reviewed_at = datetime.now(timezone.utc)
    entry.review_reason = data.reason
    ticket.status = "revisao"
    await refresh_ticket_progress(ticket)
    await add_action(session, ticket, "lancamento_revisao", actor_id=data.actor_id, payload={"entry_id": entry.id, "reason": data.reason})
    await session.commit()
    return ticket_out(ticket)


@router.post("/tickets/{ticket_id}/approve", response_model=FarmTicketOut)
async def approve_ticket(ticket_id: int, data: FarmTicketApproveIn, session: AsyncSession = Depends(get_session)) -> FarmTicketOut:
    ticket = await get_ticket(session, ticket_id)
    await assert_license(session, ticket.guild_id)
    await refresh_ticket_progress(ticket)
    if has_pending_review(ticket):
        raise HTTPException(status_code=409, detail="Existe revisao pendente.")
    if int((ticket.progress or {}).get("percent") or 0) < 100:
        raise HTTPException(status_code=409, detail="A meta ainda nao chegou a 100%.")
    ticket.status = "aprovado_total"
    await add_action(session, ticket, "meta_aprovada", actor_id=data.actor_id, payload={"progress": ticket.progress})
    await session.commit()
    return ticket_out(ticket)


@router.post("/tickets/{ticket_id}/finalize", response_model=FarmTicketOut)
async def finalize(ticket_id: int, data: FarmTicketFinalizeIn, session: AsyncSession = Depends(get_session)) -> FarmTicketOut:
    ticket = await get_ticket(session, ticket_id)
    await assert_license(session, ticket.guild_id)
    await finalize_ticket(ticket, actor_id=data.actor_id, reason=data.reason)
    await add_action(session, ticket, "ticket_finalizado", actor_id=data.actor_id, payload={"reason": data.reason, "status": ticket.status})
    await session.commit()
    return ticket_out(ticket)


@router.post("/tickets/{ticket_id}/delete", response_model=FarmTicketOut)
async def mark_deleted(ticket_id: int, data: FarmTicketActionIn, session: AsyncSession = Depends(get_session)) -> FarmTicketOut:
    ticket = await get_ticket(session, ticket_id)
    await assert_license(session, ticket.guild_id)
    ticket.deleted_at = datetime.now(timezone.utc)
    await add_action(session, ticket, "ticket_excluido", actor_id=data.actor_id, payload=data.payload)
    await session.commit()
    return ticket_out(ticket)


@router.get("/actions/pending-logs", response_model=list[FarmTicketActionOut])
async def pending_logs(limit: int = 50, session: AsyncSession = Depends(get_session)) -> list[FarmTicketActionOut]:
    result = await session.execute(
        select(FarmTicketAction)
        .where(FarmTicketAction.log_sent_at.is_(None), FarmTicketAction.log_attempts < 10)
        .order_by(FarmTicketAction.created_at.asc())
        .limit(limit)
    )
    return [action_out(action) for action in result.scalars()]


@router.post("/actions/{action_id}/log-sent", response_model=FarmTicketActionOut)
async def mark_log_sent(action_id: int, data: FarmTicketActionLogPatch, session: AsyncSession = Depends(get_session)) -> FarmTicketActionOut:
    action = await session.get(FarmTicketAction, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Acao nao encontrada.")
    await assert_license(session, action.guild_id)
    action.log_sent_at = datetime.now(timezone.utc)
    action.log_message_id = data.log_message_id
    await session.commit()
    return action_out(action)


@router.post("/actions/{action_id}/log-failed", response_model=FarmTicketActionOut)
async def mark_log_failed(action_id: int, session: AsyncSession = Depends(get_session)) -> FarmTicketActionOut:
    action = await session.get(FarmTicketAction, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Acao nao encontrada.")
    await assert_license(session, action.guild_id)
    action.log_attempts = (action.log_attempts or 0) + 1
    await session.commit()
    return action_out(action)


@router.get("/maintenance/stale-tickets", response_model=list[FarmTicketOut])
async def stale_tickets(current_week_id: str, session: AsyncSession = Depends(get_session)) -> list[FarmTicketOut]:
    result = await session.execute(
        select(FarmTicket)
        .where(FarmTicket.week_id < current_week_id, FarmTicket.status.in_(ACTIVE_TICKET_STATUSES), FarmTicket.deleted_at.is_(None))
        .options(selectinload(FarmTicket.entries))
    )
    return [ticket_out(ticket) for ticket in result.scalars()]


@router.get("/maintenance/deletable-tickets", response_model=list[FarmTicketOut])
async def deletable_tickets(current_week_id: str, session: AsyncSession = Depends(get_session)) -> list[FarmTicketOut]:
    result = await session.execute(
        select(FarmTicket)
        .where(FarmTicket.week_id < current_week_id, FarmTicket.status.notin_(ACTIVE_TICKET_STATUSES), FarmTicket.deleted_at.is_(None))
        .options(selectinload(FarmTicket.entries), selectinload(FarmTicket.actions))
    )
    tickets = []
    for ticket in result.scalars():
        if all(action.log_sent_at is not None for action in ticket.actions or []):
            tickets.append(ticket_out(ticket))
    return tickets
