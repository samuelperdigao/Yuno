from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Iterable, Mapping
import unicodedata


class FarmDomainError(ValueError):
    pass


class ProductStatus(StrEnum):
    active = "active"
    archived = "archived"


class TemplateStatus(StrEnum):
    draft = "draft"
    active = "active"
    archived = "archived"


class CycleStatus(StrEnum):
    draft = "draft"
    scheduled = "scheduled"
    active = "active"
    closing = "closing"
    closed = "closed"
    cancelled = "cancelled"


class ParticipationMode(StrEnum):
    opt_in = "opt_in"
    assigned = "assigned"


class TicketStatus(StrEnum):
    open = "open"
    completed = "completed"
    closed = "closed"
    cancelled = "cancelled"


class SubmissionStatus(StrEnum):
    submitted = "submitted"
    under_review = "under_review"
    approved = "approved"
    correction_requested = "correction_requested"
    rejected = "rejected"


class ReviewDecision(StrEnum):
    approved = "approved"
    correction_requested = "correction_requested"
    rejected = "rejected"


PRODUCT_TRANSITIONS = {ProductStatus.active: {ProductStatus.archived}}
TEMPLATE_TRANSITIONS = {
    TemplateStatus.draft: {TemplateStatus.active, TemplateStatus.archived},
    TemplateStatus.active: {TemplateStatus.archived},
}
CYCLE_TRANSITIONS = {
    CycleStatus.draft: {CycleStatus.scheduled, CycleStatus.cancelled},
    CycleStatus.scheduled: {CycleStatus.draft, CycleStatus.active, CycleStatus.cancelled},
    CycleStatus.active: {CycleStatus.closing, CycleStatus.cancelled},
    CycleStatus.closing: {CycleStatus.closed, CycleStatus.cancelled},
}
TICKET_TRANSITIONS = {
    TicketStatus.open: {TicketStatus.completed, TicketStatus.closed, TicketStatus.cancelled},
    TicketStatus.completed: {TicketStatus.open, TicketStatus.closed, TicketStatus.cancelled},
}
SUBMISSION_TRANSITIONS = {
    SubmissionStatus.submitted: {
        SubmissionStatus.under_review,
        SubmissionStatus.approved,
        SubmissionStatus.correction_requested,
        SubmissionStatus.rejected,
    },
    SubmissionStatus.under_review: {
        SubmissionStatus.submitted,
        SubmissionStatus.approved,
        SubmissionStatus.correction_requested,
        SubmissionStatus.rejected,
    },
}


def ensure_transition(current: StrEnum, target: StrEnum, transitions: Mapping[StrEnum, set[StrEnum]]) -> None:
    if target not in transitions.get(current, set()):
        raise FarmDomainError(f"Transicao de {current.value} para {target.value} nao permitida.")


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.strip().split()).casefold()


def normalize_quantity(value: Decimal | int | str, precision: int) -> Decimal:
    if precision < 0 or precision > 3:
        raise FarmDomainError("Precisao deve estar entre 0 e 3.")
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise FarmDomainError("Quantidade invalida.") from exc
    if not quantity.is_finite() or quantity <= 0:
        raise FarmDomainError("Quantidade deve ser positiva.")
    quantum = Decimal(1).scaleb(-precision)
    normalized = quantity.quantize(quantum)
    if normalized != quantity:
        raise FarmDomainError(f"Quantidade excede a precisao de {precision} casas.")
    return normalized


@dataclass(frozen=True)
class ItemProgress:
    required: Decimal
    approved: Decimal
    percent: Decimal


@dataclass(frozen=True)
class ProgressSnapshot:
    items: dict[int, ItemProgress]
    percent: Decimal
    completed: bool


def calculate_progress(
    goals: Mapping[int, Decimal],
    approved_items: Iterable[tuple[int, Decimal]],
) -> ProgressSnapshot:
    totals = {goal_id: Decimal("0") for goal_id in goals}
    for goal_id, quantity in approved_items:
        if goal_id in totals:
            totals[goal_id] += quantity

    items: dict[int, ItemProgress] = {}
    capped: list[Decimal] = []
    for goal_id, required in goals.items():
        if required <= 0:
            raise FarmDomainError("Meta deve ser positiva.")
        approved = totals[goal_id]
        percent = (approved / required * Decimal("100")).quantize(Decimal("0.01"))
        items[goal_id] = ItemProgress(required=required, approved=approved, percent=percent)
        capped.append(min(percent, Decimal("100")))

    overall = (
        (sum(capped, Decimal("0")) / Decimal(len(capped))).quantize(Decimal("0.01"))
        if capped
        else Decimal("0")
    )
    return ProgressSnapshot(
        items=items,
        percent=overall,
        completed=bool(items) and all(item.approved >= item.required for item in items.values()),
    )
