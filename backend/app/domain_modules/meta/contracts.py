from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain_modules.meta.domain import ObjectiveKind
from app.domain_modules.meta.models import (
    MetaCycle,
    MetaCycleObjective,
    MetaCycleParticipant,
    MetaGoal,
    MetaIntegrationEvent,
)


@dataclass(frozen=True)
class GoalObjectiveSnapshot:
    objective_id: int
    kind: ObjectiveKind
    name: str
    unit: str | None
    item_quantity: str | None
    money_amount: str | None
    position: int


@dataclass(frozen=True)
class GoalCycleSnapshot:
    cycle_id: int
    goal_id: int
    guild_id: str
    name: str
    state: str
    starts_at: datetime
    ends_at: datetime
    timezone: str
    config_version_id: int


@dataclass(frozen=True)
class ActiveGoalForMember:
    goal_id: int
    cycle: GoalCycleSnapshot
    objectives: tuple[GoalObjectiveSnapshot, ...]


@dataclass(frozen=True)
class GoalEvent:
    event_id: str
    sequence: int
    event_type: str
    event_version: int
    occurred_at: datetime
    causation_id: str
    deduplication_key: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class GoalEventPage:
    events: tuple[GoalEvent, ...]
    next_sequence: int
    has_more: bool


def _objective(item: MetaCycleObjective) -> GoalObjectiveSnapshot:
    return GoalObjectiveSnapshot(
        objective_id=item.id,
        kind=item.kind,
        name=item.name,
        unit=item.unit,
        item_quantity=str(item.item_quantity) if item.item_quantity is not None else None,
        money_amount=str(item.money_amount) if item.money_amount is not None else None,
        position=item.position,
    )


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


async def get_cycle(
    session: AsyncSession, *, guild_id: str, cycle_id: int
) -> GoalCycleSnapshot | None:
    row = (
        await session.execute(
            select(MetaCycle, MetaGoal)
            .join(MetaGoal, MetaGoal.id == MetaCycle.goal_id)
            .where(MetaCycle.guild_id == guild_id, MetaCycle.id == cycle_id)
        )
    ).first()
    if row is None:
        return None
    cycle, goal = row
    return GoalCycleSnapshot(
        cycle_id=cycle.id,
        goal_id=goal.id,
        guild_id=cycle.guild_id,
        name=cycle.name,
        state=cycle.state.value,
        starts_at=cycle.starts_at,
        ends_at=cycle.ends_at,
        timezone=cycle.timezone,
        config_version_id=cycle.config_version_id,
    )


async def get_cycle_objectives(
    session: AsyncSession, *, guild_id: str, cycle_id: int
) -> tuple[GoalObjectiveSnapshot, ...] | None:
    exists = await session.scalar(
        select(MetaCycle.id).where(MetaCycle.guild_id == guild_id, MetaCycle.id == cycle_id)
    )
    if exists is None:
        return None
    rows = list(
        (
            await session.execute(
                select(MetaCycleObjective)
                .where(
                    MetaCycleObjective.guild_id == guild_id,
                    MetaCycleObjective.cycle_id == cycle_id,
                )
                .order_by(MetaCycleObjective.position)
            )
        ).scalars()
    )
    return tuple(_objective(item) for item in rows)


async def is_member_participant(
    session: AsyncSession, *, guild_id: str, cycle_id: int, member_id: str
) -> bool:
    participant = await session.scalar(
        select(MetaCycleParticipant.id).where(
            MetaCycleParticipant.guild_id == guild_id,
            MetaCycleParticipant.cycle_id == cycle_id,
            MetaCycleParticipant.member_id == member_id,
            MetaCycleParticipant.active.is_(True),
        )
    )
    return participant is not None


async def get_active_goal_for_member(
    session: AsyncSession, *, guild_id: str, member_id: str
) -> ActiveGoalForMember | None:
    row = (
        await session.execute(
            select(MetaCycleParticipant, MetaCycle)
            .join(MetaCycle, MetaCycle.id == MetaCycleParticipant.cycle_id)
            .where(
                MetaCycleParticipant.guild_id == guild_id,
                MetaCycleParticipant.member_id == member_id,
                MetaCycleParticipant.active.is_(True),
            )
        )
    ).first()
    if row is None:
        return None
    _, cycle_model = row
    cycle = await get_cycle(session, guild_id=guild_id, cycle_id=cycle_model.id)
    objectives = await get_cycle_objectives(session, guild_id=guild_id, cycle_id=cycle_model.id)
    if cycle is None or objectives is None:
        return None
    return ActiveGoalForMember(goal_id=cycle.goal_id, cycle=cycle, objectives=objectives)


async def read_goal_events(
    session: AsyncSession,
    *,
    guild_id: str,
    after_sequence: int = 0,
    event_types: tuple[str, ...] = (),
    limit: int = 100,
) -> GoalEventPage:
    if after_sequence < 0:
        raise ValueError("after_sequence nao pode ser negativo.")
    if limit < 1 or limit > 500:
        raise ValueError("limit deve estar entre 1 e 500.")
    query = select(MetaIntegrationEvent).where(
        MetaIntegrationEvent.guild_id == guild_id,
        MetaIntegrationEvent.sequence > after_sequence,
    )
    if event_types:
        query = query.where(MetaIntegrationEvent.event_type.in_(event_types))
    rows = list(
        (
            await session.execute(
                query.order_by(MetaIntegrationEvent.sequence).limit(limit + 1)
            )
        ).scalars()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    events = tuple(
        GoalEvent(
            event_id=item.event_id,
            sequence=item.sequence,
            event_type=item.event_type,
            event_version=item.event_version,
            occurred_at=item.occurred_at,
            causation_id=item.causation_id,
            deduplication_key=item.deduplication_key,
            payload=_freeze(dict(item.payload or {})),
        )
        for item in rows
    )
    return GoalEventPage(
        events=events,
        next_sequence=events[-1].sequence if events else after_sequence,
        has_more=has_more,
    )
