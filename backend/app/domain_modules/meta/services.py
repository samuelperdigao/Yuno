from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
import unicodedata

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain_modules.meta.domain import (
    CycleState,
    EligibleMember,
    EVENT_GOAL_CYCLE_ENDED,
    EVENT_GOAL_CYCLE_STARTED,
    EVENT_PARTICIPANT_MOVED,
    EVENT_PARTICIPANT_REMOVED,
    GoalEndReason,
    GoalState,
    ObjectiveKind,
    ParticipantRemovalReason,
    RecurrenceKind,
    eligible_members,
    next_boundary,
)
from app.domain_modules.meta.models import (
    MetaAdminDraft,
    MetaCycle,
    MetaCycleObjective,
    MetaCycleParticipant,
    MetaGoal,
    MetaGoalConfigObjective,
    MetaGoalConfigRole,
    MetaGoalConfigVersion,
    MetaGuildSettings,
    MetaIntegrationEvent,
    MetaProduct,
)
from app.domain_modules.meta.schemas import MetaGoalConfigurationIn, MetaMemberSnapshotIn
from app.platform.audit import write_audit
from app.platform.automation import schedule_task
from app.platform.lifecycle import ensure_module_instance
from app.platform.models import AutomationTask, ModuleLifecycle, RuntimeMode, WorkState


def _http(status: int, detail: str, **current: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"detail": detail, **current})


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().split()).casefold()


async def _lock_guild(session: AsyncSession, guild_id: str) -> None:
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"yuno:meta:{guild_id}"},
        )
    else:
        # SQLite serializa escritas. A leitura garante uma fronteira explicita
        # no teste e mantem o mesmo ponto de chamada em ambos os dialetos.
        await session.execute(select(func.count(MetaGoal.id)).where(MetaGoal.guild_id == guild_id))


async def _activate_runtime(session: AsyncSession, guild_id: str) -> None:
    instance = await ensure_module_instance(session, guild_id=guild_id, module_key="meta")
    instance.lifecycle = ModuleLifecycle.active
    instance.runtime_mode = RuntimeMode.domain


def _objective_dict(item: MetaGoalConfigObjective | MetaCycleObjective) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind.value,
        "name": item.name,
        "unit": item.unit,
        "item_quantity": str(item.item_quantity) if item.item_quantity is not None else None,
        "money_amount": str(item.money_amount) if item.money_amount is not None else None,
        "position": item.position,
    }


def _config_dict(item: MetaGoalConfigVersion) -> dict[str, Any]:
    return {
        "id": item.id,
        "version": item.version,
        "name": item.name,
        "recurrence": item.recurrence.value,
        "timezone": item.timezone,
        "daily_time": item.daily_time,
        "weekday": item.weekday,
        "month_day": item.month_day,
        "scheduled_start_at": item.scheduled_start_at,
        "scheduled_end_at": item.scheduled_end_at,
        "participation": item.participation.value,
        "role_ids": [value.role_id for value in item.roles],
        "objectives": [_objective_dict(value) for value in sorted(item.objectives, key=lambda x: x.position)],
        "notice_text": item.notice_text,
    }


def goal_dict(item: MetaGoal) -> dict[str, Any]:
    return {
        "id": item.id,
        "guild_id": item.guild_id,
        "name": item.name,
        "state": item.state.value,
        "recurrence": item.recurrence.value,
        "recurrence_enabled": item.recurrence_enabled,
        "version": item.version,
        "created_sequence": item.created_sequence,
        "current_config_version_id": item.current_config_version_id,
        "future_config_version_id": item.future_config_version_id,
        "next_transition_at": item.next_transition_at,
        "end_reason": item.end_reason.value if item.end_reason else None,
        "created_at": item.created_at,
        "ended_at": item.ended_at,
    }


def cycle_dict(item: MetaCycle) -> dict[str, Any]:
    return {
        "id": item.id,
        "guild_id": item.guild_id,
        "goal_id": item.goal_id,
        "config_version_id": item.config_version_id,
        "cycle_key": item.cycle_key,
        "name": item.name,
        "notice_text": item.notice_text,
        "state": item.state.value,
        "timezone": item.timezone,
        "starts_at": item.starts_at,
        "ends_at": item.ends_at,
        "notice_channel_id": item.notice_channel_id,
        "notice_message_id": item.notice_message_id,
        "notice_reference": item.notice_reference,
        "end_reason": item.end_reason.value if item.end_reason else None,
        "revision": item.revision,
        "objectives": [_objective_dict(value) for value in sorted(item.objectives, key=lambda x: x.position)],
        "participants": [
            {
                "member_id": value.member_id,
                "display_name": value.display_name,
                "role_ids": list(value.role_ids or []),
                "active": value.active,
                "removed_at": value.removed_at,
                "removal_reason": value.removal_reason.value if value.removal_reason else None,
            }
            for value in item.participants
        ],
    }


async def get_settings(session: AsyncSession, *, guild_id: str) -> dict[str, Any]:
    item = await session.get(MetaGuildSettings, guild_id)
    return {
        "guild_id": guild_id,
        "notice_channel_id": item.notice_channel_id if item else None,
        "revision": item.revision if item else 0,
    }


async def save_settings(
    session: AsyncSession,
    *,
    guild_id: str,
    notice_channel_id: str,
    expected_revision: int | None,
    actor_id: str,
    correlation_id: str,
) -> dict[str, Any]:
    await _lock_guild(session, guild_id)
    item = await session.get(MetaGuildSettings, guild_id)
    if item is None:
        if expected_revision not in {None, 0}:
            raise _http(409, "Configuracao de Metas foi alterada.", current_revision=0)
        item = MetaGuildSettings(
            guild_id=guild_id,
            notice_channel_id=notice_channel_id,
            revision=1,
            updated_by=actor_id,
        )
        session.add(item)
    else:
        if expected_revision is not None and expected_revision != item.revision:
            raise _http(409, "Configuracao de Metas foi alterada.", current_revision=item.revision)
        item.notice_channel_id = notice_channel_id
        item.revision += 1
        item.updated_by = actor_id
    await _activate_runtime(session, guild_id)
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="meta",
        action="meta.settings.updated",
        resource_type="meta_settings",
        resource_id=guild_id,
        actor_id=actor_id,
        correlation_id=correlation_id,
        after={"notice_channel_id": notice_channel_id, "revision": item.revision},
    )
    await session.commit()
    return await get_settings(session, guild_id=guild_id)


async def _config(
    session: AsyncSession, config_id: int
) -> MetaGoalConfigVersion:
    item = (
        await session.execute(
            select(MetaGoalConfigVersion)
            .where(MetaGoalConfigVersion.id == config_id)
            .options(
                selectinload(MetaGoalConfigVersion.roles),
                selectinload(MetaGoalConfigVersion.objectives),
            )
        )
    ).scalar_one()
    return item


async def _goal(session: AsyncSession, guild_id: str, goal_id: int, *, lock: bool = False) -> MetaGoal:
    query = select(MetaGoal).where(MetaGoal.guild_id == guild_id, MetaGoal.id == goal_id)
    if lock:
        query = query.with_for_update()
    item = (await session.execute(query)).scalar_one_or_none()
    if item is None:
        raise _http(404, "Meta nao encontrada.")
    return item


async def list_goals(
    session: AsyncSession, *, guild_id: str, page: int = 0, page_size: int = 23
) -> dict[str, Any]:
    if page < 0 or page_size < 1 or page_size > 25:
        raise _http(422, "Paginacao invalida.")
    selectable = (GoalState.active, GoalState.scheduled, GoalState.launch_pending, GoalState.action_required)
    total = int(
        await session.scalar(
            select(func.count(MetaGoal.id)).where(
                MetaGoal.guild_id == guild_id, MetaGoal.state.in_(selectable)
            )
        )
        or 0
    )
    rows = list(
        (
            await session.execute(
                select(MetaGoal)
                .where(MetaGoal.guild_id == guild_id, MetaGoal.state.in_(selectable))
                .order_by(MetaGoal.created_sequence.desc())
                .offset(page * page_size)
                .limit(page_size)
            )
        ).scalars()
    )
    return {"items": [goal_dict(item) for item in rows], "page": page, "page_size": page_size, "total": total}


async def record_pending_notice(
    session: AsyncSession,
    *,
    guild_id: str,
    cycle_id: int,
    notice_channel_id: str,
    notice_message_id: str,
) -> dict[str, Any]:
    cycle = (
        await session.execute(
            select(MetaCycle)
            .where(MetaCycle.guild_id == guild_id, MetaCycle.id == cycle_id)
            .options(selectinload(MetaCycle.objectives), selectinload(MetaCycle.participants))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if cycle is None:
        raise _http(404, "Ciclo de Meta nao encontrado.")
    if cycle.state not in {CycleState.launch_pending, CycleState.active}:
        raise _http(409, "Ciclo nao aceita mais referencia de aviso.")
    if cycle.state == CycleState.active and cycle.notice_message_id not in {None, notice_message_id}:
        raise _http(409, "Aviso do ciclo ativo nao pode ser substituido.")
    cycle.notice_channel_id = notice_channel_id
    cycle.notice_message_id = notice_message_id
    await session.commit()
    return cycle_dict(cycle)


async def get_goal_detail(session: AsyncSession, *, guild_id: str, goal_id: int) -> dict[str, Any]:
    item = await _goal(session, guild_id, goal_id)
    current = await _config(session, item.current_config_version_id) if item.current_config_version_id else None
    future = await _config(session, item.future_config_version_id) if item.future_config_version_id else None
    cycle = (
        await session.execute(
            select(MetaCycle)
            .where(MetaCycle.guild_id == guild_id, MetaCycle.goal_id == goal_id)
            .options(selectinload(MetaCycle.objectives), selectinload(MetaCycle.participants))
            .order_by(MetaCycle.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return {
        **goal_dict(item),
        "current_configuration": _config_dict(current) if current else None,
        "future_configuration": _config_dict(future) if future else None,
        "latest_cycle": cycle_dict(cycle) if cycle else None,
    }


def _draft_dict(item: MetaAdminDraft) -> dict[str, Any]:
    return {
        "id": item.id,
        "guild_id": item.guild_id,
        "admin_id": item.admin_id,
        "goal_id": item.goal_id,
        "expected_goal_version": item.expected_goal_version,
        "revision": item.revision,
        "step": item.step,
        "data": dict(item.data or {}),
        "submitted_goal_id": item.submitted_goal_id,
    }


async def get_draft(session: AsyncSession, *, guild_id: str, admin_id: str) -> dict[str, Any]:
    item = (
        await session.execute(
            select(MetaAdminDraft).where(
                MetaAdminDraft.guild_id == guild_id, MetaAdminDraft.admin_id == admin_id
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise _http(404, "Rascunho de Meta nao encontrado.")
    return _draft_dict(item)


async def _draft_from_goal(session: AsyncSession, goal: MetaGoal) -> dict[str, Any]:
    config_id = goal.future_config_version_id or goal.current_config_version_id
    if config_id is None:
        return {}
    data = jsonable_encoder(_config_dict(await _config(session, config_id)))
    data.pop("id", None)
    data.pop("version", None)
    objective_fields = {
        "kind", "name", "unit", "item_quantity", "money_amount"
    }
    data["objectives"] = [
        {key: value for key, value in item.items() if key in objective_fields}
        for item in data.get("objectives") or []
    ]
    return data


async def open_draft(
    session: AsyncSession, *, guild_id: str, admin_id: str, goal_id: int | None
) -> dict[str, Any]:
    await _lock_guild(session, guild_id)
    goal = await _goal(session, guild_id, goal_id, lock=True) if goal_id else None
    if goal is not None:
        if goal.state == GoalState.ended:
            raise _http(409, "Meta encerrada e somente leitura.")
        if goal.state == GoalState.active and goal.recurrence == RecurrenceKind.custom:
            raise _http(409, "Meta personalizada ativa e somente leitura.")
        if goal.state in {GoalState.launch_pending, GoalState.action_required}:
            raise _http(409, "A Meta esta em lancamento e nao pode ser editada agora.")
        data = await _draft_from_goal(session, goal)
    else:
        data = {
            "timezone": "America/Sao_Paulo",
            "role_ids": [],
            "objectives": [],
        }
    item = (
        await session.execute(
            select(MetaAdminDraft).where(
                MetaAdminDraft.guild_id == guild_id,
                MetaAdminDraft.admin_id == admin_id,
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if item is None:
        item = MetaAdminDraft(guild_id=guild_id, admin_id=admin_id)
        session.add(item)
    else:
        item.revision += 1
    item.goal_id = goal.id if goal else None
    item.expected_goal_version = goal.version if goal else None
    item.step = "name"
    item.data = data
    item.submitted_goal_id = None
    await session.commit()
    return _draft_dict(item)


async def patch_draft(
    session: AsyncSession,
    *,
    guild_id: str,
    admin_id: str,
    expected_revision: int,
    step: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    item = (
        await session.execute(
            select(MetaAdminDraft).where(
                MetaAdminDraft.guild_id == guild_id,
                MetaAdminDraft.admin_id == admin_id,
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if item is None:
        raise _http(404, "Rascunho de Meta nao encontrado.")
    if item.revision != expected_revision:
        raise _http(409, "Rascunho foi alterado.", current_revision=item.revision)
    forbidden = {"guild_id", "admin_id", "goal_id", "expected_goal_version", "revision"}
    if forbidden.intersection(patch):
        raise _http(422, "Campo reservado no rascunho.")
    item.data = {**dict(item.data or {}), **jsonable_encoder(patch)}
    item.step = step
    item.revision += 1
    item.submitted_goal_id = None
    await session.commit()
    return _draft_dict(item)


async def _product_for_objective(
    session: AsyncSession,
    *,
    guild_id: str,
    name: str,
    unit: str,
    quantity: Decimal,
    actor_id: str,
) -> MetaProduct:
    key = _normalize_name(name)
    item = (
        await session.execute(
            select(MetaProduct).where(
                MetaProduct.guild_id == guild_id,
                MetaProduct.active_key == key,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        item = MetaProduct(
            guild_id=guild_id,
            name=" ".join(name.split()),
            normalized_name=key,
            active_key=key,
            unit=unit,
            last_suggested_quantity=quantity,
            created_by=actor_id,
        )
        session.add(item)
        await session.flush()
    else:
        item.name = " ".join(name.split())
        item.unit = unit
        item.last_suggested_quantity = quantity
    return item


async def _materialize_config(
    session: AsyncSession,
    *,
    goal: MetaGoal,
    data: MetaGoalConfigurationIn,
    version: int,
    actor_id: str,
) -> MetaGoalConfigVersion:
    config = MetaGoalConfigVersion(
        goal_id=goal.id,
        guild_id=goal.guild_id,
        version=version,
        name=data.name,
        recurrence=data.recurrence,
        timezone=data.timezone,
        daily_time=data.daily_time,
        weekday=data.weekday,
        month_day=data.month_day,
        scheduled_start_at=_utc(data.scheduled_start_at) if data.scheduled_start_at else None,
        scheduled_end_at=_utc(data.scheduled_end_at) if data.scheduled_end_at else None,
        participation=data.participation,
        notice_text=data.notice_text,
        created_by=actor_id,
    )
    session.add(config)
    await session.flush()
    session.add_all([
        MetaGoalConfigRole(config_version_id=config.id, guild_id=goal.guild_id, role_id=value)
        for value in data.role_ids
    ])
    objectives: list[MetaGoalConfigObjective] = []
    for position, value in enumerate(data.objectives):
        product_id = None
        if value.kind == ObjectiveKind.item:
            product = await _product_for_objective(
                session,
                guild_id=goal.guild_id,
                name=value.name,
                unit=value.unit or "unidade",
                quantity=value.item_quantity or Decimal("0"),
                actor_id=actor_id,
            )
            product_id = product.id
        objectives.append(
            MetaGoalConfigObjective(
                config_version_id=config.id,
                guild_id=goal.guild_id,
                kind=value.kind,
                product_id=product_id,
                name=value.name,
                unit=value.unit,
                item_quantity=value.item_quantity,
                money_amount=value.money_amount,
                position=position,
            )
        )
    session.add_all(objectives)
    await session.flush()
    return config


async def _cancel_goal_tasks(session: AsyncSession, goal_id: int) -> None:
    await session.execute(
        update(AutomationTask)
        .where(
            AutomationTask.module_key == "meta",
            AutomationTask.resource_type == "meta_goal",
            AutomationTask.resource_id == str(goal_id),
            AutomationTask.state.in_([WorkState.pending, WorkState.retry]),
        )
        .values(state=WorkState.cancelled, lease_owner=None, lease_until=None)
    )


async def _schedule_launch(
    session: AsyncSession,
    *,
    goal: MetaGoal,
    due_at: datetime,
    correlation_id: str,
    key_suffix: str,
) -> None:
    await schedule_task(
        session,
        guild_id=goal.guild_id,
        module_key="meta",
        job_key="meta.goal.launch",
        resource_type="meta_goal",
        resource_id=str(goal.id),
        payload={"goal_id": goal.id},
        due_at=_utc(due_at),
        idempotency_key=f"goal:{goal.id}:launch:{key_suffix}",
        correlation_id=correlation_id,
        max_attempts=None,
        commit=False,
    )


async def _reload_stale_draft(
    session: AsyncSession, draft: MetaAdminDraft, goal: MetaGoal
) -> None:
    draft.data = await _draft_from_goal(session, goal)
    draft.expected_goal_version = goal.version
    draft.step = "review"
    draft.revision += 1
    draft.submitted_goal_id = None
    await session.commit()


async def submit_draft(
    session: AsyncSession,
    *,
    guild_id: str,
    admin_id: str,
    expected_revision: int,
    correlation_id: str,
) -> dict[str, Any]:
    await _lock_guild(session, guild_id)
    draft = (
        await session.execute(
            select(MetaAdminDraft).where(
                MetaAdminDraft.guild_id == guild_id,
                MetaAdminDraft.admin_id == admin_id,
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if draft is None:
        raise _http(404, "Rascunho de Meta nao encontrado.")
    if draft.revision != expected_revision:
        raise _http(409, "Rascunho foi alterado.", current_revision=draft.revision)
    if draft.submitted_goal_id is not None:
        existing = await _goal(session, guild_id, draft.submitted_goal_id)
        return goal_dict(existing)
    try:
        allowed = MetaGoalConfigurationIn.model_fields
        data = MetaGoalConfigurationIn.model_validate(
            {key: value for key, value in dict(draft.data or {}).items() if key in allowed}
        )
    except ValueError as exc:
        raise _http(422, str(exc)) from exc
    now = datetime.now(timezone.utc)
    await _activate_runtime(session, guild_id)
    if draft.goal_id is None:
        sequence = int(
            await session.scalar(
                select(func.coalesce(func.max(MetaGoal.created_sequence), 0)).where(
                    MetaGoal.guild_id == guild_id
                )
            )
            or 0
        ) + 1
        goal = MetaGoal(
            guild_id=guild_id,
            created_sequence=sequence,
            creation_key=f"{draft.id}:{draft.revision}",
            name=data.name,
            state=GoalState.scheduled,
            recurrence=data.recurrence,
            recurrence_enabled=data.recurrence != RecurrenceKind.custom,
            created_by=admin_id,
        )
        session.add(goal)
        await session.flush()
        config = await _materialize_config(
            session, goal=goal, data=data, version=1, actor_id=admin_id
        )
        goal.current_config_version_id = config.id
        due_at = data.scheduled_start_at if data.recurrence == RecurrenceKind.custom else now
        if due_at is None:
            raise _http(422, "Inicio da Meta personalizada nao informado.")
        goal.next_transition_at = _utc(due_at)
        await _schedule_launch(
            session,
            goal=goal,
            due_at=goal.next_transition_at,
            correlation_id=correlation_id,
            key_suffix=f"config:{config.id}",
        )
        action = "meta.goal.created"
    else:
        goal = await _goal(session, guild_id, draft.goal_id, lock=True)
        if draft.expected_goal_version != goal.version:
            await _reload_stale_draft(session, draft, goal)
            raise _http(
                409,
                "A Meta foi alterada por outro administrador. A versao atual foi recarregada.",
                current_version=goal.version,
                draft_revision=draft.revision,
            )
        if goal.state == GoalState.ended:
            raise _http(409, "Meta encerrada e somente leitura.")
        if goal.state == GoalState.active and goal.recurrence == RecurrenceKind.custom:
            raise _http(409, "Meta personalizada ativa e somente leitura.")
        if goal.state in {GoalState.launch_pending, GoalState.action_required}:
            raise _http(409, "A Meta esta em lancamento e nao pode ser editada agora.")
        next_version = int(
            await session.scalar(
                select(func.coalesce(func.max(MetaGoalConfigVersion.version), 0)).where(
                    MetaGoalConfigVersion.goal_id == goal.id
                )
            )
            or 0
        ) + 1
        config = await _materialize_config(
            session, goal=goal, data=data, version=next_version, actor_id=admin_id
        )
        if goal.state == GoalState.active:
            goal.future_config_version_id = config.id
        else:
            goal.current_config_version_id = config.id
            goal.name = data.name
            goal.recurrence = data.recurrence
            goal.recurrence_enabled = data.recurrence != RecurrenceKind.custom
            due_at = data.scheduled_start_at if data.recurrence == RecurrenceKind.custom else now
            if due_at is None:
                raise _http(422, "Inicio da Meta personalizada nao informado.")
            goal.next_transition_at = _utc(due_at)
            await _cancel_goal_tasks(session, goal.id)
            await _schedule_launch(
                session,
                goal=goal,
                due_at=goal.next_transition_at,
                correlation_id=correlation_id,
                key_suffix=f"config:{config.id}",
            )
        goal.version += 1
        action = "meta.goal.next_configuration_updated" if goal.state == GoalState.active else "meta.goal.scheduled_updated"
    draft.submitted_goal_id = goal.id
    draft.expected_goal_version = goal.version
    draft.step = "submitted"
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="meta",
        action=action,
        resource_type="meta_goal",
        resource_id=str(goal.id),
        actor_id=admin_id,
        correlation_id=correlation_id,
        after={"goal_version": goal.version, "config_version_id": config.id},
    )
    await session.commit()
    return goal_dict(goal)


async def _emit_event(
    session: AsyncSession,
    *,
    guild_id: str,
    event_type: str,
    causation_id: str,
    deduplication_key: str,
    payload: dict[str, Any],
) -> MetaIntegrationEvent:
    existing = (
        await session.execute(
            select(MetaIntegrationEvent).where(
                MetaIntegrationEvent.guild_id == guild_id,
                MetaIntegrationEvent.deduplication_key == deduplication_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    sequence = int(
        await session.scalar(
            select(func.coalesce(func.max(MetaIntegrationEvent.sequence), 0)).where(
                MetaIntegrationEvent.guild_id == guild_id
            )
        )
        or 0
    ) + 1
    event = MetaIntegrationEvent(
        guild_id=guild_id,
        sequence=sequence,
        event_type=event_type,
        event_version=1,
        causation_id=causation_id,
        deduplication_key=deduplication_key,
        payload=jsonable_encoder(payload),
    )
    session.add(event)
    await session.flush()
    return event


def _eligible_input(
    members: list[MetaMemberSnapshotIn], config: MetaGoalConfigVersion
) -> tuple[EligibleMember, ...]:
    snapshots = tuple(
        EligibleMember(
            member_id=item.member_id,
            display_name=item.display_name,
            role_ids=tuple(item.role_ids),
        )
        for item in members
    )
    return eligible_members(
        snapshots,
        participation=config.participation,
        role_ids=tuple(value.role_id for value in config.roles),
    )


async def _temporary_zero(
    session: AsyncSession,
    *,
    goal: MetaGoal,
    config: MetaGoalConfigVersion,
    now: datetime,
    causation_id: str,
) -> dict[str, Any]:
    if config.recurrence == RecurrenceKind.custom:
        goal.state = GoalState.ended
        goal.end_reason = GoalEndReason.completed
        goal.ended_at = now
        goal.next_transition_at = None
        await _cancel_goal_tasks(session, goal.id)
        return {"status": "ended_without_participants", "goal": goal_dict(goal)}
    due_at = next_boundary(
        recurrence=config.recurrence,
        after=now,
        timezone_name=config.timezone,
        daily_time=config.daily_time,
        weekday=config.weekday,
        month_day=config.month_day,
    )
    goal.state = GoalState.scheduled
    goal.next_transition_at = due_at
    await _schedule_launch(
        session,
        goal=goal,
        due_at=due_at,
        correlation_id=causation_id,
        key_suffix=f"reevaluate:{due_at.isoformat()}",
    )
    return {"status": "temporarily_without_participants", "goal": goal_dict(goal), "retry_at": due_at}


async def prepare_launch(
    session: AsyncSession,
    *,
    guild_id: str,
    goal_id: int,
    members: list[MetaMemberSnapshotIn],
    notice_channel_id: str,
    causation_id: str,
) -> dict[str, Any]:
    await _lock_guild(session, guild_id)
    goal = await _goal(session, guild_id, goal_id, lock=True)
    if goal.state == GoalState.ended or (
        goal.recurrence != RecurrenceKind.custom and not goal.recurrence_enabled
    ):
        return {"status": "ended", "goal": goal_dict(goal)}
    existing = (
        await session.execute(
            select(MetaCycle)
            .where(
                MetaCycle.guild_id == guild_id,
                MetaCycle.goal_id == goal.id,
                MetaCycle.state == CycleState.launch_pending,
            )
            .options(selectinload(MetaCycle.objectives), selectinload(MetaCycle.participants))
            .order_by(MetaCycle.id.desc())
        )
    ).scalars().first()
    if existing is not None:
        return {"status": "prepared", "goal": goal_dict(goal), "cycle": cycle_dict(existing)}
    if goal.current_config_version_id is None:
        raise _http(409, "Meta sem configuracao vigente.")
    config = await _config(session, goal.current_config_version_id)
    now = datetime.now(timezone.utc)
    if config.recurrence == RecurrenceKind.custom:
        if config.scheduled_start_at is None or config.scheduled_end_at is None:
            raise _http(409, "Meta personalizada sem periodo valido.")
        starts_at = _utc(config.scheduled_start_at)
        ends_at = _utc(config.scheduled_end_at)
        if now < starts_at:
            raise _http(409, "Inicio da Meta ainda nao venceu.", due_at=starts_at)
        if now >= ends_at:
            result = await _temporary_zero(
                session, goal=goal, config=config, now=now, causation_id=causation_id
            )
            await session.commit()
            return result
    else:
        starts_at = now
        ends_at = next_boundary(
            recurrence=config.recurrence,
            after=now,
            timezone_name=config.timezone,
            daily_time=config.daily_time,
            weekday=config.weekday,
            month_day=config.month_day,
        )
    candidates = _eligible_input(members, config)
    if not candidates:
        result = await _temporary_zero(
            session, goal=goal, config=config, now=now, causation_id=causation_id
        )
        await session.commit()
        return result
    cycle_key = f"{config.id}:{int(starts_at.timestamp())}"
    cycle = MetaCycle(
        guild_id=guild_id,
        goal_id=goal.id,
        config_version_id=config.id,
        cycle_key=cycle_key,
        name=config.name,
        notice_text=config.notice_text,
        state=CycleState.launch_pending,
        timezone=config.timezone,
        starts_at=starts_at,
        ends_at=ends_at,
        notice_channel_id=notice_channel_id,
        notice_reference=f"meta:{goal.id}:{cycle_key}",
    )
    session.add(cycle)
    await session.flush()
    session.add_all([
        MetaCycleObjective(
            guild_id=guild_id,
            cycle_id=cycle.id,
            kind=item.kind,
            product_id=item.product_id,
            name=item.name,
            unit=item.unit,
            item_quantity=item.item_quantity,
            money_amount=item.money_amount,
            position=item.position,
        )
        for item in config.objectives
    ])
    session.add_all([
        MetaCycleParticipant(
            guild_id=guild_id,
            cycle_id=cycle.id,
            member_id=item.member_id,
            display_name=item.display_name,
            role_ids=list(item.role_ids),
            active=False,
        )
        for item in candidates
    ])
    goal.state = GoalState.launch_pending
    goal.next_transition_at = ends_at
    await session.commit()
    refreshed = (
        await session.execute(
            select(MetaCycle)
            .where(MetaCycle.id == cycle.id)
            .options(selectinload(MetaCycle.objectives), selectinload(MetaCycle.participants))
        )
    ).scalar_one()
    return {"status": "prepared", "goal": goal_dict(goal), "cycle": cycle_dict(refreshed)}


async def _end_replaced_goal(
    session: AsyncSession,
    *,
    goal: MetaGoal,
    cycle: MetaCycle,
    now: datetime,
    causation_id: str,
) -> None:
    cycle.state = CycleState.ended
    cycle.end_reason = GoalEndReason.replaced
    cycle.ended_at = now
    cycle.revision += 1
    goal.state = GoalState.ended
    goal.end_reason = GoalEndReason.replaced
    goal.recurrence_enabled = False
    goal.next_transition_at = None
    goal.ended_at = now
    goal.version += 1
    await _cancel_goal_tasks(session, goal.id)
    await _emit_event(
        session,
        guild_id=goal.guild_id,
        event_type=EVENT_GOAL_CYCLE_ENDED,
        causation_id=causation_id,
        deduplication_key=f"cycle:{cycle.id}:ended:replaced",
        payload={
            "goal_id": goal.id,
            "cycle_id": cycle.id,
            "reason": GoalEndReason.replaced.value,
            "recurrence_disabled": True,
        },
    )


async def activate_cycle(
    session: AsyncSession,
    *,
    guild_id: str,
    cycle_id: int,
    members: list[MetaMemberSnapshotIn],
    notice_channel_id: str,
    notice_message_id: str,
    causation_id: str,
) -> dict[str, Any]:
    await _lock_guild(session, guild_id)
    cycle = (
        await session.execute(
            select(MetaCycle)
            .where(MetaCycle.guild_id == guild_id, MetaCycle.id == cycle_id)
            .options(selectinload(MetaCycle.objectives), selectinload(MetaCycle.participants))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if cycle is None:
        raise _http(404, "Ciclo de Meta nao encontrado.")
    goal = await _goal(session, guild_id, cycle.goal_id, lock=True)
    if cycle.state == CycleState.active:
        return {"status": "active", "goal": goal_dict(goal), "cycle": cycle_dict(cycle), "ended_notices": []}
    if cycle.state != CycleState.launch_pending:
        return {"status": "ended", "goal": goal_dict(goal), "cycle": cycle_dict(cycle), "ended_notices": []}
    config = await _config(session, cycle.config_version_id)
    current_candidates = {item.member_id: item for item in _eligible_input(members, config)}
    await session.execute(
        delete(MetaCycleParticipant).where(
            MetaCycleParticipant.cycle_id == cycle.id,
            MetaCycleParticipant.member_id.not_in(tuple(current_candidates) or ("",)),
            MetaCycleParticipant.active.is_(False),
        )
    )
    prepared = {item.member_id: item for item in cycle.participants}
    for member_id, member in current_candidates.items():
        item = prepared.get(member_id)
        if item is None:
            item = MetaCycleParticipant(
                guild_id=guild_id,
                cycle_id=cycle.id,
                member_id=member.member_id,
                display_name=member.display_name,
                role_ids=list(member.role_ids),
                active=False,
            )
            session.add(item)
            prepared[member_id] = item
        else:
            item.display_name = member.display_name
            item.role_ids = list(member.role_ids)
    await session.flush()
    owners: dict[str, tuple[MetaCycleParticipant, MetaCycle, MetaGoal]] = {}
    if current_candidates:
        rows = (
            await session.execute(
                select(MetaCycleParticipant, MetaCycle, MetaGoal)
                .join(MetaCycle, MetaCycle.id == MetaCycleParticipant.cycle_id)
                .join(MetaGoal, MetaGoal.id == MetaCycle.goal_id)
                .where(
                    MetaCycleParticipant.guild_id == guild_id,
                    MetaCycleParticipant.member_id.in_(tuple(current_candidates)),
                    MetaCycleParticipant.active.is_(True),
                    MetaCycleParticipant.cycle_id != cycle.id,
                )
                .with_for_update()
            )
        ).all()
        owners = {participant.member_id: (participant, old_cycle, old_goal) for participant, old_cycle, old_goal in rows}
    final_ids: set[str] = set()
    blocked_by_newer: set[str] = set()
    affected_cycles: dict[int, tuple[MetaCycle, MetaGoal]] = {}
    now = datetime.now(timezone.utc)
    for member_id in current_candidates:
        owner = owners.get(member_id)
        if owner is None:
            final_ids.add(member_id)
            continue
        old_participant, old_cycle, old_goal = owner
        if goal.created_sequence < old_goal.created_sequence:
            blocked_by_newer.add(member_id)
            continue
        old_participant.active = False
        old_participant.removed_at = now
        old_participant.removal_reason = ParticipantRemovalReason.moved_to_another_goal
        affected_cycles[old_cycle.id] = (old_cycle, old_goal)
        final_ids.add(member_id)
        await _emit_event(
            session,
            guild_id=guild_id,
            event_type=EVENT_PARTICIPANT_REMOVED,
            causation_id=causation_id,
            deduplication_key=f"cycle:{old_cycle.id}:member:{member_id}:removed:goal:{goal.id}",
            payload={
                "goal_id": old_goal.id,
                "cycle_id": old_cycle.id,
                "member_id": member_id,
                "reason": ParticipantRemovalReason.moved_to_another_goal.value,
                "destination_goal_id": goal.id,
            },
        )
        await _emit_event(
            session,
            guild_id=guild_id,
            event_type=EVENT_PARTICIPANT_MOVED,
            causation_id=causation_id,
            deduplication_key=f"member:{member_id}:moved:{old_cycle.id}:{cycle.id}",
            payload={
                "member_id": member_id,
                "source_goal_id": old_goal.id,
                "source_cycle_id": old_cycle.id,
                "destination_goal_id": goal.id,
                "destination_cycle_id": cycle.id,
            },
        )
    await session.flush()
    ended_notices: list[dict[str, Any]] = []
    for old_cycle, old_goal in affected_cycles.values():
        remaining = int(
            await session.scalar(
                select(func.count(MetaCycleParticipant.id)).where(
                    MetaCycleParticipant.cycle_id == old_cycle.id,
                    MetaCycleParticipant.active.is_(True),
                )
            )
            or 0
        )
        if remaining == 0:
            await _end_replaced_goal(
                session,
                goal=old_goal,
                cycle=old_cycle,
                now=now,
                causation_id=causation_id,
            )
            ended_notices.append(
                {
                    "cycle_id": old_cycle.id,
                    "goal_id": old_goal.id,
                    "channel_id": old_cycle.notice_channel_id,
                    "message_id": old_cycle.notice_message_id,
                }
            )
    for ended_notice in ended_notices:
        if ended_notice["message_id"]:
            await schedule_task(
                session,
                guild_id=guild_id,
                module_key="meta",
                job_key="meta.notice.reconcile",
                resource_type="meta_cycle",
                resource_id=str(ended_notice["cycle_id"]),
                payload=ended_notice,
                due_at=now,
                idempotency_key=f"cycle:{ended_notice['cycle_id']}:notice:ended",
                correlation_id=causation_id,
                max_attempts=None,
                commit=False,
            )
    if not final_ids:
        cycle.notice_channel_id = notice_channel_id
        cycle.notice_message_id = notice_message_id
        cycle.state = CycleState.ended
        cycle.ended_at = now
        cycle.revision += 1
        if current_candidates and blocked_by_newer == set(current_candidates):
            cycle.end_reason = GoalEndReason.replaced
            goal.state = GoalState.ended
            goal.end_reason = GoalEndReason.replaced
            goal.recurrence_enabled = False
            goal.next_transition_at = None
            goal.ended_at = now
            goal.version += 1
            await _cancel_goal_tasks(session, goal.id)
            status = "replaced"
        else:
            cycle.end_reason = GoalEndReason.completed
            result = await _temporary_zero(
                session, goal=goal, config=config, now=now, causation_id=causation_id
            )
            status = result["status"]
        await session.commit()
        return {
            "status": status,
            "goal": goal_dict(goal),
            "cycle": cycle_dict(cycle),
            "ended_notices": ended_notices,
        }
    await session.execute(
        delete(MetaCycleParticipant).where(
            MetaCycleParticipant.cycle_id == cycle.id,
            MetaCycleParticipant.member_id.not_in(tuple(final_ids)),
            MetaCycleParticipant.active.is_(False),
        )
    )
    participants = list(
        (
            await session.execute(
                select(MetaCycleParticipant).where(
                    MetaCycleParticipant.cycle_id == cycle.id,
                    MetaCycleParticipant.member_id.in_(tuple(final_ids)),
                )
            )
        ).scalars()
    )
    for participant in participants:
        participant.active = True
        participant.joined_at = now
        participant.removed_at = None
        participant.removal_reason = None
    cycle.notice_channel_id = notice_channel_id
    cycle.notice_message_id = notice_message_id
    cycle.state = CycleState.active
    cycle.activated_at = now
    cycle.revision += 1
    goal.state = GoalState.active
    goal.next_transition_at = cycle.ends_at
    goal.version += 1
    await _emit_event(
        session,
        guild_id=guild_id,
        event_type=EVENT_GOAL_CYCLE_STARTED,
        causation_id=causation_id,
        deduplication_key=f"cycle:{cycle.id}:started",
        payload={
            "goal_id": goal.id,
            "cycle_id": cycle.id,
            "config_version_id": cycle.config_version_id,
            "starts_at": cycle.starts_at,
            "ends_at": cycle.ends_at,
            "participant_ids": sorted(final_ids),
        },
    )
    await schedule_task(
        session,
        guild_id=guild_id,
        module_key="meta",
        job_key="meta.cycle.transition",
        resource_type="meta_goal",
        resource_id=str(goal.id),
        payload={"goal_id": goal.id, "cycle_id": cycle.id},
        due_at=_utc(cycle.ends_at),
        idempotency_key=f"cycle:{cycle.id}:transition",
        correlation_id=causation_id,
        max_attempts=None,
        commit=False,
    )
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="meta",
        action="meta.cycle.activated",
        resource_type="meta_cycle",
        resource_id=str(cycle.id),
        actor_type="system",
        correlation_id=causation_id,
        after={"participants": len(final_ids), "moved": len(affected_cycles)},
    )
    await session.commit()
    refreshed = (
        await session.execute(
            select(MetaCycle)
            .where(MetaCycle.id == cycle.id)
            .options(selectinload(MetaCycle.objectives), selectinload(MetaCycle.participants))
        )
    ).scalar_one()
    return {
        "status": "active",
        "goal": goal_dict(goal),
        "cycle": cycle_dict(refreshed),
        "ended_notices": ended_notices,
    }


async def close_cycle(
    session: AsyncSession,
    *,
    guild_id: str,
    cycle_id: int,
    causation_id: str,
) -> dict[str, Any]:
    await _lock_guild(session, guild_id)
    cycle = (
        await session.execute(
            select(MetaCycle)
            .where(MetaCycle.guild_id == guild_id, MetaCycle.id == cycle_id)
            .options(selectinload(MetaCycle.objectives), selectinload(MetaCycle.participants))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if cycle is None:
        raise _http(404, "Ciclo de Meta nao encontrado.")
    goal = await _goal(session, guild_id, cycle.goal_id, lock=True)
    if cycle.state == CycleState.ended:
        return {"status": "ended", "goal": goal_dict(goal), "cycle": cycle_dict(cycle)}
    now = datetime.now(timezone.utc)
    for participant in cycle.participants:
        participant.active = False
    cycle.state = CycleState.ended
    cycle.end_reason = GoalEndReason.completed
    cycle.ended_at = now
    cycle.revision += 1
    await _emit_event(
        session,
        guild_id=guild_id,
        event_type=EVENT_GOAL_CYCLE_ENDED,
        causation_id=causation_id,
        deduplication_key=f"cycle:{cycle.id}:ended:completed",
        payload={"goal_id": goal.id, "cycle_id": cycle.id, "reason": GoalEndReason.completed.value},
    )
    if goal.recurrence == RecurrenceKind.custom or not goal.recurrence_enabled:
        goal.state = GoalState.ended
        goal.end_reason = GoalEndReason.completed
        goal.ended_at = now
        goal.next_transition_at = None
    else:
        if goal.future_config_version_id is not None:
            goal.current_config_version_id = goal.future_config_version_id
            goal.future_config_version_id = None
            config = await _config(session, goal.current_config_version_id)
            goal.name = config.name
            goal.recurrence = config.recurrence
            goal.recurrence_enabled = config.recurrence != RecurrenceKind.custom
        else:
            config = await _config(session, goal.current_config_version_id)
        goal.state = GoalState.scheduled
        due_at = (
            _utc(config.scheduled_start_at)
            if config.recurrence == RecurrenceKind.custom and config.scheduled_start_at
            else now
        )
        goal.next_transition_at = due_at
        await _schedule_launch(
            session,
            goal=goal,
            due_at=due_at,
            correlation_id=causation_id,
            key_suffix=f"after-cycle:{cycle.id}:config:{config.id}",
        )
    goal.version += 1
    await session.commit()
    return {"status": "ended", "goal": goal_dict(goal), "cycle": cycle_dict(cycle)}


async def remove_member(
    session: AsyncSession,
    *,
    guild_id: str,
    member_id: str,
    causation_id: str,
) -> dict[str, Any]:
    await _lock_guild(session, guild_id)
    row = (
        await session.execute(
            select(MetaCycleParticipant, MetaCycle, MetaGoal)
            .join(MetaCycle, MetaCycle.id == MetaCycleParticipant.cycle_id)
            .join(MetaGoal, MetaGoal.id == MetaCycle.goal_id)
            .where(
                MetaCycleParticipant.guild_id == guild_id,
                MetaCycleParticipant.member_id == member_id,
                MetaCycleParticipant.active.is_(True),
            )
            .with_for_update()
        )
    ).first()
    if row is None:
        return {"removed": False}
    participant, cycle, goal = row
    participant.active = False
    participant.removed_at = datetime.now(timezone.utc)
    participant.removal_reason = ParticipantRemovalReason.left_guild
    await _emit_event(
        session,
        guild_id=guild_id,
        event_type=EVENT_PARTICIPANT_REMOVED,
        causation_id=causation_id,
        deduplication_key=f"cycle:{cycle.id}:member:{member_id}:left",
        payload={
            "goal_id": goal.id,
            "cycle_id": cycle.id,
            "member_id": member_id,
            "reason": ParticipantRemovalReason.left_guild.value,
        },
    )
    await session.commit()
    return {"removed": True, "goal_id": goal.id, "cycle_id": cycle.id}


async def reconcile(session: AsyncSession, *, guild_id: str, causation_id: str) -> dict[str, Any]:
    await _lock_guild(session, guild_id)
    now = datetime.now(timezone.utc)
    scheduled = list(
        (
            await session.execute(
                select(MetaGoal).where(
                    MetaGoal.guild_id == guild_id,
                    MetaGoal.state == GoalState.scheduled,
                    MetaGoal.next_transition_at.is_not(None),
                )
            )
        ).scalars()
    )
    launch_tasks = 0
    for goal in scheduled:
        due_at = _utc(goal.next_transition_at or now)
        await _schedule_launch(
            session,
            goal=goal,
            due_at=due_at,
            correlation_id=causation_id,
            key_suffix=f"recovery:{goal.version}:{due_at.isoformat()}",
        )
        launch_tasks += 1
    overdue = list(
        (
            await session.execute(
                select(MetaCycle).where(
                    MetaCycle.guild_id == guild_id,
                    MetaCycle.state == CycleState.active,
                    MetaCycle.ends_at <= now,
                )
            )
        ).scalars()
    )
    transition_tasks = 0
    for cycle in overdue:
        await schedule_task(
            session,
            guild_id=guild_id,
            module_key="meta",
            job_key="meta.cycle.transition",
            resource_type="meta_goal",
            resource_id=str(cycle.goal_id),
            payload={"goal_id": cycle.goal_id, "cycle_id": cycle.id},
            due_at=now,
            idempotency_key=f"cycle:{cycle.id}:transition",
            correlation_id=causation_id,
            max_attempts=None,
            commit=False,
        )
        transition_tasks += 1
    pending_cycles = list(
        (
            await session.execute(
                select(MetaCycle).where(
                MetaCycle.guild_id == guild_id,
                MetaCycle.state == CycleState.launch_pending,
                )
            )
        ).scalars()
    )
    for cycle in pending_cycles:
        await schedule_task(
            session,
            guild_id=guild_id,
            module_key="meta",
            job_key="meta.goal.launch",
            resource_type="meta_goal",
            resource_id=str(cycle.goal_id),
            payload={"goal_id": cycle.goal_id},
            due_at=now,
            idempotency_key=f"cycle:{cycle.id}:launch-recovery",
            correlation_id=causation_id,
            max_attempts=None,
            commit=False,
        )
        launch_tasks += 1
    await session.commit()
    return {
        "launch_tasks": launch_tasks,
        "transition_tasks": transition_tasks,
        "launch_pending": len(pending_cycles),
    }
