from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import FarmTicket, FarmTicketAction, FarmTicketConfig, FarmTicketEntry, FarmWeeklyGoal
from app.schemas import FarmTicketConfigIn, FarmWeeklyGoalIn
from app.services import get_or_create_config


ACTIVE_TICKET_STATUSES = {"reservado", "aberto", "revisao"}
FINAL_TICKET_STATUSES = {"aprovado_total", "aprovado_parcial", "sem_entrega", "finalizado"}


def progress_from_entries(goal_items: list[dict], entries: list[FarmTicketEntry]) -> dict:
    items: dict[str, dict] = {}
    for item in goal_items:
        name = str(item.get("name") or item.get("produto") or "").strip()
        if not name:
            continue
        required = int(item.get("quantity") or item.get("quantidade") or 0)
        items[name] = {"required": required, "delivered": 0, "percent": 0}

    for entry in entries:
        if entry.status == "revisao":
            continue
        for name, value in (entry.values or {}).items():
            if name in items:
                items[name]["delivered"] += int(value or 0)

    percents: list[int] = []
    for data in items.values():
        required = data["required"]
        delivered = data["delivered"]
        data["percent"] = int((delivered / required) * 100) if required > 0 else 0
        percents.append(min(data["percent"], 100))
    total_percent = int(sum(percents) / len(percents)) if percents else 0
    return {"items": items, "percent": total_percent}


async def get_ticket(session: AsyncSession, ticket_id: int) -> FarmTicket:
    result = await session.execute(
        select(FarmTicket)
        .where(FarmTicket.id == ticket_id)
        .options(selectinload(FarmTicket.entries), selectinload(FarmTicket.actions))
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket de farm nao encontrado.")
    return ticket


async def get_config(session: AsyncSession, guild_id: str) -> FarmTicketConfig:
    result = await session.execute(select(FarmTicketConfig).where(FarmTicketConfig.guild_id == guild_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Sistema de tickets de farm nao configurado.")
    return config


async def upsert_config(session: AsyncSession, guild_id: str, data: FarmTicketConfigIn) -> FarmTicketConfig:
    result = await session.execute(select(FarmTicketConfig).where(FarmTicketConfig.guild_id == guild_id))
    config = result.scalar_one_or_none()
    if not config:
        config = FarmTicketConfig(guild_id=guild_id, log_channel_id=data.log_channel_id, panel_channel_id=data.panel_channel_id)
        session.add(config)
    config.category_ids = data.category_ids
    config.admin_role_ids = data.admin_role_ids
    config.log_channel_id = data.log_channel_id
    config.panel_channel_id = data.panel_channel_id
    config.folders_category_id = data.folders_category_id
    config.participant_role_ids = data.participant_role_ids

    guild_config = await get_or_create_config(session, guild_id)
    settings = dict(guild_config.settings or {})
    settings["farm_tickets"] = {
        "category_ids": data.category_ids,
        "admin_role_ids": data.admin_role_ids,
        "log_channel_id": data.log_channel_id,
        "panel_channel_id": data.panel_channel_id,
        "folders_category_id": data.folders_category_id,
        "participant_role_ids": data.participant_role_ids,
    }
    guild_config.settings = settings
    return config


async def upsert_goal(session: AsyncSession, guild_id: str, data: FarmWeeklyGoalIn) -> FarmWeeklyGoal:
    result = await session.execute(select(FarmWeeklyGoal).where(FarmWeeklyGoal.guild_id == guild_id, FarmWeeklyGoal.week_id == data.week_id))
    goal = result.scalar_one_or_none()
    if not goal:
        goal = FarmWeeklyGoal(guild_id=guild_id, week_id=data.week_id, created_by=data.created_by)
        session.add(goal)
    goal.items = data.items
    goal.active = True
    goal.created_by = data.created_by or goal.created_by
    return goal


async def active_goal(session: AsyncSession, guild_id: str, week_id: str) -> FarmWeeklyGoal:
    result = await session.execute(
        select(FarmWeeklyGoal).where(FarmWeeklyGoal.guild_id == guild_id, FarmWeeklyGoal.week_id == week_id, FarmWeeklyGoal.active.is_(True))
    )
    goal = result.scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="Nao existe meta ativa para esta semana.")
    return goal


async def reserve_ticket(session: AsyncSession, *, guild_id: str, week_id: str, user_id: str, member_name: str) -> tuple[FarmTicket, bool]:
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
    existing = result.scalar_one_or_none()
    if existing:
        return existing, True

    goal = await active_goal(session, guild_id, week_id)
    ticket = FarmTicket(
        guild_id=guild_id,
        week_id=week_id,
        user_id=user_id,
        member_name=member_name,
        status="reservado",
        goal_items=goal.items,
        progress=progress_from_entries(goal.items, []),
    )
    session.add(ticket)
    await session.flush()
    await add_action(session, ticket, "ticket_aberto", actor_id=user_id, payload={"member_name": member_name, "week_id": week_id})
    return ticket, False


async def add_action(
    session: AsyncSession,
    ticket: FarmTicket | None,
    action: str,
    *,
    guild_id: str | None = None,
    actor_id: str | None = None,
    payload: dict | None = None,
) -> FarmTicketAction:
    action_record = FarmTicketAction(
        ticket_id=ticket.id if ticket else None,
        guild_id=ticket.guild_id if ticket else str(guild_id),
        action=action,
        actor_id=actor_id,
        event_id=uuid4().hex,
        payload=payload or {},
    )
    session.add(action_record)
    return action_record


async def refresh_ticket_progress(ticket: FarmTicket) -> None:
    ticket.progress = progress_from_entries(ticket.goal_items or [], ticket.entries or [])


def final_status(progress: dict) -> str:
    percent = int((progress or {}).get("percent") or 0)
    if percent >= 100:
        return "aprovado_total"
    if percent > 0:
        return "aprovado_parcial"
    return "sem_entrega"


def has_pending_review(ticket: FarmTicket) -> bool:
    return any(entry.status == "revisao" for entry in ticket.entries or [])


async def finalize_ticket(ticket: FarmTicket, *, actor_id: str | None, reason: str) -> None:
    await refresh_ticket_progress(ticket)
    ticket.status = final_status(ticket.progress)
    ticket.finalized_at = datetime.now(timezone.utc)
    ticket.finalized_by = actor_id
    ticket.finalization_reason = reason
