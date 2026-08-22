from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

try:
    from enum import StrEnum
except ImportError:  # Python 3.10 do ambiente de teste
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        pass


class FarmTicketError(ValueError):
    code = "farm_ticket_error"


class FarmTicketConflict(FarmTicketError):
    code = "farm_ticket_conflict"


class ProofNoLongerEligible(FarmTicketConflict):
    """A prova chegou depois do encerramento efetivo da participacao."""

    code = "farm_ticket_proof_ineligible"


class FarmTicketNotFound(FarmTicketError):
    code = "farm_ticket_not_found"


class FarmTicketPermissionDenied(FarmTicketError):
    code = "farm_ticket_permission_denied"


class TicketStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    APPROVED = "APPROVED"
    FINALIZED_INCOMPLETE = "FINALIZED_INCOMPLETE"
    CLOSED_MANUALLY = "CLOSED_MANUALLY"


class OperationStatus(StrEnum):
    AWAITING_PROOF = "AWAITING_PROOF"
    PROOF_CLAIMED = "PROOF_CLAIMED"
    PROCESSING_PROOF = "PROCESSING_PROOF"
    RETRYING_PROOF = "RETRYING_PROOF"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


ACTIVE_OPERATION_STATUSES = frozenset(
    {
        OperationStatus.AWAITING_PROOF,
        OperationStatus.PROOF_CLAIMED,
        OperationStatus.PROCESSING_PROOF,
        OperationStatus.RETRYING_PROOF,
    }
)

CLAIMED_OPERATION_STATUSES = frozenset(
    {
        OperationStatus.PROOF_CLAIMED,
        OperationStatus.PROCESSING_PROOF,
        OperationStatus.RETRYING_PROOF,
    }
)


class OperationKind(StrEnum):
    CREATE_ENTRY = "CREATE_ENTRY"
    EDIT_ENTRY = "EDIT_ENTRY"


class FormKind(StrEnum):
    CREATE_ENTRY = "CREATE_ENTRY"
    EDIT_ENTRY = "EDIT_ENTRY"
    WITHDRAWAL = "WITHDRAWAL"


class ObjectiveKind(StrEnum):
    ITEM = "item"
    MONEY = "money"


class EntryRevisionStatus(StrEnum):
    PENDING = "PENDING"
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class TicketCloseReason(StrEnum):
    APPROVED = "APPROVED"
    MANUAL = "MANUAL"
    CYCLE_ENDED = "CYCLE_ENDED"
    NEW_GOAL = "NEW_GOAL"
    LEFT_GUILD = "LEFT_GUILD"


class ResourceRemovalReason(StrEnum):
    MANUAL_DELETE = "MANUAL_DELETE"
    CYCLE_CLEANUP = "CYCLE_CLEANUP"
    NEW_GOAL_CLEANUP = "NEW_GOAL_CLEANUP"
    MEMBER_LEFT_CLEANUP = "MEMBER_LEFT_CLEANUP"
    RECONCILIATION = "RECONCILIATION"


class BindingOwnership(StrEnum):
    ADOPTED = "ADOPTED"
    MANAGED = "MANAGED"


class BindingState(StrEnum):
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    MISSING = "MISSING"
    DELETE_PENDING = "DELETE_PENDING"
    DELETED = "DELETED"


class ResourceKind(StrEnum):
    CATEGORY = "CATEGORY"
    GLOBAL_PANEL_CHANNEL = "GLOBAL_PANEL_CHANNEL"
    GLOBAL_PANEL_MESSAGE = "GLOBAL_PANEL_MESSAGE"
    LOG_CHANNEL = "LOG_CHANNEL"
    TICKET_CHANNEL = "TICKET_CHANNEL"
    TICKET_PANEL_MESSAGE = "TICKET_PANEL_MESSAGE"
    TICKET_MAIN_MESSAGE = "TICKET_MAIN_MESSAGE"
    TICKET_THREAD = "TICKET_THREAD"


class ProofStorageState(StrEnum):
    PENDING = "PENDING"
    STORED = "STORED"
    DELETE_PENDING = "DELETE_PENDING"
    RETAINED = "RETAINED"
    DELETED = "DELETED"


class ProofCandidateStatus(StrEnum):
    CLAIMED = "CLAIMED"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"


ZERO = Decimal("0")
ITEM_QUANTUM = Decimal("0.001")
MONEY_QUANTUM = Decimal("0.01")
PERCENT_QUANTUM = Decimal("0.01")


def decimal_amount(value: object, *, money: bool = False) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FarmTicketError("Valor numerico invalido.") from exc
    if not amount.is_finite() or amount <= ZERO:
        raise FarmTicketError("O valor deve ser maior que zero.")
    return amount.quantize(
        MONEY_QUANTUM if money else ITEM_QUANTUM, rounding=ROUND_HALF_UP
    )


@dataclass(frozen=True)
class ObjectiveProgress:
    objective_id: str
    launched: Decimal
    target: Decimal
    percent: Decimal


@dataclass(frozen=True)
class TicketProgress:
    percent: Decimal
    objectives: tuple[ObjectiveProgress, ...]


def calculate_progress(
    objectives: list[tuple[str, Decimal, Decimal]],
) -> TicketProgress:
    """Media dos objetivos, limitada em 100%, sem truncar os totais reais."""
    if not objectives:
        return TicketProgress(percent=ZERO, objectives=())
    rows: list[ObjectiveProgress] = []
    capped_total = ZERO
    for objective_id, launched, target in objectives:
        if target <= ZERO:
            raise FarmTicketError("Objetivo congelado deve ser maior que zero.")
        real_percent = (launched / target * Decimal("100")).quantize(
            PERCENT_QUANTUM, rounding=ROUND_HALF_UP
        )
        rows.append(
            ObjectiveProgress(
                objective_id=objective_id,
                launched=launched,
                target=target,
                percent=real_percent,
            )
        )
        capped_total += min(real_percent, Decimal("100"))
    average = (capped_total / Decimal(len(rows))).quantize(
        PERCENT_QUANTUM, rounding=ROUND_HALF_UP
    )
    return TicketProgress(
        percent=min(average, Decimal("100.00")), objectives=tuple(rows)
    )
