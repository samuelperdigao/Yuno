from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.platform.lifecycle import ensure_module_instance
from app.platform.models import AutomationRun, AutomationTask, ModuleInstance, ModuleLifecycle, WorkState
from app.platform.registry import module_registry


async def schedule_task(
    session: AsyncSession,
    *,
    guild_id: str,
    module_key: str,
    job_key: str,
    resource_type: str,
    resource_id: str,
    payload: dict,
    due_at: datetime,
    idempotency_key: str,
    correlation_id: str,
    max_attempts: int | None,
    commit: bool = True,
) -> AutomationTask:
    definition = module_registry.get(module_key)
    job = definition.job(job_key) if definition else None
    if job is None:
        raise HTTPException(status_code=422, detail="Job nao declarado pelo modulo.")
    if due_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="due_at precisa incluir timezone.")
    await ensure_module_instance(session, guild_id=guild_id, module_key=module_key)
    existing = (
        await session.execute(
            select(AutomationTask).where(
                AutomationTask.guild_id == guild_id,
                AutomationTask.module_key == module_key,
                AutomationTask.job_key == job_key,
                AutomationTask.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    task = AutomationTask(
        guild_id=guild_id,
        module_key=module_key,
        job_key=job_key,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=payload,
        due_at=due_at,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        max_attempts=max_attempts or job.max_attempts,
    )
    try:
        async with session.begin_nested():
            session.add(task)
            await session.flush()
    except IntegrityError:
        task = (
            await session.execute(
                select(AutomationTask).where(
                    AutomationTask.guild_id == guild_id,
                    AutomationTask.module_key == module_key,
                    AutomationTask.job_key == job_key,
                    AutomationTask.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one()
    if commit:
        await session.commit()
    return task


async def claim_tasks(
    session: AsyncSession, *, worker_id: str, limit: int, lease_seconds: int
) -> list[AutomationTask]:
    now = datetime.now(timezone.utc)
    query = (
        select(AutomationTask)
        .join(
            ModuleInstance,
            (ModuleInstance.guild_id == AutomationTask.guild_id)
            & (ModuleInstance.module_key == AutomationTask.module_key),
        )
        .where(
            ModuleInstance.lifecycle == ModuleLifecycle.active,
            AutomationTask.due_at <= now,
            or_(
                AutomationTask.state.in_([WorkState.pending, WorkState.retry]),
                (AutomationTask.state == WorkState.claimed) & (AutomationTask.lease_until < now),
            ),
        )
        .order_by(AutomationTask.due_at, AutomationTask.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    tasks = list((await session.execute(query)).scalars())
    for task in tasks:
        task.state = WorkState.claimed
        task.lease_owner = worker_id
        task.lease_until = now + timedelta(seconds=lease_seconds)
        task.attempts += 1
        session.add(
            AutomationRun(
                task_id=task.id,
                guild_id=task.guild_id,
                module_key=task.module_key,
                job_key=task.job_key,
                attempt=task.attempts,
                worker_id=worker_id,
                correlation_id=task.correlation_id,
            )
        )
    await session.commit()
    return tasks


async def _claimed_task(
    session: AsyncSession, *, guild_id: str, task_id: str, worker_id: str
) -> AutomationTask:
    task = (
        await session.execute(
            select(AutomationTask).where(
                AutomationTask.id == task_id,
                AutomationTask.guild_id == guild_id,
            ).with_for_update()
        )
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada.")
    if task.state != WorkState.claimed or task.lease_owner != worker_id:
        raise HTTPException(status_code=409, detail="Lease da tarefa nao pertence a este worker.")
    lease_until = task.lease_until
    if lease_until is None:
        raise HTTPException(status_code=409, detail="Lease da tarefa expirou.")
    if lease_until.tzinfo is None:
        lease_until = lease_until.replace(tzinfo=timezone.utc)
    if lease_until < datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="Lease da tarefa expirou.")
    return task


async def complete_task(
    session: AsyncSession, *, guild_id: str, task_id: str, worker_id: str, result: dict
) -> AutomationTask:
    task = await _claimed_task(session, guild_id=guild_id, task_id=task_id, worker_id=worker_id)
    task.state = WorkState.succeeded
    task.result = result
    task.lease_owner = None
    task.lease_until = None
    run = (
        await session.execute(
            select(AutomationRun).where(
                AutomationRun.task_id == task.id,
                AutomationRun.attempt == task.attempts,
            )
        )
    ).scalar_one()
    run.state = WorkState.succeeded
    run.result = result
    run.finished_at = datetime.now(timezone.utc)
    await session.commit()
    return task


async def fail_task(
    session: AsyncSession,
    *,
    guild_id: str,
    task_id: str,
    worker_id: str,
    error: str,
    retry_at: datetime | None,
) -> AutomationTask:
    if retry_at is not None and retry_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="retry_at precisa incluir timezone.")
    task = await _claimed_task(session, guild_id=guild_id, task_id=task_id, worker_id=worker_id)
    exhausted = task.attempts >= task.max_attempts
    task.state = WorkState.failed if exhausted else WorkState.retry
    task.last_error = error
    task.due_at = retry_at or datetime.now(timezone.utc) + timedelta(seconds=min(900, 2 ** task.attempts))
    task.lease_owner = None
    task.lease_until = None
    run = (
        await session.execute(
            select(AutomationRun).where(
                AutomationRun.task_id == task.id,
                AutomationRun.attempt == task.attempts,
            )
        )
    ).scalar_one()
    run.state = task.state
    run.error = error
    run.finished_at = datetime.now(timezone.utc)
    await session.commit()
    return task
