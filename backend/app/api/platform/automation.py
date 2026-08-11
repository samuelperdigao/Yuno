from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import require_active_license
from app.core.security import require_bot_token
from app.db import get_session
from app.platform import automation as service
from app.platform.schemas import TaskScheduleIn, WorkClaimIn, WorkCompleteIn, WorkFailIn, WorkItemOut


router = APIRouter(dependencies=[Depends(require_bot_token)])


def task_out(item) -> WorkItemOut:
    return WorkItemOut(
        id=item.id,
        guild_id=item.guild_id,
        module_key=item.module_key,
        key=item.job_key,
        resource_type=item.resource_type,
        resource_id=item.resource_id,
        payload=item.payload or {},
        state=item.state,
        attempts=item.attempts,
        max_attempts=item.max_attempts,
        correlation_id=item.correlation_id,
    )


@router.post("/guilds/{guild_id}/modules/{module_key}/automation/tasks", response_model=WorkItemOut)
async def schedule(
    guild_id: str,
    module_key: str,
    data: TaskScheduleIn,
    session: AsyncSession = Depends(get_session),
) -> WorkItemOut:
    await require_active_license(session, guild_id)
    return task_out(
        await service.schedule_task(
            session, guild_id=guild_id, module_key=module_key, **data.model_dump()
        )
    )


@router.post("/automation/tasks/claim", response_model=list[WorkItemOut])
async def claim(data: WorkClaimIn, session: AsyncSession = Depends(get_session)) -> list[WorkItemOut]:
    return [task_out(item) for item in await service.claim_tasks(session, **data.model_dump())]


@router.post("/guilds/{guild_id}/automation/tasks/{task_id}/complete", response_model=WorkItemOut)
async def complete(
    guild_id: str,
    task_id: str,
    data: WorkCompleteIn,
    session: AsyncSession = Depends(get_session),
) -> WorkItemOut:
    await require_active_license(session, guild_id)
    return task_out(
        await service.complete_task(
            session,
            guild_id=guild_id,
            task_id=task_id,
            worker_id=data.worker_id,
            result=data.result,
        )
    )


@router.post("/guilds/{guild_id}/automation/tasks/{task_id}/fail", response_model=WorkItemOut)
async def fail(
    guild_id: str,
    task_id: str,
    data: WorkFailIn,
    session: AsyncSession = Depends(get_session),
) -> WorkItemOut:
    await require_active_license(session, guild_id)
    return task_out(
        await service.fail_task(
            session, guild_id=guild_id, task_id=task_id, **data.model_dump()
        )
    )
