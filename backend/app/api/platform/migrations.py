from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import ActorHeader, CorrelationHeader, require_active_license, require_platform_admin
from app.core.security import require_bot_token
from app.db import get_session
from app.platform import migrations as service
from app.platform.schemas import AdministrativeActionIn, MigrationOut, MigrationStartIn, MigrationUpdateIn


router = APIRouter(dependencies=[Depends(require_bot_token)])


def migration_out(item) -> MigrationOut:
    return MigrationOut(
        id=item.id,
        guild_id=item.guild_id,
        module_key=item.module_key,
        migration_key=item.migration_key,
        attempt=item.attempt,
        source_mode=item.source_mode,
        target_mode=item.target_mode,
        state=item.state,
        checkpoint=item.checkpoint or {},
        counts=item.counts or {},
        checksum=item.checksum,
        warnings=item.warnings or [],
        errors=item.errors or [],
    )


@router.post("/guilds/{guild_id}/modules/{module_key}/migrations", response_model=MigrationOut)
async def start(
    guild_id: str,
    module_key: str,
    data: MigrationStartIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> MigrationOut:
    await require_active_license(session, guild_id)
    correlation = await require_platform_admin(
        session, guild_id=guild_id, actor_header=x_yuno_actor_id, actor=data.actor,
        correlation_header=x_yuno_correlation_id,
    )
    return migration_out(
        await service.start_migration(
            session,
            guild_id=guild_id,
            module_key=module_key,
            actor_id=x_yuno_actor_id,
            correlation_id=correlation,
            **data.model_dump(exclude={"actor"}),
        )
    )


@router.patch("/guilds/{guild_id}/migrations/{run_id}", response_model=MigrationOut)
async def update(
    guild_id: str,
    run_id: str,
    data: MigrationUpdateIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> MigrationOut:
    await require_active_license(session, guild_id)
    correlation = await require_platform_admin(
        session, guild_id=guild_id, actor_header=x_yuno_actor_id, actor=data.actor,
        correlation_header=x_yuno_correlation_id,
    )
    return migration_out(
        await service.update_migration(
            session,
            guild_id=guild_id,
            run_id=run_id,
            actor_id=x_yuno_actor_id,
            correlation_id=correlation,
            **data.model_dump(exclude={"actor"}),
        )
    )


@router.post("/guilds/{guild_id}/migrations/{run_id}/cutover", response_model=MigrationOut)
async def cutover(
    guild_id: str,
    run_id: str,
    data: AdministrativeActionIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> MigrationOut:
    await require_active_license(session, guild_id)
    correlation = await require_platform_admin(
        session, guild_id=guild_id, actor_header=x_yuno_actor_id, actor=data.actor,
        correlation_header=x_yuno_correlation_id,
    )
    return migration_out(
        await service.cutover(
            session,
            guild_id=guild_id,
            run_id=run_id,
            actor_id=x_yuno_actor_id,
            correlation_id=correlation,
        )
    )


@router.post("/guilds/{guild_id}/migrations/{run_id}/rollback", response_model=MigrationOut)
async def rollback(
    guild_id: str,
    run_id: str,
    data: AdministrativeActionIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> MigrationOut:
    await require_active_license(session, guild_id)
    correlation = await require_platform_admin(
        session, guild_id=guild_id, actor_header=x_yuno_actor_id, actor=data.actor,
        correlation_header=x_yuno_correlation_id,
    )
    return migration_out(
        await service.rollback_cutover(
            session,
            guild_id=guild_id,
            run_id=run_id,
            actor_id=x_yuno_actor_id,
            correlation_id=correlation,
        )
    )
