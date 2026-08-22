from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
try:
    from enum import StrEnum
except ImportError:  # Python 3.10 do ambiente de teste
    from enum import Enum

    class StrEnum(str, Enum):
        pass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class MetaDomainError(ValueError):
    pass


class GoalState(StrEnum):
    scheduled = "scheduled"
    launch_pending = "launch_pending"
    active = "active"
    action_required = "action_required"
    ended = "ended"


class CycleState(StrEnum):
    launch_pending = "launch_pending"
    active = "active"
    ended = "ended"


class RecurrenceKind(StrEnum):
    custom = "custom"
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


class ParticipationKind(StrEnum):
    all_members = "all_members"
    roles = "roles"


class ObjectiveKind(StrEnum):
    item = "item"
    money = "money"


class GoalEndReason(StrEnum):
    completed = "completed"
    replaced = "replaced"
    cancelled = "cancelled"


class ParticipantRemovalReason(StrEnum):
    left_guild = "left_guild"
    moved_to_another_goal = "moved_to_another_goal"


EVENT_GOAL_CYCLE_STARTED = "meta.goal_cycle_started.v1"
EVENT_GOAL_CYCLE_ENDED = "meta.goal_cycle_ended.v1"
EVENT_PARTICIPANT_REMOVED = "meta.participant_removed_from_cycle.v1"
EVENT_PARTICIPANT_MOVED = "meta.participant_moved_to_another_goal.v1"
EVENT_TYPES = (
    EVENT_GOAL_CYCLE_STARTED,
    EVENT_GOAL_CYCLE_ENDED,
    EVENT_PARTICIPANT_REMOVED,
    EVENT_PARTICIPANT_MOVED,
)


def normalize_decimal(value: Decimal | int | str, *, places: int) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise MetaDomainError("Valor decimal invalido.") from exc
    if not result.is_finite() or result <= 0:
        raise MetaDomainError("O valor deve ser positivo.")
    quantum = Decimal(1).scaleb(-places)
    normalized = result.quantize(quantum)
    if normalized != result:
        raise MetaDomainError(f"O valor aceita no maximo {places} casas decimais.")
    return normalized


def normalize_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise MetaDomainError("Timezone IANA invalido.") from exc
    return value


def parse_clock(value: str) -> time:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise MetaDomainError("Horario deve usar HH:MM.") from exc
    if parsed.tzinfo is not None or parsed.second or parsed.microsecond:
        raise MetaDomainError("Horario deve usar HH:MM.")
    return parsed


def _valid_local(naive: datetime, zone: ZoneInfo, *, fold: int) -> datetime | None:
    aware = naive.replace(tzinfo=zone, fold=fold)
    roundtrip = aware.astimezone(timezone.utc).astimezone(zone)
    if roundtrip.replace(tzinfo=None) != naive or roundtrip.fold != fold:
        return None
    return aware


def resolve_local(naive: datetime, timezone_name: str) -> datetime:
    """Resolve horario civil: ambiguo usa fold 0; inexistente avanca ao primeiro valido."""

    zone = ZoneInfo(normalize_timezone(timezone_name))
    first = _valid_local(naive, zone, fold=0)
    if first is not None:
        return first
    second = _valid_local(naive, zone, fold=1)
    if second is not None:
        return second
    candidate = naive
    for _ in range(180):
        candidate += timedelta(minutes=1)
        resolved = _valid_local(candidate, zone, fold=0)
        if resolved is not None:
            return resolved
    raise MetaDomainError("Nao foi possivel resolver o horario local no timezone informado.")


def _month_candidate(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, monthrange(year, month)[1]))


def next_boundary(
    *,
    recurrence: RecurrenceKind,
    after: datetime,
    timezone_name: str,
    daily_time: str | None = None,
    weekday: int | None = None,
    month_day: int | None = None,
) -> datetime:
    if after.tzinfo is None:
        raise MetaDomainError("A referencia temporal precisa incluir timezone.")
    zone = ZoneInfo(normalize_timezone(timezone_name))
    local_after = after.astimezone(zone)
    if recurrence == RecurrenceKind.custom:
        raise MetaDomainError("Meta personalizada nao possui proxima fronteira recorrente.")
    if recurrence == RecurrenceKind.daily:
        clock = parse_clock(daily_time or "00:00")
        candidate_date = local_after.date()
        candidate = resolve_local(datetime.combine(candidate_date, clock), timezone_name)
        if candidate <= local_after:
            candidate = resolve_local(datetime.combine(candidate_date + timedelta(days=1), clock), timezone_name)
        return candidate.astimezone(timezone.utc)
    if recurrence == RecurrenceKind.weekly:
        if weekday is None or weekday < 0 or weekday > 6:
            raise MetaDomainError("Dia semanal deve estar entre 0 e 6.")
        delta = (weekday - local_after.weekday()) % 7
        candidate_date = local_after.date() + timedelta(days=delta)
        candidate = resolve_local(datetime.combine(candidate_date, time.min), timezone_name)
        if candidate <= local_after:
            candidate = resolve_local(
                datetime.combine(candidate_date + timedelta(days=7), time.min), timezone_name
            )
        return candidate.astimezone(timezone.utc)
    if month_day is None or month_day < 1 or month_day > 31:
        raise MetaDomainError("Dia mensal deve estar entre 1 e 31.")
    candidate_date = _month_candidate(local_after.year, local_after.month, month_day)
    candidate = resolve_local(datetime.combine(candidate_date, time.min), timezone_name)
    if candidate <= local_after:
        year = local_after.year + (1 if local_after.month == 12 else 0)
        month = 1 if local_after.month == 12 else local_after.month + 1
        candidate_date = _month_candidate(year, month, month_day)
        candidate = resolve_local(datetime.combine(candidate_date, time.min), timezone_name)
    return candidate.astimezone(timezone.utc)


@dataclass(frozen=True)
class EligibleMember:
    member_id: str
    display_name: str
    role_ids: tuple[str, ...]


def eligible_members(
    members: tuple[EligibleMember, ...],
    *,
    participation: ParticipationKind,
    role_ids: tuple[str, ...],
) -> tuple[EligibleMember, ...]:
    if participation == ParticipationKind.all_members:
        return members
    allowed = set(role_ids)
    return tuple(member for member in members if allowed.intersection(member.role_ids))
