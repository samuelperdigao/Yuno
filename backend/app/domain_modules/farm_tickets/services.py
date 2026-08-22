from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain_modules.farm_tickets.domain import (
    ACTIVE_OPERATION_STATUSES,
    CLAIMED_OPERATION_STATUSES,
    BindingOwnership,
    BindingState,
    EntryRevisionStatus,
    FarmTicketConflict,
    FarmTicketError,
    FarmTicketNotFound,
    FormKind,
    ObjectiveKind,
    OperationKind,
    OperationStatus,
    ProofCandidateStatus,
    ProofNoLongerEligible,
    ProofStorageState,
    ResourceKind,
    ResourceRemovalReason,
    TicketCloseReason,
    TicketStatus,
    calculate_progress,
    decimal_amount,
)
from app.domain_modules.farm_tickets.models import (
    FarmTicket,
    FarmTicketAllocation,
    FarmTicketCycle,
    FarmTicketDiscordBinding,
    FarmTicketEntry,
    FarmTicketEntryItem,
    FarmTicketEntryRevision,
    FarmTicketEvent,
    FarmTicketFormDraft,
    FarmTicketMetaCursor,
    FarmTicketMetaReceipt,
    FarmTicketObjective,
    FarmTicketPendingOperation,
    FarmTicketProof,
    FarmTicketProofCandidate,
    FarmTicketWithdrawal,
    FarmTicketWithdrawalItem,
)
from app.domain_modules.meta import contracts as meta_contracts
from app.domain_modules.registration.identity import read_base_member_identity
from app.platform.automation import schedule_task
from app.platform.models import DeliveryOutbox
from app.platform.registry import discover_domain_modules, module_registry
from app.platform.schemas import ActorContextIn

EVENT_CYCLE_STARTED = "meta.goal_cycle_started.v1"
EVENT_CYCLE_ENDED = "meta.goal_cycle_ended.v1"
EVENT_PARTICIPANT_REMOVED = "meta.participant_removed_from_cycle.v1"
EVENT_PARTICIPANT_MOVED = "meta.participant_moved_to_another_goal.v1"
META_EVENT_TYPES = (
    EVENT_CYCLE_STARTED,
    EVENT_CYCLE_ENDED,
    EVENT_PARTICIPANT_REMOVED,
    EVENT_PARTICIPANT_MOVED,
)
PROOF_WINDOW = timedelta(minutes=5)


async def _schedule_ticket_task(session: AsyncSession, **kwargs: Any) -> Any:
    # Mantem o servico utilizavel em testes e CLIs que nao importam app.main.
    if module_registry.get("farm_tickets") is None:
        discover_domain_modules()
    return await schedule_task(session, module_key="farm_tickets", **kwargs)


async def _enqueue_delivery_row(
    session: AsyncSession,
    *,
    guild_id: str,
    renderer_key: str,
    destination_type: str,
    destination_id: str,
    resource_type: str,
    resource_id: str,
    payload: dict[str, Any],
    idempotency_key: str,
    correlation_id: str,
    priority: int = 100,
) -> None:
    existing = await session.scalar(
        select(DeliveryOutbox.id).where(
            DeliveryOutbox.guild_id == guild_id,
            DeliveryOutbox.module_key == "farm_tickets",
            DeliveryOutbox.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return
    session.add(
        DeliveryOutbox(
            guild_id=guild_id,
            module_key="farm_tickets",
            renderer_key=renderer_key,
            destination_type=destination_type,
            destination_id=destination_id,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload,
            priority=priority,
            available_at=utc_now(),
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            max_attempts=10,
        )
    )


def _binding_dict(binding: FarmTicketDiscordBinding) -> dict[str, Any]:
    return {
        "id": binding.id,
        "ticket_id": binding.ticket_id,
        "guild_id": binding.guild_id,
        "kind": binding.kind.value,
        "resource_id": binding.resource_id,
        "parent_resource_id": binding.parent_resource_id,
        "ownership": binding.ownership.value,
        "state": binding.state.value,
        "desired_revision": binding.desired_revision,
        "applied_revision": binding.applied_revision,
        "deletion_intent_at": (
            _utc(binding.deletion_intent_at).isoformat()
            if binding.deletion_intent_at is not None
            else None
        ),
        "last_error": binding.last_error,
    }


async def _enqueue_pending_proof_copies(
    session: AsyncSession, *, guild_id: str, ticket_id: str, correlation_id: str
) -> int:
    thread_id = await session.scalar(
        select(FarmTicketDiscordBinding.resource_id).where(
            FarmTicketDiscordBinding.guild_id == guild_id,
            FarmTicketDiscordBinding.ticket_id == ticket_id,
            FarmTicketDiscordBinding.kind == ResourceKind.TICKET_THREAD,
            FarmTicketDiscordBinding.state == BindingState.ACTIVE,
        )
    )
    if thread_id is None:
        return 0
    proofs = list(
        (
            await session.execute(
                select(FarmTicketProof).where(
                    FarmTicketProof.guild_id == guild_id,
                    FarmTicketProof.ticket_id == ticket_id,
                    FarmTicketProof.thread_delivery_confirmed_at.is_(None),
                    FarmTicketProof.storage_state != ProofStorageState.DELETED,
                )
            )
        ).scalars()
    )
    for proof in proofs:
        await _enqueue_delivery_row(
            session,
            guild_id=guild_id,
            renderer_key="farm_tickets.proof_copy",
            destination_type="thread",
            destination_id=thread_id,
            resource_type="farm_ticket_proof",
            resource_id=proof.id,
            payload={"ticket_id": ticket_id, "proof_id": proof.id},
            idempotency_key=f"proof:{proof.id}:thread-copy",
            correlation_id=correlation_id,
            priority=50,
        )
    return len(proofs)


async def _enqueue_pending_events(
    session: AsyncSession, *, guild_id: str, ticket_id: str, correlation_id: str
) -> int:
    thread_id = await session.scalar(
        select(FarmTicketDiscordBinding.resource_id).where(
            FarmTicketDiscordBinding.guild_id == guild_id,
            FarmTicketDiscordBinding.ticket_id == ticket_id,
            FarmTicketDiscordBinding.kind == ResourceKind.TICKET_THREAD,
            FarmTicketDiscordBinding.state == BindingState.ACTIVE,
        )
    )
    if thread_id is None:
        return 0
    events = list(
        (
            await session.execute(
                select(FarmTicketEvent)
                .where(FarmTicketEvent.ticket_id == ticket_id)
                .order_by(FarmTicketEvent.sequence)
            )
        ).scalars()
    )
    for event in events:
        await _enqueue_delivery_row(
            session,
            guild_id=guild_id,
            renderer_key="farm_tickets.event",
            destination_type="thread",
            destination_id=thread_id,
            resource_type="farm_ticket_event",
            resource_id=event.id,
            payload={
                "ticket_id": ticket_id,
                "event_id": event.id,
                "sequence": event.sequence,
                "event_type": event.event_type,
                "actor_id": event.actor_id,
                "event_payload": event.payload,
            },
            idempotency_key=f"event:{event.id}:thread",
            correlation_id=correlation_id,
            # O worker ordena por priority; incorporar a sequencia impede que
            # UUIDs ou timestamps iguais embaralhem a reconstrucao historica.
            priority=100 + event.sequence,
        )
    return len(events)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _actor_id(actor: ActorContextIn) -> str:
    return actor.user_id or "Yuno"


async def _lock_ticket(
    session: AsyncSession, *, guild_id: str, ticket_id: str
) -> FarmTicket:
    ticket = (
        await session.execute(
            select(FarmTicket)
            .where(FarmTicket.guild_id == guild_id, FarmTicket.id == ticket_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if ticket is None:
        raise FarmTicketNotFound("Ticket nao encontrado.")
    return ticket


async def _event(
    session: AsyncSession,
    *,
    ticket: FarmTicket,
    event_type: str,
    actor_id: str | None,
    deduplication_key: str,
    payload: dict[str, Any] | None = None,
) -> FarmTicketEvent:
    existing = (
        await session.execute(
            select(FarmTicketEvent).where(
                FarmTicketEvent.guild_id == ticket.guild_id,
                FarmTicketEvent.deduplication_key == deduplication_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    sequence = (
        int(
            await session.scalar(
                select(func.coalesce(func.max(FarmTicketEvent.sequence), 0)).where(
                    FarmTicketEvent.ticket_id == ticket.id
                )
            )
            or 0
        )
        + 1
    )
    item = FarmTicketEvent(
        ticket_id=ticket.id,
        guild_id=ticket.guild_id,
        sequence=sequence,
        event_type=event_type,
        actor_id=actor_id,
        deduplication_key=deduplication_key,
        payload=payload or {},
    )
    session.add(item)
    await session.flush()
    await _enqueue_delivery_row(
        session,
        guild_id=ticket.guild_id,
        renderer_key="farm_tickets.panel",
        destination_type="panel",
        destination_id=ticket.id,
        resource_type="farm_ticket",
        resource_id=ticket.id,
        payload={"ticket_id": ticket.id, "event_id": item.id},
        idempotency_key=f"event:{item.id}:panel-refresh",
        correlation_id=deduplication_key[:80],
        priority=80,
    )
    await _enqueue_pending_events(
        session,
        guild_id=ticket.guild_id,
        ticket_id=ticket.id,
        correlation_id=deduplication_key[:80],
    )
    return item


async def _active_operation(
    session: AsyncSession, *, ticket_id: str, lock: bool = False
) -> FarmTicketPendingOperation | None:
    query = select(FarmTicketPendingOperation).where(
        FarmTicketPendingOperation.ticket_id == ticket_id,
        FarmTicketPendingOperation.status.in_(list(ACTIVE_OPERATION_STATUSES)),
    )
    if lock:
        query = query.with_for_update()
    return (await session.execute(query)).scalars().first()


def _operation_summary(operation: FarmTicketPendingOperation | None) -> dict | None:
    if operation is None:
        return None
    return {
        "id": operation.id,
        "kind": operation.kind.value,
        "status": operation.status.value,
        "actor_id": operation.actor_id,
        "proof_deadline": _utc(operation.proof_deadline).isoformat(),
        "proof_received_at": (
            _utc(operation.proof_received_at).isoformat()
            if operation.proof_received_at is not None
            else None
        ),
    }


async def _objective_rows(
    session: AsyncSession, *, ticket_id: str
) -> list[FarmTicketObjective]:
    return list(
        (
            await session.execute(
                select(FarmTicketObjective)
                .where(FarmTicketObjective.ticket_id == ticket_id)
                .order_by(FarmTicketObjective.position)
            )
        ).scalars()
    )


async def _totals(
    session: AsyncSession, *, ticket_id: str
) -> tuple[
    dict[str, Decimal],
    dict[str, Decimal],
    dict[str, Decimal],
    list[FarmTicketObjective],
]:
    objectives = await _objective_rows(session, ticket_id=ticket_id)
    launched = {item.id: Decimal("0") for item in objectives}
    withdrawn = {item.id: Decimal("0") for item in objectives}
    launched_rows = await session.execute(
        select(FarmTicketEntryItem.objective_id, func.sum(FarmTicketEntryItem.amount))
        .join(
            FarmTicketEntryRevision,
            FarmTicketEntryRevision.id == FarmTicketEntryItem.revision_id,
        )
        .where(
            FarmTicketEntryItem.ticket_id == ticket_id,
            FarmTicketEntryRevision.status == EntryRevisionStatus.CURRENT,
        )
        .group_by(FarmTicketEntryItem.objective_id)
    )
    for objective_id, amount in launched_rows:
        launched[objective_id] = Decimal(amount or 0)
    withdrawal_rows = await session.execute(
        select(FarmTicketAllocation.objective_id, func.sum(FarmTicketAllocation.amount))
        .where(FarmTicketAllocation.ticket_id == ticket_id)
        .group_by(FarmTicketAllocation.objective_id)
    )
    for objective_id, amount in withdrawal_rows:
        withdrawn[objective_id] = Decimal(amount or 0)
    available = {
        objective_id: max(
            Decimal("0"), launched[objective_id] - withdrawn[objective_id]
        )
        for objective_id in launched
    }
    return launched, withdrawn, available, objectives


async def ticket_dict(session: AsyncSession, ticket: FarmTicket) -> dict[str, Any]:
    launched, withdrawn, available, objectives = await _totals(
        session, ticket_id=ticket.id
    )
    cycle = (
        await session.execute(
            select(FarmTicketCycle).where(FarmTicketCycle.ticket_id == ticket.id)
        )
    ).scalar_one()
    entry_count = int(
        await session.scalar(
            select(func.count(FarmTicketEntry.id)).where(
                FarmTicketEntry.ticket_id == ticket.id,
                FarmTicketEntry.current_revision > 0,
            )
        )
        or 0
    )
    withdrawal_count = int(
        await session.scalar(
            select(func.count(FarmTicketWithdrawal.id)).where(
                FarmTicketWithdrawal.ticket_id == ticket.id
            )
        )
        or 0
    )
    progress = calculate_progress(
        [
            (item.id, launched[item.id], Decimal(item.target_amount))
            for item in objectives
        ]
    )
    operation = await _active_operation(session, ticket_id=ticket.id)
    allowed_actions = ["list_proofs"]
    has_balance = any(value > 0 for value in available.values())
    if operation is None:
        if (
            ticket.status == TicketStatus.IN_PROGRESS
            and ticket.operations_closed_at is None
            and ticket.member_left_at is None
        ):
            allowed_actions.extend(
                ["create_entry", "edit_entry", "assign", "approve", "finalize"]
            )
        if ticket.withdrawals_open and has_balance:
            allowed_actions.append("withdraw")
    return {
        "id": ticket.id,
        "guild_id": ticket.guild_id,
        "member_id": ticket.member_id,
        "member_name": ticket.member_name,
        "base_nickname": ticket.base_nickname,
        "player_id": ticket.player_id,
        "meta_goal_id": ticket.meta_goal_id,
        "meta_cycle_id": ticket.meta_cycle_id,
        "goal_name": cycle.goal_name,
        "cycle_starts_at": _utc(cycle.starts_at).isoformat(),
        "cycle_ends_at": _utc(cycle.ends_at).isoformat(),
        "cycle_timezone": cycle.timezone,
        "status": ticket.status.value,
        "revision": ticket.revision,
        "operations_open": ticket.operations_closed_at is None,
        "withdrawals_open": ticket.withdrawals_open,
        "launched": {key: str(value) for key, value in launched.items()},
        "withdrawn": {key: str(value) for key, value in withdrawn.items()},
        "available": {key: str(value) for key, value in available.items()},
        "progress_percent": str(progress.percent),
        "entry_count": entry_count,
        "withdrawal_count": withdrawal_count,
        "active_operation": _operation_summary(operation),
        "allowed_actions": allowed_actions,
        "objectives": [
            {
                "objective_id": item.id,
                "name": item.name,
                "kind": item.kind.value,
                "unit": item.unit,
                "target": str(item.target_amount),
                "launched": str(launched[item.id]),
                "withdrawn": str(withdrawn[item.id]),
                "available": str(available[item.id]),
                "remaining_to_goal": str(
                    max(Decimal("0"), Decimal(item.target_amount) - launched[item.id])
                ),
            }
            for item in objectives
        ],
        "assigned_admin_id": ticket.assigned_admin_id,
        "binding_released": ticket.binding_released_at is not None,
        "member_left_at": (
            _utc(ticket.member_left_at).isoformat()
            if ticket.member_left_at is not None
            else None
        ),
        "close_reason": ticket.close_reason.value if ticket.close_reason else None,
        "last_resource_removal_reason": (
            ticket.last_resource_removal_reason.value
            if ticket.last_resource_removal_reason
            else None
        ),
    }


async def _assert_expected(ticket: FarmTicket, expected_version: int) -> None:
    if ticket.revision != expected_version:
        raise FarmTicketConflict(
            f"Versao divergente: esperado {expected_version}, atual {ticket.revision}."
        )


async def _assert_cycle_open(
    session: AsyncSession, *, ticket: FarmTicket, require_participant: bool
) -> None:
    cycle = await meta_contracts.get_cycle(
        session, guild_id=ticket.guild_id, cycle_id=ticket.meta_cycle_id
    )
    if cycle is None or cycle.state != "active" or _utc(cycle.ends_at) <= utc_now():
        raise FarmTicketConflict("O ciclo da Meta nao esta mais ativo.")
    if require_participant and not await meta_contracts.is_member_participant(
        session,
        guild_id=ticket.guild_id,
        cycle_id=ticket.meta_cycle_id,
        member_id=ticket.member_id,
    ):
        raise FarmTicketConflict("O membro nao participa mais deste ciclo.")


async def _resolve_concurrent_open(
    session: AsyncSession,
    *,
    guild_id: str,
    member_id: str,
    meta_cycle_id: int,
) -> dict[str, Any]:
    winner = (
        await session.execute(
            select(FarmTicket).where(
                FarmTicket.guild_id == guild_id,
                FarmTicket.member_id == member_id,
                FarmTicket.binding_released_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if winner is not None:
        return await ticket_dict(session, winner)
    historical = (
        await session.execute(
            select(FarmTicket).where(
                FarmTicket.guild_id == guild_id,
                FarmTicket.meta_cycle_id == meta_cycle_id,
                FarmTicket.member_id == member_id,
            )
        )
    ).scalar_one_or_none()
    if historical is not None:
        raise FarmTicketConflict(
            "A participacao neste ciclo ja possui ticket encerrado e nao sera reativada."
        )
    raise FarmTicketConflict("A abertura concorrente do ticket nao pôde ser consolidada.")


async def open_ticket(
    session: AsyncSession,
    *,
    guild_id: str,
    member_id: str,
    actor: ActorContextIn,
    idempotency_key: str,
) -> dict[str, Any]:
    existing = (
        await session.execute(
            select(FarmTicket)
            .where(
                FarmTicket.guild_id == guild_id,
                FarmTicket.member_id == member_id,
                FarmTicket.binding_released_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None:
        return await ticket_dict(session, existing)
    identity = await read_base_member_identity(
        session, guild_id=guild_id, discord_user_id=member_id
    )
    if identity is None or identity.status.value != "active":
        raise FarmTicketConflict("O membro nao possui Registro ativo no Yuno.")
    active_goal = await meta_contracts.get_active_goal_for_member(
        session, guild_id=guild_id, member_id=member_id
    )
    if active_goal is None or active_goal.cycle.state != "active":
        raise FarmTicketConflict("Nao existe Meta ativa aplicavel ao membro.")
    now = utc_now()
    if _utc(active_goal.cycle.ends_at) <= now:
        raise FarmTicketConflict("O ciclo da Meta ja terminou.")
    historical = (
        await session.execute(
            select(FarmTicket)
            .where(
                FarmTicket.guild_id == guild_id,
                FarmTicket.meta_cycle_id == active_goal.cycle.cycle_id,
                FarmTicket.member_id == member_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if historical is not None:
        raise FarmTicketConflict(
            "A participacao neste ciclo ja possui ticket encerrado e nao sera reativada."
        )
    ticket = FarmTicket(
        guild_id=guild_id,
        member_id=member_id,
        meta_goal_id=active_goal.goal_id,
        meta_cycle_id=active_goal.cycle.cycle_id,
        registration_identity_id=identity.identity_id,
        member_name=identity.registered_name,
        player_id=identity.player_id,
        base_nickname=identity.base_nickname,
        created_by=_actor_id(actor),
    )
    session.add(ticket)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return await _resolve_concurrent_open(
            session,
            guild_id=guild_id,
            member_id=member_id,
            meta_cycle_id=active_goal.cycle.cycle_id,
        )
    session.add(
        FarmTicketCycle(
            ticket_id=ticket.id,
            guild_id=guild_id,
            meta_goal_id=active_goal.goal_id,
            meta_cycle_id=active_goal.cycle.cycle_id,
            goal_name=active_goal.cycle.name,
            timezone=active_goal.cycle.timezone,
            starts_at=_utc(active_goal.cycle.starts_at),
            ends_at=_utc(active_goal.cycle.ends_at),
        )
    )
    for item in active_goal.objectives:
        kind = ObjectiveKind(item.kind.value)
        raw_target = (
            item.money_amount if kind == ObjectiveKind.MONEY else item.item_quantity
        )
        if raw_target is None:
            raise FarmTicketError("Objetivo de Meta sem quantidade congelada.")
        session.add(
            FarmTicketObjective(
                ticket_id=ticket.id,
                guild_id=guild_id,
                meta_objective_id=item.objective_id,
                kind=kind,
                name=item.name,
                unit=item.unit,
                target_amount=decimal_amount(
                    raw_target, money=kind == ObjectiveKind.MONEY
                ),
                position=item.position,
            )
        )
    await _event(
        session,
        ticket=ticket,
        event_type="ticket.created",
        actor_id=_actor_id(actor),
        deduplication_key=f"open:{guild_id}:{idempotency_key}",
        payload={
            "meta_goal_id": ticket.meta_goal_id,
            "meta_cycle_id": ticket.meta_cycle_id,
        },
    )
    await _schedule_ticket_task(
        session,
        guild_id=guild_id,
        job_key="farm_tickets.provision",
        resource_type="farm_ticket",
        resource_id=ticket.id,
        payload={"ticket_id": ticket.id},
        due_at=now,
        idempotency_key=f"ticket:{ticket.id}:provision:v1",
        correlation_id=actor.correlation_id,
        max_attempts=10,
        commit=False,
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return await _resolve_concurrent_open(
            session,
            guild_id=guild_id,
            member_id=member_id,
            meta_cycle_id=active_goal.cycle.cycle_id,
        )
    await session.refresh(ticket)
    return await ticket_dict(session, ticket)


async def get_ticket(
    session: AsyncSession, *, guild_id: str, ticket_id: str
) -> dict[str, Any]:
    ticket = await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    return await ticket_dict(session, ticket)


async def get_active_ticket_for_member(
    session: AsyncSession, *, guild_id: str, member_id: str
) -> dict[str, Any] | None:
    ticket = (
        await session.execute(
            select(FarmTicket).where(
                FarmTicket.guild_id == guild_id,
                FarmTicket.member_id == member_id,
                FarmTicket.binding_released_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    return await ticket_dict(session, ticket) if ticket is not None else None


async def list_tickets(
    session: AsyncSession,
    *,
    guild_id: str,
    active_only: bool = True,
    reconcile_only: bool = False,
) -> list[dict[str, Any]]:
    query = select(FarmTicket).where(FarmTicket.guild_id == guild_id)
    if reconcile_only:
        pending_binding = (
            select(FarmTicketDiscordBinding.id)
            .where(
                FarmTicketDiscordBinding.ticket_id == FarmTicket.id,
                FarmTicketDiscordBinding.state.in_(
                    [
                        BindingState.PROVISIONING,
                        BindingState.MISSING,
                        BindingState.DELETE_PENDING,
                    ]
                ),
            )
            .exists()
        )
        query = query.where(
            or_(
                FarmTicket.binding_released_at.is_(None),
                FarmTicket.provisioning_error.is_not(None),
                pending_binding,
            )
        )
    elif active_only:
        query = query.where(FarmTicket.binding_released_at.is_(None))
    tickets = list(
        (await session.execute(query.order_by(FarmTicket.created_at))).scalars()
    )
    return [await ticket_dict(session, ticket) for ticket in tickets]


async def get_active_operation_for_channel(
    session: AsyncSession, *, guild_id: str, channel_id: str
) -> dict[str, Any] | None:
    ticket_id = await session.scalar(
        select(FarmTicketDiscordBinding.ticket_id).where(
            FarmTicketDiscordBinding.guild_id == guild_id,
            FarmTicketDiscordBinding.resource_id == channel_id,
            FarmTicketDiscordBinding.kind == ResourceKind.TICKET_CHANNEL,
            FarmTicketDiscordBinding.state.in_(
                [BindingState.PROVISIONING, BindingState.ACTIVE]
            ),
        )
    )
    if ticket_id is None:
        return None
    ticket = await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    operation = await _active_operation(session, ticket_id=ticket_id)
    if operation is None:
        return None
    return {
        "ticket": await ticket_dict(session, ticket),
        "operation": _operation_summary(operation),
    }


async def list_entries(
    session: AsyncSession,
    *,
    guild_id: str,
    ticket_id: str,
    editable_only: bool = False,
) -> list[dict[str, Any]]:
    await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    entries = list(
        (
            await session.execute(
                select(FarmTicketEntry)
                .where(
                    FarmTicketEntry.ticket_id == ticket_id,
                    FarmTicketEntry.current_revision > 0,
                )
                .order_by(FarmTicketEntry.number)
            )
        ).scalars()
    )
    entry_ids = [entry.id for entry in entries]
    if not entry_ids:
        return []
    allocated_entry_ids = set(
        (
            await session.execute(
                select(FarmTicketEntryItem.entry_id)
                .join(
                    FarmTicketAllocation,
                    FarmTicketAllocation.entry_item_id == FarmTicketEntryItem.id,
                )
                .where(FarmTicketEntryItem.entry_id.in_(entry_ids))
                .distinct()
            )
        ).scalars()
    )
    revisions = {
        revision.entry_id: revision
        for revision in (
            await session.execute(
                select(FarmTicketEntryRevision).where(
                    FarmTicketEntryRevision.entry_id.in_(entry_ids),
                    FarmTicketEntryRevision.status == EntryRevisionStatus.CURRENT,
                )
            )
        ).scalars()
    }
    items_by_revision: dict[
        str, list[tuple[FarmTicketEntryItem, FarmTicketObjective]]
    ] = {}
    revision_ids = [revision.id for revision in revisions.values()]
    if revision_ids:
        item_rows = (
            await session.execute(
                select(FarmTicketEntryItem, FarmTicketObjective)
                .join(
                    FarmTicketObjective,
                    FarmTicketObjective.id == FarmTicketEntryItem.objective_id,
                )
                .where(FarmTicketEntryItem.revision_id.in_(revision_ids))
                .order_by(FarmTicketEntryItem.revision_id, FarmTicketObjective.position)
            )
        ).all()
        for item, objective in item_rows:
            items_by_revision.setdefault(item.revision_id, []).append((item, objective))
    result: list[dict[str, Any]] = []
    for entry in entries:
        allocated = entry.id in allocated_entry_ids
        if editable_only and allocated:
            continue
        revision = revisions[entry.id]
        items = items_by_revision.get(revision.id, [])
        result.append(
            {
                "id": entry.id,
                "number": entry.number,
                "actor_id": entry.actor_id,
                "revision": revision.version,
                "editable": not allocated,
                "items": [
                    {
                        "objective_id": item.objective_id,
                        "name": objective.name,
                        "amount": str(item.amount),
                        "unit": objective.unit,
                    }
                    for item, objective in items
                ],
            }
        )
    return result


async def _validate_values(
    session: AsyncSession,
    *,
    ticket_id: str,
    values: Iterable[tuple[str, Decimal]],
) -> list[tuple[FarmTicketObjective, Decimal]]:
    objectives = {
        item.id: item for item in await _objective_rows(session, ticket_id=ticket_id)
    }
    normalized: list[tuple[FarmTicketObjective, Decimal]] = []
    seen: set[str] = set()
    for objective_id, raw_amount in values:
        if objective_id in seen:
            raise FarmTicketError("Objetivo repetido no lancamento.")
        seen.add(objective_id)
        objective = objectives.get(objective_id)
        if objective is None:
            raise FarmTicketError("Objetivo nao pertence ao ticket.")
        normalized.append(
            (
                objective,
                decimal_amount(raw_amount, money=objective.kind == ObjectiveKind.MONEY),
            )
        )
    if not normalized:
        raise FarmTicketError("Informe ao menos um valor maior que zero.")
    return normalized


async def _entry_has_allocation(session: AsyncSession, *, entry_id: str) -> bool:
    allocation_id = await session.scalar(
        select(FarmTicketAllocation.id)
        .join(
            FarmTicketEntryItem,
            FarmTicketEntryItem.id == FarmTicketAllocation.entry_item_id,
        )
        .where(FarmTicketEntryItem.entry_id == entry_id)
        .limit(1)
    )
    return allocation_id is not None


def _draft_dict(
    draft: FarmTicketFormDraft, objectives: list[FarmTicketObjective]
) -> dict[str, Any]:
    values = dict(draft.values or {})
    return {
        "id": draft.id,
        "ticket_id": draft.ticket_id,
        "kind": draft.operation_kind.value,
        "target_entry_id": draft.target_entry_id,
        "step": draft.step,
        "revision": draft.revision,
        "total_steps": max(1, (len(objectives) + 4) // 5),
        "objectives": [
            {
                "objective_id": item.id,
                "name": item.name,
                "unit": item.unit,
                "kind": item.kind.value,
                "target": str(item.target_amount),
                "value": values.get(item.id, "0"),
            }
            for item in objectives
        ],
    }


async def open_form_draft(
    session: AsyncSession,
    *,
    guild_id: str,
    ticket_id: str,
    actor: ActorContextIn,
    expected_version: int,
    kind: FormKind,
    target_entry_id: str | None,
) -> dict[str, Any]:
    ticket = await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    await _assert_expected(ticket, expected_version)
    if kind == FormKind.WITHDRAWAL:
        if not ticket.withdrawals_open:
            raise FarmTicketConflict("Recolhimentos estao encerrados para este ticket.")
        await _assert_cycle_open(session, ticket=ticket, require_participant=False)
    else:
        if (
            ticket.status != TicketStatus.IN_PROGRESS
            or ticket.operations_closed_at is not None
        ):
            raise FarmTicketConflict(
                "O ticket nao aceita novos lancamentos ou edicoes."
            )
        if ticket.member_left_at is not None:
            raise FarmTicketConflict("O membro saiu da guild.")
        await _assert_cycle_open(session, ticket=ticket, require_participant=True)
    active = await _active_operation(session, ticket_id=ticket.id, lock=True)
    if active is not None:
        raise FarmTicketConflict(
            f"Ja existe operacao {active.status.value} neste ticket."
        )
    objectives = await _objective_rows(session, ticket_id=ticket.id)
    if kind == FormKind.WITHDRAWAL:
        _, _, available, _ = await _totals(session, ticket_id=ticket.id)
        objectives = [item for item in objectives if available[item.id] > 0]
        if not objectives:
            raise FarmTicketConflict("Nao existe saldo disponivel para recolher.")
    initial_values = {item.id: "0" for item in objectives}
    if kind == FormKind.EDIT_ENTRY:
        if not target_entry_id:
            raise FarmTicketError("Selecione o lancamento que sera editado.")
        entry = (
            await session.execute(
                select(FarmTicketEntry)
                .where(
                    FarmTicketEntry.id == target_entry_id,
                    FarmTicketEntry.ticket_id == ticket.id,
                    FarmTicketEntry.current_revision > 0,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if entry is None:
            raise FarmTicketNotFound("Lancamento editavel nao encontrado.")
        if await _entry_has_allocation(session, entry_id=entry.id):
            raise FarmTicketConflict(
                "Lancamento com recolhimento nao pode ser editado."
            )
        rows = await session.execute(
            select(FarmTicketEntryItem.objective_id, FarmTicketEntryItem.amount)
            .join(
                FarmTicketEntryRevision,
                FarmTicketEntryRevision.id == FarmTicketEntryItem.revision_id,
            )
            .where(
                FarmTicketEntryItem.entry_id == entry.id,
                FarmTicketEntryRevision.status == EntryRevisionStatus.CURRENT,
            )
        )
        for objective_id, amount in rows:
            initial_values[objective_id] = str(amount)
    draft = (
        await session.execute(
            select(FarmTicketFormDraft)
            .where(
                FarmTicketFormDraft.ticket_id == ticket.id,
                FarmTicketFormDraft.actor_id == _actor_id(actor),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if draft is None:
        draft = FarmTicketFormDraft(
            ticket_id=ticket.id,
            guild_id=guild_id,
            actor_id=_actor_id(actor),
            operation_kind=kind,
            target_entry_id=target_entry_id,
            values=initial_values,
        )
        session.add(draft)
    elif draft.operation_kind != kind or draft.target_entry_id != target_entry_id:
        draft.operation_kind = kind
        draft.target_entry_id = target_entry_id
        draft.step = 0
        draft.revision += 1
        draft.values = initial_values
    await session.commit()
    await session.refresh(draft)
    return _draft_dict(draft, objectives)


async def save_form_step(
    session: AsyncSession,
    *,
    guild_id: str,
    ticket_id: str,
    draft_id: str,
    actor: ActorContextIn,
    expected_version: int,
    draft_revision: int,
    step: int,
    values: Iterable[tuple[str, Decimal]],
    idempotency_key: str,
    interaction_id: str | None = None,
) -> dict[str, Any]:
    ticket = await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    await _assert_expected(ticket, expected_version)
    draft = (
        await session.execute(
            select(FarmTicketFormDraft)
            .where(
                FarmTicketFormDraft.id == draft_id,
                FarmTicketFormDraft.ticket_id == ticket.id,
                FarmTicketFormDraft.actor_id == _actor_id(actor),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if draft is None:
        existing_operation = (
            await session.execute(
                select(FarmTicketPendingOperation).where(
                    FarmTicketPendingOperation.guild_id == guild_id,
                    FarmTicketPendingOperation.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing_operation is not None:
            return {
                "completed": True,
                "operation": _operation_summary(existing_operation),
            }
        raise FarmTicketNotFound("Rascunho do formulario nao encontrado.")
    if draft.revision != draft_revision or draft.step != step:
        raise FarmTicketConflict(
            f"Etapa divergente: rascunho na etapa {draft.step}, revisao {draft.revision}."
        )
    objectives = await _objective_rows(session, ticket_id=ticket.id)
    total_steps = max(1, (len(objectives) + 4) // 5)
    visible = objectives[step * 5 : step * 5 + 5]
    visible_ids = {item.id for item in visible}
    submitted = list(values)
    if {item[0] for item in submitted} != visible_ids:
        raise FarmTicketError("A etapa deve informar exatamente os objetivos exibidos.")
    merged = dict(draft.values or {})
    objective_by_id = {item.id: item for item in visible}
    for objective_id, raw_amount in submitted:
        amount = Decimal(str(raw_amount))
        if not amount.is_finite() or amount < 0:
            raise FarmTicketError("Valor do formulario deve ser zero ou positivo.")
        objective = objective_by_id[objective_id]
        quantum = (
            Decimal("0.01")
            if objective.kind == ObjectiveKind.MONEY
            else Decimal("0.001")
        )
        merged[objective_id] = str(amount.quantize(quantum))
    draft.values = merged
    draft.revision += 1
    if step + 1 < total_steps:
        draft.step += 1
        await session.commit()
        await session.refresh(draft)
        return {"completed": False, "draft": _draft_dict(draft, objectives)}
    positive = [
        (objective_id, Decimal(value))
        for objective_id, value in merged.items()
        if Decimal(value) > 0
    ]
    kind = draft.operation_kind
    target_entry_id = draft.target_entry_id
    await session.commit()
    if kind == FormKind.WITHDRAWAL:
        result = await withdraw(
            session,
            guild_id=guild_id,
            ticket_id=ticket.id,
            actor=actor,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            values=positive,
        )
        completed_result: dict[str, Any] = {"ticket": result}
    else:
        operation = await begin_operation(
            session,
            guild_id=guild_id,
            ticket_id=ticket.id,
            actor=actor,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            kind=OperationKind(kind.value),
            values=positive,
            target_entry_id=target_entry_id,
            interaction_id=interaction_id,
        )
        completed_result = {"operation": operation}
    await session.execute(
        delete(FarmTicketFormDraft).where(FarmTicketFormDraft.id == draft_id)
    )
    await session.commit()
    return {"completed": True, **completed_result}


async def begin_operation(
    session: AsyncSession,
    *,
    guild_id: str,
    ticket_id: str,
    actor: ActorContextIn,
    expected_version: int,
    idempotency_key: str,
    kind: OperationKind,
    values: Iterable[tuple[str, Decimal]],
    target_entry_id: str | None = None,
    interaction_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    existing = (
        await session.execute(
            select(FarmTicketPendingOperation).where(
                FarmTicketPendingOperation.guild_id == guild_id,
                FarmTicketPendingOperation.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return _operation_summary(existing) or {}
    ticket = await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    await _assert_expected(ticket, expected_version)
    if (
        ticket.status != TicketStatus.IN_PROGRESS
        or ticket.operations_closed_at is not None
    ):
        raise FarmTicketConflict("O ticket nao aceita novos lancamentos ou edicoes.")
    if ticket.member_left_at is not None:
        raise FarmTicketConflict(
            "O membro saiu da guild; o ticket esta somente para recolhimento."
        )
    await _assert_cycle_open(session, ticket=ticket, require_participant=True)
    active = await _active_operation(session, ticket_id=ticket.id, lock=True)
    if active is not None:
        raise FarmTicketConflict(
            f"Ja existe operacao {active.status.value} ate {_utc(active.proof_deadline).isoformat()}."
        )
    normalized = await _validate_values(session, ticket_id=ticket.id, values=values)
    if kind == OperationKind.EDIT_ENTRY:
        if not target_entry_id:
            raise FarmTicketError("Selecione o lancamento que sera editado.")
        entry = (
            await session.execute(
                select(FarmTicketEntry)
                .where(
                    FarmTicketEntry.id == target_entry_id,
                    FarmTicketEntry.ticket_id == ticket.id,
                    FarmTicketEntry.current_revision > 0,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if entry is None:
            raise FarmTicketNotFound("Lancamento editavel nao encontrado.")
        if await _entry_has_allocation(session, entry_id=entry.id):
            raise FarmTicketConflict(
                "Lancamento com recolhimento nao pode ser editado."
            )
        version = entry.current_revision + 1
    else:
        next_number = (
            int(
                await session.scalar(
                    select(func.coalesce(func.max(FarmTicketEntry.number), 0)).where(
                        FarmTicketEntry.ticket_id == ticket.id
                    )
                )
                or 0
            )
            + 1
        )
        entry = FarmTicketEntry(
            ticket_id=ticket.id,
            guild_id=guild_id,
            number=next_number,
            actor_id=_actor_id(actor),
        )
        session.add(entry)
        await session.flush()
        version = 1
    revision = FarmTicketEntryRevision(
        entry_id=entry.id,
        ticket_id=ticket.id,
        guild_id=guild_id,
        version=version,
        status=EntryRevisionStatus.PENDING,
        actor_id=_actor_id(actor),
    )
    session.add(revision)
    await session.flush()
    for objective, amount in normalized:
        session.add(
            FarmTicketEntryItem(
                revision_id=revision.id,
                entry_id=entry.id,
                ticket_id=ticket.id,
                objective_id=objective.id,
                amount=amount,
            )
        )
    created_at = _utc(now or utc_now())
    operation = FarmTicketPendingOperation(
        ticket_id=ticket.id,
        guild_id=guild_id,
        kind=kind,
        status=OperationStatus.AWAITING_PROOF,
        target_entry_id=target_entry_id,
        pending_entry_id=entry.id,
        pending_revision_id=revision.id,
        actor_id=_actor_id(actor),
        idempotency_key=idempotency_key,
        interaction_id=interaction_id,
        proof_deadline=created_at + PROOF_WINDOW,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(operation)
    ticket.revision += 1
    await _event(
        session,
        ticket=ticket,
        event_type="operation.awaiting_proof",
        actor_id=_actor_id(actor),
        deduplication_key=f"operation:{idempotency_key}:started",
        payload={"operation_id": operation.id, "kind": kind.value},
    )
    await _schedule_ticket_task(
        session,
        guild_id=guild_id,
        job_key="farm_tickets.operation.expire",
        resource_type="farm_ticket_operation",
        resource_id=operation.id,
        payload={"operation_id": operation.id},
        due_at=operation.proof_deadline,
        idempotency_key=f"operation:{operation.id}:expire",
        correlation_id=actor.correlation_id,
        max_attempts=10,
        commit=False,
    )
    await session.commit()
    await session.refresh(operation)
    return _operation_summary(operation) or {}


async def claim_proof(
    session: AsyncSession,
    *,
    guild_id: str,
    ticket_id: str,
    operation_id: str,
    actor: ActorContextIn,
    expected_version: int,
    message_id: str,
    attachment_id: str,
    author_id: str,
    channel_id: str,
    received_at: datetime,
    filename: str,
    content_type: str | None,
    size_bytes: int,
    source_url: str,
) -> dict[str, Any]:
    ticket = await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    await _assert_expected(ticket, expected_version)
    operation = (
        await session.execute(
            select(FarmTicketPendingOperation)
            .where(
                FarmTicketPendingOperation.id == operation_id,
                FarmTicketPendingOperation.ticket_id == ticket.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if operation is None:
        raise FarmTicketNotFound("Operacao pendente nao encontrada.")
    if operation.proof_message_id == message_id and operation.claim_token:
        return {
            **(_operation_summary(operation) or {}),
            "claim_token": operation.claim_token,
        }
    if operation.status != OperationStatus.AWAITING_PROOF:
        raise FarmTicketConflict(f"A operacao esta em {operation.status.value}.")
    received = _utc(received_at)
    if author_id != operation.actor_id:
        raise FarmTicketConflict(
            "Somente o autor da operacao pode enviar o comprovante."
        )
    if size_bytes <= 0 or size_bytes > 20 * 1024 * 1024:
        raise FarmTicketError("O comprovante deve ter no maximo 20 MiB.")
    if received > _utc(operation.proof_deadline):
        raise FarmTicketConflict(
            "A imagem foi recebida depois do prazo de cinco minutos."
        )
    cycle = (
        await session.execute(
            select(FarmTicketCycle).where(FarmTicketCycle.ticket_id == ticket.id)
        )
    ).scalar_one()
    effective_end = _utc(cycle.ends_at)
    if cycle.participation_ended_at is not None:
        effective_end = min(effective_end, _utc(cycle.participation_ended_at))
    if received > effective_end:
        raise FarmTicketConflict(
            "A imagem chegou depois do encerramento da participacao."
        )
    binding_channel = await session.scalar(
        select(FarmTicketDiscordBinding.resource_id).where(
            FarmTicketDiscordBinding.ticket_id == ticket.id,
            FarmTicketDiscordBinding.kind == ResourceKind.TICKET_CHANNEL,
            FarmTicketDiscordBinding.state.in_(
                [BindingState.PROVISIONING, BindingState.ACTIVE]
            ),
        )
    )
    if binding_channel is not None and binding_channel != channel_id:
        raise FarmTicketConflict("O comprovante deve ser enviado no canal do ticket.")
    claimed_at = utc_now()
    token = secrets.token_urlsafe(48)
    candidate = FarmTicketProofCandidate(
        operation_id=operation.id,
        ticket_id=ticket.id,
        guild_id=guild_id,
        message_id=message_id,
        attachment_id=attachment_id,
        author_id=author_id,
        channel_id=channel_id,
        received_at=received,
        claimed_at=claimed_at,
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        source_url=source_url,
        claim_token=token,
    )
    session.add(candidate)
    operation.status = OperationStatus.PROOF_CLAIMED
    operation.claim_token = token
    operation.proof_message_id = message_id
    operation.proof_attachment_id = attachment_id
    operation.proof_author_id = author_id
    operation.proof_channel_id = channel_id
    operation.proof_received_at = received
    operation.claimed_at = claimed_at
    operation.attachment_filename = filename
    operation.attachment_content_type = content_type
    operation.attachment_size = size_bytes
    operation.attachment_url = source_url
    operation.processing_error = None
    ticket.revision += 1
    await _event(
        session,
        ticket=ticket,
        event_type="proof.claimed",
        actor_id=author_id,
        deduplication_key=f"proof-message:{guild_id}:{message_id}",
        payload={
            "operation_id": operation.id,
            "attachment_id": attachment_id,
            "received_at": received.isoformat(),
        },
    )
    await _schedule_ticket_task(
        session,
        guild_id=guild_id,
        job_key="farm_tickets.proof.process",
        resource_type="farm_ticket_proof_candidate",
        resource_id=candidate.id,
        payload={
            "ticket_id": ticket.id,
            "operation_id": operation.id,
            "claim_token": token,
        },
        due_at=claimed_at,
        idempotency_key=f"proof-candidate:{candidate.id}:process",
        correlation_id=actor.correlation_id,
        max_attempts=10,
        commit=False,
    )
    await session.commit()  # claim duravel antes de download, validacao ou S3
    return {**(_operation_summary(operation) or {}), "claim_token": token}


async def mark_proof_processing(
    session: AsyncSession,
    *,
    guild_id: str,
    ticket_id: str,
    operation_id: str,
    claim_token: str,
) -> None:
    await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    operation = (
        await session.execute(
            select(FarmTicketPendingOperation)
            .where(
                FarmTicketPendingOperation.id == operation_id,
                FarmTicketPendingOperation.ticket_id == ticket_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if operation is None or operation.claim_token != claim_token:
        raise FarmTicketConflict("Claim de comprovante invalido.")
    if operation.status not in {
        OperationStatus.PROOF_CLAIMED,
        OperationStatus.RETRYING_PROOF,
        OperationStatus.PROCESSING_PROOF,
    }:
        raise FarmTicketConflict(f"A operacao esta em {operation.status.value}.")
    operation.status = OperationStatus.PROCESSING_PROOF
    operation.attempts += 1
    operation.processing_error = None
    await session.commit()


async def retry_proof(
    session: AsyncSession,
    *,
    guild_id: str,
    ticket_id: str,
    operation_id: str,
    claim_token: str,
    error: str,
) -> None:
    ticket = await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    operation = (
        await session.execute(
            select(FarmTicketPendingOperation)
            .where(
                FarmTicketPendingOperation.id == operation_id,
                FarmTicketPendingOperation.ticket_id == ticket_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if operation is None or operation.claim_token != claim_token:
        raise FarmTicketConflict("Claim de comprovante invalido.")
    if operation.status not in CLAIMED_OPERATION_STATUSES:
        raise FarmTicketConflict(f"A operacao esta em {operation.status.value}.")
    operation.status = OperationStatus.RETRYING_PROOF
    operation.processing_error = error[:2000]
    ticket.revision += 1
    await _event(
        session,
        ticket=ticket,
        event_type="proof.retrying",
        actor_id="Yuno",
        deduplication_key=f"proof:{operation.id}:retry:{operation.attempts}",
        payload={"error": error[:500]},
    )
    await session.commit()


async def reject_invalid_proof(
    session: AsyncSession,
    *,
    guild_id: str,
    ticket_id: str,
    operation_id: str,
    claim_token: str,
    reason: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    ticket = await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    operation = (
        await session.execute(
            select(FarmTicketPendingOperation)
            .where(
                FarmTicketPendingOperation.id == operation_id,
                FarmTicketPendingOperation.ticket_id == ticket.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if operation is None or operation.claim_token != claim_token:
        raise FarmTicketConflict("Claim de comprovante invalido.")
    if operation.status not in CLAIMED_OPERATION_STATUSES:
        raise FarmTicketConflict(f"A operacao esta em {operation.status.value}.")
    candidate = (
        await session.execute(
            select(FarmTicketProofCandidate).where(
                FarmTicketProofCandidate.operation_id == operation.id,
                FarmTicketProofCandidate.claim_token == claim_token,
            )
        )
    ).scalar_one()
    resolved = _utc(now or utc_now())
    candidate.status = ProofCandidateStatus.REJECTED
    candidate.rejection_reason = reason[:2000]
    candidate.resolved_at = resolved
    operation.claim_token = None
    operation.proof_message_id = None
    operation.proof_attachment_id = None
    operation.proof_author_id = None
    operation.proof_channel_id = None
    operation.proof_received_at = None
    operation.claimed_at = None
    operation.attachment_filename = None
    operation.attachment_content_type = None
    operation.attachment_size = None
    operation.attachment_url = None
    operation.processing_error = reason[:2000]
    revision = await session.get(FarmTicketEntryRevision, operation.pending_revision_id)
    if resolved <= _utc(operation.proof_deadline):
        operation.status = OperationStatus.AWAITING_PROOF
    else:
        operation.status = OperationStatus.EXPIRED
        operation.completed_at = resolved
        if revision is not None:
            revision.status = EntryRevisionStatus.REJECTED
    ticket.revision += 1
    await _event(
        session,
        ticket=ticket,
        event_type="proof.rejected",
        actor_id="Yuno",
        deduplication_key=f"proof-candidate:{candidate.id}:rejected",
        payload={"reason": reason[:500], "operation_status": operation.status.value},
    )
    await session.commit()
    return _operation_summary(operation) or {}


async def expire_operation(
    session: AsyncSession,
    *,
    guild_id: str,
    operation_id: str,
    now: datetime | None = None,
) -> bool:
    ticket_id = await session.scalar(
        select(FarmTicketPendingOperation.ticket_id).where(
            FarmTicketPendingOperation.guild_id == guild_id,
            FarmTicketPendingOperation.id == operation_id,
        )
    )
    if ticket_id is None:
        return False
    ticket = await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    operation = (
        await session.execute(
            select(FarmTicketPendingOperation)
            .where(
                FarmTicketPendingOperation.guild_id == guild_id,
                FarmTicketPendingOperation.id == operation_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if operation is None:
        return False
    instant = _utc(now or utc_now())
    if operation.status != OperationStatus.AWAITING_PROOF:
        return False
    if instant <= _utc(operation.proof_deadline):
        return False
    operation.status = OperationStatus.EXPIRED
    operation.completed_at = instant
    revision = await session.get(FarmTicketEntryRevision, operation.pending_revision_id)
    if revision is not None:
        revision.status = EntryRevisionStatus.REJECTED
    ticket.revision += 1
    await _event(
        session,
        ticket=ticket,
        event_type="operation.expired",
        actor_id="Yuno",
        deduplication_key=f"operation:{operation.id}:expired",
        payload={"proof_deadline": _utc(operation.proof_deadline).isoformat()},
    )
    await session.commit()
    return True


async def fail_operation_definitively(
    session: AsyncSession,
    *,
    guild_id: str,
    operation_id: str,
    error: str,
) -> None:
    ticket_id = await session.scalar(
        select(FarmTicketPendingOperation.ticket_id).where(
            FarmTicketPendingOperation.guild_id == guild_id,
            FarmTicketPendingOperation.id == operation_id,
        )
    )
    if ticket_id is None:
        raise FarmTicketNotFound("Operacao nao encontrada.")
    ticket = await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    operation = (
        await session.execute(
            select(FarmTicketPendingOperation)
            .where(
                FarmTicketPendingOperation.guild_id == guild_id,
                FarmTicketPendingOperation.id == operation_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if operation is None:
        raise FarmTicketNotFound("Operacao nao encontrada.")
    if operation.status not in ACTIVE_OPERATION_STATUSES:
        return
    operation.status = OperationStatus.FAILED
    operation.failed_recoverably = True
    operation.processing_error = error[:2000]
    operation.completed_at = utc_now()
    revision = await session.get(FarmTicketEntryRevision, operation.pending_revision_id)
    if revision is not None:
        revision.status = EntryRevisionStatus.REJECTED
    ticket.revision += 1
    await _event(
        session,
        ticket=ticket,
        event_type="operation.failed",
        actor_id="Yuno",
        deduplication_key=f"operation:{operation.id}:failed",
        payload={"error": error[:500], "recoverable": True},
    )
    await session.commit()


async def confirm_proof(
    session: AsyncSession,
    *,
    guild_id: str,
    ticket_id: str,
    operation_id: str,
    claim_token: str,
    object_key: str,
    checksum_sha256: str,
    size_bytes: int,
    content_type: str,
) -> dict[str, Any]:
    ticket = await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    operation = (
        await session.execute(
            select(FarmTicketPendingOperation)
            .where(
                FarmTicketPendingOperation.id == operation_id,
                FarmTicketPendingOperation.ticket_id == ticket.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if operation is None or operation.claim_token != claim_token:
        raise FarmTicketConflict("Claim de comprovante invalido.")
    if operation.status == OperationStatus.CONFIRMED:
        return await ticket_dict(session, ticket)
    if operation.status not in CLAIMED_OPERATION_STATUSES:
        raise FarmTicketConflict(f"A operacao esta em {operation.status.value}.")
    if operation.proof_received_at is None or _utc(operation.proof_received_at) > _utc(
        operation.proof_deadline
    ):
        raise FarmTicketConflict("O comprovante nao foi recebido dentro do prazo.")
    cycle = (
        await session.execute(
            select(FarmTicketCycle).where(FarmTicketCycle.ticket_id == ticket.id)
        )
    ).scalar_one()
    effective_end = _utc(cycle.ends_at)
    if cycle.participation_ended_at is not None:
        effective_end = min(effective_end, _utc(cycle.participation_ended_at))
    if _utc(operation.proof_received_at) > effective_end:
        raise ProofNoLongerEligible(
            "O comprovante chegou depois do encerramento efetivo da participacao."
        )
    revision = await session.get(FarmTicketEntryRevision, operation.pending_revision_id)
    entry = await session.get(FarmTicketEntry, operation.pending_entry_id)
    if revision is None or entry is None:
        raise FarmTicketConflict("Revisao pendente inconsistente.")
    if operation.kind == OperationKind.EDIT_ENTRY:
        if await _entry_has_allocation(session, entry_id=entry.id):
            raise FarmTicketConflict(
                "O lancamento foi recolhido e a edicao nao pode ser aplicada."
            )
        previous = (
            await session.execute(
                select(FarmTicketEntryRevision).where(
                    FarmTicketEntryRevision.entry_id == entry.id,
                    FarmTicketEntryRevision.status == EntryRevisionStatus.CURRENT,
                )
            )
        ).scalar_one()
        previous.status = EntryRevisionStatus.SUPERSEDED
    candidate = (
        await session.execute(
            select(FarmTicketProofCandidate).where(
                FarmTicketProofCandidate.operation_id == operation.id,
                FarmTicketProofCandidate.claim_token == claim_token,
            )
        )
    ).scalar_one()
    now = utc_now()
    proof = FarmTicketProof(
        operation_id=operation.id,
        ticket_id=ticket.id,
        entry_revision_id=revision.id,
        guild_id=guild_id,
        message_id=candidate.message_id,
        attachment_id=candidate.attachment_id,
        author_id=candidate.author_id,
        channel_id=candidate.channel_id,
        received_at=_utc(candidate.received_at),
        object_key=object_key,
        checksum_sha256=checksum_sha256,
        size_bytes=size_bytes,
        content_type=content_type,
        original_filename=candidate.filename,
        storage_state=ProofStorageState.STORED,
    )
    session.add(proof)
    candidate.status = ProofCandidateStatus.ACCEPTED
    candidate.resolved_at = now
    revision.status = EntryRevisionStatus.CURRENT
    revision.confirmed_at = now
    entry.current_revision = revision.version
    operation.status = OperationStatus.CONFIRMED
    operation.completed_at = now
    operation.processing_error = None
    ticket.revision += 1
    await session.flush()
    view = await ticket_dict(session, ticket)
    auto_approved = Decimal(view["progress_percent"]) >= Decimal("100")
    if auto_approved and ticket.status == TicketStatus.IN_PROGRESS:
        ticket.status = TicketStatus.APPROVED
        ticket.operations_closed_at = now
        ticket.result_finalized_at = now
        ticket.close_reason = TicketCloseReason.APPROVED
        if not any(Decimal(value) > 0 for value in view["available"].values()):
            ticket.withdrawals_open = False
            ticket.settlement_closed_at = now
        ticket.revision += 1
    await _event(
        session,
        ticket=ticket,
        event_type="entry.edited"
        if operation.kind == OperationKind.EDIT_ENTRY
        else "entry.confirmed",
        actor_id=operation.actor_id,
        deduplication_key=f"operation:{operation.id}:confirmed",
        payload={
            "entry_id": entry.id,
            "entry_number": entry.number,
            "revision": revision.version,
            "proof_id": proof.id,
            "auto_approved": auto_approved,
        },
    )
    if auto_approved:
        await _event(
            session,
            ticket=ticket,
            event_type="ticket.approved_automatically",
            actor_id="Yuno",
            deduplication_key=f"ticket:{ticket.id}:auto-approved",
            payload={"progress_percent": view["progress_percent"]},
        )
    await _enqueue_pending_proof_copies(
        session,
        guild_id=guild_id,
        ticket_id=ticket.id,
        correlation_id=f"proof-confirmed:{proof.id}",
    )
    await _schedule_ticket_task(
        session,
        guild_id=guild_id,
        job_key="farm_tickets.meta.consume",
        resource_type="guild",
        resource_id=guild_id,
        payload={"reason": "proof_completed", "ticket_id": ticket.id},
        due_at=now,
        idempotency_key=f"proof:{proof.id}:resume-meta",
        correlation_id=f"proof-confirmed:{proof.id}",
        max_attempts=10,
        commit=False,
    )
    await session.commit()
    await session.refresh(ticket)
    return await ticket_dict(session, ticket)


async def list_proofs(
    session: AsyncSession, *, guild_id: str, ticket_id: str
) -> list[dict[str, Any]]:
    await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    rows = list(
        (
            await session.execute(
                select(FarmTicketProof)
                .where(FarmTicketProof.ticket_id == ticket_id)
                .order_by(FarmTicketProof.created_at, FarmTicketProof.id)
            )
        ).scalars()
    )
    return [
        {
            "id": item.id,
            "entry_revision_id": item.entry_revision_id,
            "received_at": _utc(item.received_at).isoformat(),
            "object_key": item.object_key,
            "checksum_sha256": item.checksum_sha256,
            "size_bytes": item.size_bytes,
            "content_type": item.content_type,
            "storage_state": item.storage_state.value,
            "thread_delivery_confirmed": item.thread_delivery_confirmed_at is not None,
        }
        for item in rows
    ]


async def mark_proof_thread_delivered(
    session: AsyncSession,
    *,
    guild_id: str,
    ticket_id: str,
    proof_id: str,
    external_message_id: str,
) -> dict[str, Any]:
    await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    proof = (
        await session.execute(
            select(FarmTicketProof)
            .where(
                FarmTicketProof.guild_id == guild_id,
                FarmTicketProof.ticket_id == ticket_id,
                FarmTicketProof.id == proof_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if proof is None:
        raise FarmTicketNotFound("Comprovante nao encontrado.")
    proof.thread_delivery_confirmed_at = proof.thread_delivery_confirmed_at or utc_now()
    proof.cleanup_error = None
    await session.commit()
    return {
        "proof_id": proof.id,
        "external_message_id": external_message_id,
        "thread_delivery_confirmed": True,
    }


async def list_discord_bindings(
    session: AsyncSession,
    *,
    guild_id: str,
    ticket_id: str | None = None,
) -> list[dict[str, Any]]:
    query = select(FarmTicketDiscordBinding).where(
        FarmTicketDiscordBinding.guild_id == guild_id
    )
    if ticket_id is not None:
        query = query.where(FarmTicketDiscordBinding.ticket_id == ticket_id)
    return [
        _binding_dict(item)
        for item in (
            await session.execute(
                query.order_by(
                    FarmTicketDiscordBinding.kind, FarmTicketDiscordBinding.created_at
                )
            )
        ).scalars()
    ]


async def upsert_discord_binding(
    session: AsyncSession,
    *,
    guild_id: str,
    ticket_id: str | None,
    kind: str,
    resource_id: str,
    parent_resource_id: str | None,
    ownership: str,
    idempotency_key: str,
) -> dict[str, Any]:
    try:
        resolved_kind = ResourceKind(kind)
        resolved_ownership = BindingOwnership(ownership)
    except ValueError as exc:
        raise FarmTicketError("Binding Discord invalido.") from exc
    if ticket_id is not None:
        await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    query = select(FarmTicketDiscordBinding).where(
        FarmTicketDiscordBinding.guild_id == guild_id,
        FarmTicketDiscordBinding.kind == resolved_kind,
    )
    if ticket_id is not None:
        query = query.where(FarmTicketDiscordBinding.ticket_id == ticket_id)
    elif resolved_kind == ResourceKind.CATEGORY:
        query = query.where(
            FarmTicketDiscordBinding.ticket_id.is_(None),
            FarmTicketDiscordBinding.resource_id == resource_id,
        )
    else:
        query = query.where(FarmTicketDiscordBinding.ticket_id.is_(None))
    binding = (await session.execute(query.with_for_update())).scalar_one_or_none()
    if binding is None and ticket_id is None and resolved_kind == ResourceKind.CATEGORY:
        binding = (
            await session.execute(
                select(FarmTicketDiscordBinding)
                .where(
                    FarmTicketDiscordBinding.guild_id == guild_id,
                    FarmTicketDiscordBinding.ticket_id.is_(None),
                    FarmTicketDiscordBinding.kind == ResourceKind.CATEGORY,
                    FarmTicketDiscordBinding.state == BindingState.MISSING,
                )
                .order_by(FarmTicketDiscordBinding.created_at)
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
    if binding is None:
        binding = FarmTicketDiscordBinding(
            ticket_id=ticket_id,
            guild_id=guild_id,
            kind=resolved_kind,
            resource_id=resource_id,
            parent_resource_id=parent_resource_id,
            ownership=resolved_ownership,
            state=BindingState.ACTIVE,
            applied_revision=1,
        )
        session.add(binding)
    else:
        if (
            binding.resource_id != resource_id
            and binding.ownership == BindingOwnership.ADOPTED
            and binding.state != BindingState.MISSING
        ):
            raise FarmTicketConflict("Recurso adotado ativo nao pode ser substituido.")
        if binding.resource_id != resource_id and binding.state == BindingState.MISSING:
            resolved_ownership = BindingOwnership.MANAGED
        binding.resource_id = resource_id
        binding.parent_resource_id = parent_resource_id
        binding.ownership = resolved_ownership
        binding.state = BindingState.ACTIVE
        binding.applied_revision = binding.desired_revision
        binding.last_error = None
        binding.deletion_intent_at = None
        binding.deletion_reason = None
    await session.flush()
    if ticket_id is not None and resolved_kind == ResourceKind.TICKET_THREAD:
        await _enqueue_pending_proof_copies(
            session,
            guild_id=guild_id,
            ticket_id=ticket_id,
            correlation_id=f"binding:{binding.id}:{idempotency_key}",
        )
        await _enqueue_pending_events(
            session,
            guild_id=guild_id,
            ticket_id=ticket_id,
            correlation_id=f"binding:{binding.id}:{idempotency_key}"[:80],
        )
    await session.commit()
    await session.refresh(binding)
    return _binding_dict(binding)


async def mark_discord_binding_deleted(
    session: AsyncSession, *, guild_id: str, binding_id: str
) -> dict[str, Any]:
    binding = (
        await session.execute(
            select(FarmTicketDiscordBinding)
            .where(
                FarmTicketDiscordBinding.guild_id == guild_id,
                FarmTicketDiscordBinding.id == binding_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if binding is None:
        raise FarmTicketNotFound("Binding Discord nao encontrado.")
    binding.state = BindingState.DELETED
    binding.last_error = None
    await session.commit()
    return _binding_dict(binding)


async def set_provisioning_error(
    session: AsyncSession, *, guild_id: str, ticket_id: str, error: str | None
) -> dict[str, Any]:
    ticket = await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    ticket.provisioning_error = error[:2000] if error else None
    await session.commit()
    return await ticket_dict(session, ticket)


async def withdraw(
    session: AsyncSession,
    *,
    guild_id: str,
    ticket_id: str,
    actor: ActorContextIn,
    expected_version: int,
    idempotency_key: str,
    values: Iterable[tuple[str, Decimal]],
) -> dict[str, Any]:
    existing = (
        await session.execute(
            select(FarmTicketWithdrawal).where(
                FarmTicketWithdrawal.guild_id == guild_id,
                FarmTicketWithdrawal.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        ticket = await _lock_ticket(
            session, guild_id=guild_id, ticket_id=existing.ticket_id
        )
        return await ticket_dict(session, ticket)
    ticket = await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    await _assert_expected(ticket, expected_version)
    if not ticket.withdrawals_open:
        raise FarmTicketConflict("Recolhimentos estao encerrados para este ticket.")
    await _assert_cycle_open(session, ticket=ticket, require_participant=False)
    active = await _active_operation(session, ticket_id=ticket.id, lock=True)
    if active is not None and active.kind == OperationKind.EDIT_ENTRY:
        raise FarmTicketConflict("Uma edicao esta aguardando comprovante neste ticket.")
    normalized = await _validate_values(session, ticket_id=ticket.id, values=values)
    _, _, available, _ = await _totals(session, ticket_id=ticket.id)
    for objective, amount in normalized:
        if amount > available[objective.id]:
            raise FarmTicketConflict(
                f"Recolhimento de {objective.name} excede o saldo disponivel."
            )
    number = (
        int(
            await session.scalar(
                select(func.coalesce(func.max(FarmTicketWithdrawal.number), 0)).where(
                    FarmTicketWithdrawal.ticket_id == ticket.id
                )
            )
            or 0
        )
        + 1
    )
    withdrawal = FarmTicketWithdrawal(
        ticket_id=ticket.id,
        guild_id=guild_id,
        number=number,
        actor_id=_actor_id(actor),
        idempotency_key=idempotency_key,
    )
    session.add(withdrawal)
    await session.flush()
    allocation_summaries: list[dict[str, Any]] = []
    for objective, amount in normalized:
        withdrawal_item = FarmTicketWithdrawalItem(
            withdrawal_id=withdrawal.id,
            ticket_id=ticket.id,
            objective_id=objective.id,
            amount=amount,
        )
        session.add(withdrawal_item)
        await session.flush()
        allocation_totals = (
            select(
                FarmTicketAllocation.entry_item_id.label("entry_item_id"),
                func.sum(FarmTicketAllocation.amount).label("allocated"),
            )
            .group_by(FarmTicketAllocation.entry_item_id)
            .subquery()
        )
        fifo_rows = await session.execute(
            select(
                FarmTicketEntryItem,
                FarmTicketEntry.number,
                func.coalesce(allocation_totals.c.allocated, 0),
            )
            .join(
                FarmTicketEntryRevision,
                FarmTicketEntryRevision.id == FarmTicketEntryItem.revision_id,
            )
            .join(FarmTicketEntry, FarmTicketEntry.id == FarmTicketEntryItem.entry_id)
            .outerjoin(
                allocation_totals,
                allocation_totals.c.entry_item_id == FarmTicketEntryItem.id,
            )
            .where(
                FarmTicketEntryItem.ticket_id == ticket.id,
                FarmTicketEntryItem.objective_id == objective.id,
                FarmTicketEntryRevision.status == EntryRevisionStatus.CURRENT,
            )
            .order_by(FarmTicketEntry.number, FarmTicketEntryItem.id)
            .with_for_update()
        )
        remaining = amount
        for entry_item, entry_number, allocated in fifo_rows:
            capacity = Decimal(entry_item.amount) - Decimal(allocated or 0)
            if capacity <= 0:
                continue
            allocated_now = min(capacity, remaining)
            session.add(
                FarmTicketAllocation(
                    ticket_id=ticket.id,
                    objective_id=objective.id,
                    withdrawal_item_id=withdrawal_item.id,
                    entry_item_id=entry_item.id,
                    amount=allocated_now,
                )
            )
            allocation_summaries.append(
                {
                    "objective_id": objective.id,
                    "entry_number": entry_number,
                    "amount": str(allocated_now),
                }
            )
            remaining -= allocated_now
            if remaining == 0:
                break
        if remaining != 0:
            raise FarmTicketConflict(
                "Saldo FIFO mudou durante o recolhimento; tente novamente."
            )
    ticket.revision += 1
    await session.flush()
    view = await ticket_dict(session, ticket)
    if ticket.status != TicketStatus.IN_PROGRESS and not any(
        Decimal(value) > 0 for value in view["available"].values()
    ):
        ticket.withdrawals_open = False
        ticket.settlement_closed_at = utc_now()
        if ticket.member_left_at is not None and ticket.binding_released_at is None:
            ticket.binding_released_at = utc_now()
            await _schedule_terminal_work(
                session,
                ticket=ticket,
                reason=ResourceRemovalReason.MEMBER_LEFT_CLEANUP,
                correlation_id=f"withdrawal:{withdrawal.id}:member-left-cleanup",
            )
    await _event(
        session,
        ticket=ticket,
        event_type="withdrawal.confirmed",
        actor_id=_actor_id(actor),
        deduplication_key=f"withdrawal:{guild_id}:{idempotency_key}",
        payload={
            "withdrawal_id": withdrawal.id,
            "number": number,
            "allocations": allocation_summaries,
        },
    )
    await session.commit()
    await session.refresh(ticket)
    return await ticket_dict(session, ticket)


async def _administrative_action(
    session: AsyncSession,
    *,
    guild_id: str,
    ticket_id: str,
    actor: ActorContextIn,
    expected_version: int,
    idempotency_key: str,
    action: str,
    status: TicketStatus,
    close_reason: TicketCloseReason,
) -> dict[str, Any]:
    ticket = await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    duplicate = await session.scalar(
        select(FarmTicketEvent.id).where(
            FarmTicketEvent.guild_id == guild_id,
            FarmTicketEvent.deduplication_key == f"admin:{action}:{idempotency_key}",
        )
    )
    if duplicate is not None:
        return await ticket_dict(session, ticket)
    await _assert_expected(ticket, expected_version)
    if ticket.status != TicketStatus.IN_PROGRESS:
        raise FarmTicketConflict("O resultado do ticket ja foi consolidado.")
    await _assert_cycle_open(session, ticket=ticket, require_participant=True)
    active = await _active_operation(session, ticket_id=ticket.id, lock=True)
    if active is not None:
        raise FarmTicketConflict(
            f"Acao bloqueada por operacao {active.status.value} ate "
            f"{_utc(active.proof_deadline).isoformat()}."
        )
    now = utc_now()
    ticket.status = status
    ticket.operations_closed_at = now
    ticket.result_finalized_at = now
    ticket.close_reason = close_reason
    ticket.revision += 1
    _, _, available, _ = await _totals(session, ticket_id=ticket.id)
    if not any(value > 0 for value in available.values()):
        ticket.withdrawals_open = False
        ticket.settlement_closed_at = now
    await _event(
        session,
        ticket=ticket,
        event_type=f"ticket.{action}",
        actor_id=_actor_id(actor),
        deduplication_key=f"admin:{action}:{idempotency_key}",
        payload={},
    )
    await session.commit()
    await session.refresh(ticket)
    return await ticket_dict(session, ticket)


async def approve_ticket(**kwargs: Any) -> dict[str, Any]:
    return await _administrative_action(
        **kwargs,
        action="approved_manually",
        status=TicketStatus.APPROVED,
        close_reason=TicketCloseReason.APPROVED,
    )


async def finalize_ticket(**kwargs: Any) -> dict[str, Any]:
    return await _administrative_action(
        **kwargs,
        action="finalized_incomplete",
        status=TicketStatus.FINALIZED_INCOMPLETE,
        close_reason=TicketCloseReason.MANUAL,
    )


async def assign_ticket(
    session: AsyncSession,
    *,
    guild_id: str,
    ticket_id: str,
    actor: ActorContextIn,
    expected_version: int,
    idempotency_key: str,
    administrator_id: str,
) -> dict[str, Any]:
    ticket = await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    duplicate = await session.scalar(
        select(FarmTicketEvent.id).where(
            FarmTicketEvent.guild_id == guild_id,
            FarmTicketEvent.deduplication_key == f"assign:{idempotency_key}",
        )
    )
    if duplicate is not None:
        return await ticket_dict(session, ticket)
    await _assert_expected(ticket, expected_version)
    if (
        ticket.status != TicketStatus.IN_PROGRESS
        or ticket.operations_closed_at is not None
    ):
        raise FarmTicketConflict("Ticket finalizado nao pode ser assumido.")
    await _assert_cycle_open(session, ticket=ticket, require_participant=True)
    previous = ticket.assigned_admin_id
    ticket.assigned_admin_id = administrator_id
    ticket.revision += 1
    await _event(
        session,
        ticket=ticket,
        event_type="ticket.assigned",
        actor_id=_actor_id(actor),
        deduplication_key=f"assign:{idempotency_key}",
        payload={"previous": previous, "current": administrator_id},
    )
    await session.commit()
    await session.refresh(ticket)
    return await ticket_dict(session, ticket)


async def delete_ticket(
    session: AsyncSession,
    *,
    guild_id: str,
    ticket_id: str,
    actor: ActorContextIn,
    expected_version: int,
    idempotency_key: str,
) -> dict[str, Any]:
    ticket = await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    duplicate = await session.scalar(
        select(FarmTicketEvent.id).where(
            FarmTicketEvent.guild_id == guild_id,
            FarmTicketEvent.deduplication_key == f"delete:{idempotency_key}",
        )
    )
    if duplicate is not None:
        return await ticket_dict(session, ticket)
    await _assert_expected(ticket, expected_version)
    active = await _active_operation(session, ticket_id=ticket.id, lock=True)
    if active is not None:
        raise FarmTicketConflict(
            f"Exclusao bloqueada por operacao {active.status.value}; ela nao sera cancelada."
        )
    _, _, available, _ = await _totals(session, ticket_id=ticket.id)
    if ticket.withdrawals_open and any(value > 0 for value in available.values()):
        raise FarmTicketConflict(
            "Existe saldo para recolher; a exclusao esta bloqueada."
        )
    now = utc_now()
    previous_status = ticket.status
    if ticket.status == TicketStatus.IN_PROGRESS:
        ticket.status = TicketStatus.CLOSED_MANUALLY
        ticket.result_finalized_at = now
        ticket.close_reason = TicketCloseReason.MANUAL
    ticket.operations_closed_at = ticket.operations_closed_at or now
    ticket.withdrawals_open = False
    ticket.settlement_closed_at = ticket.settlement_closed_at or now
    ticket.binding_released_at = ticket.binding_released_at or now
    ticket.last_resource_removal_reason = ResourceRemovalReason.MANUAL_DELETE
    ticket.revision += 1
    await _event(
        session,
        ticket=ticket,
        event_type="resource.manual_delete_requested",
        actor_id=_actor_id(actor),
        deduplication_key=f"delete:{idempotency_key}",
        payload={
            "historical_status_before": previous_status.value,
            "historical_status_after": ticket.status.value,
            "resource_reason": ResourceRemovalReason.MANUAL_DELETE.value,
        },
    )
    await _schedule_terminal_work(
        session,
        ticket=ticket,
        reason=ResourceRemovalReason.MANUAL_DELETE,
        correlation_id=f"ticket-delete:{idempotency_key}",
    )
    await session.commit()
    await session.refresh(ticket)
    return await ticket_dict(session, ticket)


async def _schedule_terminal_work(
    session: AsyncSession,
    *,
    ticket: FarmTicket,
    reason: ResourceRemovalReason,
    correlation_id: str,
) -> None:
    await _enqueue_pending_proof_copies(
        session,
        guild_id=ticket.guild_id,
        ticket_id=ticket.id,
        correlation_id=correlation_id,
    )
    now = utc_now()
    bindings = list(
        (
            await session.execute(
                select(FarmTicketDiscordBinding)
                .where(
                    FarmTicketDiscordBinding.guild_id == ticket.guild_id,
                    FarmTicketDiscordBinding.ticket_id == ticket.id,
                    FarmTicketDiscordBinding.ownership == BindingOwnership.MANAGED,
                    FarmTicketDiscordBinding.kind.in_(
                        [ResourceKind.TICKET_CHANNEL, ResourceKind.TICKET_PANEL_MESSAGE]
                    ),
                    FarmTicketDiscordBinding.state != BindingState.DELETED,
                )
                .with_for_update()
            )
        ).scalars()
    )
    for binding in bindings:
        binding.deletion_intent_at = binding.deletion_intent_at or now
        binding.deletion_reason = reason
        binding.state = BindingState.DELETE_PENDING
    for job_key, resource_type in (
        ("farm_tickets.provision", "farm_ticket"),
        ("farm_tickets.storage.cleanup", "farm_ticket"),
    ):
        await _schedule_ticket_task(
            session,
            guild_id=ticket.guild_id,
            job_key=job_key,
            resource_type=resource_type,
            resource_id=ticket.id,
            payload={
                "ticket_id": ticket.id,
                "action": "terminal_cleanup",
                "reason": reason.value,
            },
            due_at=now,
            idempotency_key=f"ticket:{ticket.id}:{job_key}:terminal:{reason.value}",
            correlation_id=correlation_id,
            max_attempts=10,
            commit=False,
        )


async def ticket_cleanup_state(
    session: AsyncSession, *, guild_id: str, ticket_id: str
) -> dict[str, Any]:
    ticket = await _lock_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    undelivered = int(
        await session.scalar(
            select(func.count(FarmTicketProof.id)).where(
                FarmTicketProof.guild_id == guild_id,
                FarmTicketProof.ticket_id == ticket_id,
                FarmTicketProof.thread_delivery_confirmed_at.is_(None),
            )
        )
        or 0
    )
    return {
        "ticket_id": ticket.id,
        "binding_released": ticket.binding_released_at is not None,
        "proofs_waiting_for_thread": undelivered,
        "ready": ticket.binding_released_at is not None and undelivered == 0,
    }


async def freeze_and_close_for_cycle(
    session: AsyncSession,
    *,
    ticket: FarmTicket,
    reason: TicketCloseReason,
    meta_event_id: str,
    effective_at: datetime,
) -> bool:
    cycle_snapshot = (
        await session.execute(
            select(FarmTicketCycle)
            .where(FarmTicketCycle.ticket_id == ticket.id)
            .with_for_update()
        )
    ).scalar_one()
    effective = _utc(effective_at)
    if cycle_snapshot.participation_ended_at is None or effective < _utc(
        cycle_snapshot.participation_ended_at
    ):
        cycle_snapshot.participation_ended_at = effective
    active = await _active_operation(session, ticket_id=ticket.id, lock=True)
    if active is not None:
        if active.status in CLAIMED_OPERATION_STATUSES:
            return False
        active.status = OperationStatus.EXPIRED
        active.completed_at = effective_at
        revision = await session.get(
            FarmTicketEntryRevision, active.pending_revision_id
        )
        if revision is not None:
            revision.status = EntryRevisionStatus.REJECTED
    launched, withdrawn, available, objectives = await _totals(
        session, ticket_id=ticket.id
    )
    now = effective
    if ticket.status == TicketStatus.IN_PROGRESS:
        ticket.status = TicketStatus.FINALIZED_INCOMPLETE
        ticket.result_finalized_at = now
    ticket.close_reason = reason
    ticket.operations_closed_at = ticket.operations_closed_at or now
    ticket.withdrawals_open = False
    ticket.settlement_closed_at = ticket.settlement_closed_at or now
    ticket.binding_released_at = ticket.binding_released_at or now
    ticket.frozen_launched_total = sum(launched.values(), Decimal("0"))
    ticket.frozen_withdrawn_total = sum(withdrawn.values(), Decimal("0"))
    ticket.frozen_unwithdrawn_total = sum(available.values(), Decimal("0"))
    ticket.frozen_totals = {
        item.id: {
            "name": item.name,
            "launched": str(launched[item.id]),
            "withdrawn": str(withdrawn[item.id]),
            "unwithdrawn": str(available[item.id]),
        }
        for item in objectives
    }
    ticket.revision += 1
    await _event(
        session,
        ticket=ticket,
        event_type="ticket.cycle_closed",
        actor_id="Yuno",
        deduplication_key=f"meta:{meta_event_id}:ticket:{ticket.id}",
        payload={
            "reason": reason.value,
            "status": ticket.status.value,
            "totals": ticket.frozen_totals,
        },
    )
    cleanup_reason = (
        ResourceRemovalReason.NEW_GOAL_CLEANUP
        if reason == TicketCloseReason.NEW_GOAL
        else ResourceRemovalReason.CYCLE_CLEANUP
    )
    await _schedule_terminal_work(
        session,
        ticket=ticket,
        reason=cleanup_reason,
        correlation_id=f"meta:{meta_event_id}:ticket:{ticket.id}",
    )
    return True


async def _apply_meta_event(
    session: AsyncSession, *, guild_id: str, event: meta_contracts.GoalEvent
) -> bool:
    payload = event.payload
    if event.event_type == EVENT_CYCLE_STARTED:
        return True
    member_id = str(payload.get("member_id", ""))
    cycle_id = int(
        payload.get(
            "source_cycle_id"
            if event.event_type == EVENT_PARTICIPANT_MOVED
            else "cycle_id",
            0,
        )
        or 0
    )
    query = select(FarmTicket).where(FarmTicket.guild_id == guild_id)
    if event.event_type == EVENT_CYCLE_ENDED:
        query = query.where(FarmTicket.meta_cycle_id == cycle_id)
        reason = TicketCloseReason.CYCLE_ENDED
    elif event.event_type in {EVENT_PARTICIPANT_REMOVED, EVENT_PARTICIPANT_MOVED}:
        query = query.where(
            FarmTicket.meta_cycle_id == cycle_id,
            FarmTicket.member_id == member_id,
            FarmTicket.binding_released_at.is_(None),
        )
        moved = (
            payload.get("reason") == "moved_to_another_goal"
            or event.event_type == EVENT_PARTICIPANT_MOVED
        )
        reason = TicketCloseReason.NEW_GOAL if moved else TicketCloseReason.LEFT_GUILD
    else:
        return True
    tickets = list((await session.execute(query.with_for_update())).scalars())
    effective = _utc(event.occurred_at)
    claimed_proof_in_flight = False
    # Preflight de todo o lote: registra o fim efetivo da janela antes de
    # permitir que o processador confirme a prova e evita aplicar um evento
    # parcialmente quando outro ticket ainda esta processando prova tempestiva.
    for ticket in tickets:
        cycle_snapshot = (
            await session.execute(
                select(FarmTicketCycle)
                .where(FarmTicketCycle.ticket_id == ticket.id)
                .with_for_update()
            )
        ).scalar_one()
        if cycle_snapshot.participation_ended_at is None or effective < _utc(
            cycle_snapshot.participation_ended_at
        ):
            cycle_snapshot.participation_ended_at = effective
        active = await _active_operation(session, ticket_id=ticket.id, lock=True)
        if active is not None and active.status in CLAIMED_OPERATION_STATUSES:
            claimed_proof_in_flight = True
    if claimed_proof_in_flight:
        return False
    for ticket in tickets:
        if reason == TicketCloseReason.LEFT_GUILD:
            active = await _active_operation(session, ticket_id=ticket.id, lock=True)
            if active is not None:
                active.status = OperationStatus.EXPIRED
                active.completed_at = effective
                revision = await session.get(
                    FarmTicketEntryRevision, active.pending_revision_id
                )
                if revision is not None:
                    revision.status = EntryRevisionStatus.REJECTED
            _, _, available, _ = await _totals(session, ticket_id=ticket.id)
            now = effective
            ticket.member_left_at = now
            ticket.operations_closed_at = ticket.operations_closed_at or now
            if not any(value > 0 for value in available.values()):
                if ticket.status == TicketStatus.IN_PROGRESS:
                    ticket.status = TicketStatus.FINALIZED_INCOMPLETE
                    ticket.result_finalized_at = now
                ticket.close_reason = TicketCloseReason.LEFT_GUILD
                ticket.withdrawals_open = False
                ticket.settlement_closed_at = now
                ticket.binding_released_at = now
                await _schedule_terminal_work(
                    session,
                    ticket=ticket,
                    reason=ResourceRemovalReason.MEMBER_LEFT_CLEANUP,
                    correlation_id=f"meta:{event.event_id}:member-left-cleanup",
                )
            ticket.revision += 1
            await _event(
                session,
                ticket=ticket,
                event_type="ticket.member_left",
                actor_id="Yuno",
                deduplication_key=f"meta:{event.event_id}:ticket:{ticket.id}",
                payload={
                    "available_balance": any(value > 0 for value in available.values())
                },
            )
        else:
            closed = await freeze_and_close_for_cycle(
                session,
                ticket=ticket,
                reason=reason,
                meta_event_id=event.event_id,
                effective_at=_utc(event.occurred_at),
            )
            if not closed:
                return False
    return True


async def consume_meta_events(
    session: AsyncSession, *, guild_id: str, limit: int = 100
) -> dict[str, Any]:
    cursor = (
        await session.execute(
            select(FarmTicketMetaCursor)
            .where(FarmTicketMetaCursor.guild_id == guild_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if cursor is None:
        cursor = FarmTicketMetaCursor(guild_id=guild_id)
        session.add(cursor)
        await session.flush()
    page = await meta_contracts.read_goal_events(
        session,
        guild_id=guild_id,
        after_sequence=cursor.last_sequence,
        event_types=META_EVENT_TYPES,
        limit=limit,
    )
    processed = 0
    blocked: dict[str, Any] | None = None
    for event in page.events:
        receipt = await session.scalar(
            select(FarmTicketMetaReceipt.id).where(
                FarmTicketMetaReceipt.guild_id == guild_id,
                FarmTicketMetaReceipt.event_id == event.event_id,
            )
        )
        if receipt is None:
            if not await _apply_meta_event(session, guild_id=guild_id, event=event):
                blocked = {
                    "event_id": event.event_id,
                    "sequence": event.sequence,
                    "reason": "timely_proof_processing",
                }
                break
            session.add(
                FarmTicketMetaReceipt(
                    guild_id=guild_id,
                    event_id=event.event_id,
                    sequence=event.sequence,
                    event_type=event.event_type,
                )
            )
        cursor.last_sequence = event.sequence
        processed += 1
    cursor.bootstrap_complete = blocked is None and not page.has_more
    await session.commit()
    return {
        "processed": processed,
        "last_sequence": cursor.last_sequence,
        "has_more": page.has_more or blocked is not None,
        "blocked": blocked,
        "bootstrap_complete": cursor.bootstrap_complete,
    }


async def record_external_resource_deletion(
    session: AsyncSession,
    *,
    guild_id: str,
    resource_id: str,
    observed_at: datetime,
) -> dict[str, Any]:
    binding = (
        await session.execute(
            select(FarmTicketDiscordBinding)
            .where(
                FarmTicketDiscordBinding.guild_id == guild_id,
                FarmTicketDiscordBinding.resource_id == resource_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if binding is None:
        return {"known": False, "action": "ignore"}
    if binding.deletion_intent_at is not None or binding.state in {
        BindingState.DELETE_PENDING,
        BindingState.DELETED,
    }:
        binding.state = BindingState.DELETED
        binding.last_error = None
        await session.commit()
        return {
            "known": True,
            "action": "planned_delete",
            "ticket_status": (
                (await session.get(FarmTicket, binding.ticket_id)).status.value
                if binding.ticket_id is not None
                else None
            ),
        }
    binding.state = BindingState.MISSING
    binding.last_error = "Recurso removido externamente."
    if binding.ticket_id is None:
        await session.commit()
        return {"known": True, "action": "recover"}
    ticket = await _lock_ticket(session, guild_id=guild_id, ticket_id=binding.ticket_id)
    _, _, available, _ = await _totals(session, ticket_id=ticket.id)
    actions_remaining = ticket.status == TicketStatus.IN_PROGRESS or (
        ticket.withdrawals_open and any(value > 0 for value in available.values())
    )
    if actions_remaining:
        await _event(
            session,
            ticket=ticket,
            event_type="resource.external_delete_detected",
            actor_id=None,
            deduplication_key=f"resource:{resource_id}:missing:{_utc(observed_at).isoformat()}",
            payload={"kind": binding.kind.value, "recovery_required": True},
        )
        action = "recover"
    else:
        binding.state = BindingState.DELETED
        binding.deletion_reason = ResourceRemovalReason.MANUAL_DELETE
        ticket.last_resource_removal_reason = ResourceRemovalReason.MANUAL_DELETE
        ticket.revision += 1
        await _event(
            session,
            ticket=ticket,
            event_type="resource.manual_delete_observed",
            actor_id=None,
            deduplication_key=f"resource:{resource_id}:deleted:{_utc(observed_at).isoformat()}",
            payload={
                "historical_status": ticket.status.value,
                "resource_reason": "MANUAL_DELETE",
            },
        )
        action = "accept_removed"
    if action == "recover":
        job_key = (
            "farm_tickets.provision" if binding.ticket_id else "farm_tickets.reconcile"
        )
        resource_type = "farm_ticket" if binding.ticket_id else "guild"
        resource_id_for_job = binding.ticket_id or guild_id
        await _schedule_ticket_task(
            session,
            guild_id=guild_id,
            job_key=job_key,
            resource_type=resource_type,
            resource_id=resource_id_for_job,
            payload={
                "ticket_id": binding.ticket_id,
                "reason": "resource_deleted",
                "binding_id": binding.id,
            },
            due_at=utc_now(),
            idempotency_key=f"resource:{binding.id}:recover:{_utc(observed_at).isoformat()}",
            correlation_id=f"resource-delete:{binding.id}",
            max_attempts=10,
            commit=False,
        )
    await session.commit()
    return {"known": True, "action": action, "ticket_status": ticket.status.value}


async def diagnose(session: AsyncSession, *, guild_id: str) -> dict[str, Any]:
    cursor = await session.get(FarmTicketMetaCursor, guild_id)
    active_tickets = int(
        await session.scalar(
            select(func.count(FarmTicket.id)).where(
                FarmTicket.guild_id == guild_id,
                FarmTicket.binding_released_at.is_(None),
            )
        )
        or 0
    )
    active_operations = int(
        await session.scalar(
            select(func.count(FarmTicketPendingOperation.id)).where(
                FarmTicketPendingOperation.guild_id == guild_id,
                FarmTicketPendingOperation.status.in_(list(ACTIVE_OPERATION_STATUSES)),
            )
        )
        or 0
    )
    retrying_proofs = int(
        await session.scalar(
            select(func.count(FarmTicketPendingOperation.id)).where(
                FarmTicketPendingOperation.guild_id == guild_id,
                FarmTicketPendingOperation.status == OperationStatus.RETRYING_PROOF,
            )
        )
        or 0
    )
    missing_resources = int(
        await session.scalar(
            select(func.count(FarmTicketDiscordBinding.id)).where(
                FarmTicketDiscordBinding.guild_id == guild_id,
                FarmTicketDiscordBinding.state == BindingState.MISSING,
            )
        )
        or 0
    )
    return {
        "guild_id": guild_id,
        "active_tickets": active_tickets,
        "active_operations": active_operations,
        "retrying_proofs": retrying_proofs,
        "missing_resources": missing_resources,
        "meta_cursor": cursor.last_sequence if cursor else 0,
        "meta_bootstrap_complete": cursor.bootstrap_complete if cursor else False,
    }


async def request_reconciliation(
    session: AsyncSession,
    *,
    guild_id: str,
    actor_id: str,
    idempotency_key: str,
    correlation_id: str,
) -> dict[str, Any]:
    task = await schedule_task(
        session,
        guild_id=guild_id,
        module_key="farm_tickets",
        job_key="farm_tickets.reconcile",
        resource_type="guild",
        resource_id=guild_id,
        payload={"reason": "manual_diagnostic", "requested_by": actor_id},
        due_at=utc_now(),
        idempotency_key=f"farm-tickets:reconcile:{idempotency_key}",
        correlation_id=correlation_id,
        max_attempts=None,
        commit=True,
    )
    return {"task_id": task.id, "state": task.state.value}
