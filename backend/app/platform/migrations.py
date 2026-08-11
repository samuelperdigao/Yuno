from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit import write_audit
from app.platform.lifecycle import ensure_module_instance
from app.platform.models import MigrationState, ModuleMigrationRun, RuntimeMode
from app.platform.registry import module_registry


MIGRATION_TRANSITIONS: dict[MigrationState, set[MigrationState]] = {
    MigrationState.inventory: {
        MigrationState.backfill,
        MigrationState.validating,
        MigrationState.failed,
    },
    MigrationState.backfill: {MigrationState.validating, MigrationState.failed},
    MigrationState.validating: {MigrationState.ready, MigrationState.failed},
    MigrationState.ready: {MigrationState.cutover, MigrationState.failed},
    MigrationState.cutover: {MigrationState.succeeded, MigrationState.failed},
    MigrationState.succeeded: {MigrationState.rolled_back},
    MigrationState.failed: set(),
    MigrationState.rolled_back: set(),
}


async def start_migration(
    session: AsyncSession,
    *,
    guild_id: str,
    module_key: str,
    migration_key: str,
    target_mode: RuntimeMode,
    actor_id: str,
    correlation_id: str,
) -> ModuleMigrationRun:
    definition = module_registry.get(module_key)
    if definition is None or definition.migration is None:
        raise HTTPException(status_code=422, detail="Modulo nao declara contrato de migracao.")
    instance = await ensure_module_instance(
        session,
        guild_id=guild_id,
        module_key=module_key,
        for_update=True,
        initial_runtime_mode=(
            RuntimeMode.legacy
            if "legacy" in definition.manifest.runtime_modes
            else RuntimeMode(definition.manifest.default_runtime_mode)
        ),
    )
    last_attempt = await session.scalar(
        select(func.max(ModuleMigrationRun.attempt)).where(
            ModuleMigrationRun.guild_id == guild_id,
            ModuleMigrationRun.module_key == module_key,
            ModuleMigrationRun.migration_key == migration_key,
        )
    )
    run = ModuleMigrationRun(
        guild_id=guild_id,
        module_key=module_key,
        migration_key=migration_key,
        attempt=int(last_attempt or 0) + 1,
        source_mode=instance.runtime_mode,
        target_mode=target_mode,
        started_by=actor_id,
    )
    session.add(run)
    await session.flush()
    await write_audit(
        session,
        guild_id=guild_id,
        module_key=module_key,
        action="migration.started",
        resource_type="module_migration_run",
        resource_id=run.id,
        actor_id=actor_id,
        after={"migration_key": migration_key, "target_mode": target_mode.value},
        correlation_id=correlation_id,
    )
    await session.commit()
    return run


async def update_migration(
    session: AsyncSession,
    *,
    guild_id: str,
    run_id: str,
    actor_id: str,
    state: MigrationState,
    checkpoint: dict,
    counts: dict,
    checksum: str | None,
    warnings: list[str],
    errors: list[str],
    correlation_id: str,
) -> ModuleMigrationRun:
    run = (
        await session.execute(
            select(ModuleMigrationRun)
            .where(ModuleMigrationRun.id == run_id, ModuleMigrationRun.guild_id == guild_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Execucao de migracao nao encontrada nesta guild.")
    if state != run.state and state not in MIGRATION_TRANSITIONS[run.state]:
        raise HTTPException(
            status_code=422,
            detail=f"Transicao de migracao invalida: {run.state.value} -> {state.value}.",
        )
    run.state = state
    run.checkpoint = checkpoint
    run.counts = counts
    run.checksum = checksum
    run.warnings = warnings
    run.errors = errors
    if state in {MigrationState.succeeded, MigrationState.failed, MigrationState.rolled_back}:
        run.finished_at = datetime.now(timezone.utc)
    await write_audit(
        session,
        guild_id=guild_id,
        module_key=run.module_key,
        action="migration.updated",
        resource_type="module_migration_run",
        resource_id=run.id,
        actor_id=actor_id,
        after={"state": state.value, "counts": counts, "checksum": checksum},
        result="failure" if state == MigrationState.failed else "success",
        correlation_id=correlation_id,
    )
    await session.commit()
    return run


async def cutover(
    session: AsyncSession,
    *,
    guild_id: str,
    run_id: str,
    actor_id: str,
    correlation_id: str,
) -> ModuleMigrationRun:
    run = (
        await session.execute(
            select(ModuleMigrationRun)
            .where(ModuleMigrationRun.id == run_id, ModuleMigrationRun.guild_id == guild_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Execucao de migracao nao encontrada nesta guild.")
    if run.state != MigrationState.ready or run.errors:
        raise HTTPException(status_code=422, detail="Migracao ainda nao esta pronta para corte.")
    instance = await ensure_module_instance(
        session, guild_id=guild_id, module_key=run.module_key, for_update=True
    )
    if instance.runtime_mode != run.source_mode:
        raise HTTPException(status_code=409, detail="Runtime mudou desde o inicio da migracao.")
    definition = module_registry.get(run.module_key)
    assert definition is not None
    if run.target_mode.value not in definition.manifest.runtime_modes:
        raise HTTPException(status_code=422, detail="Runtime alvo nao suportado pelo modulo.")
    if run.target_mode == RuntimeMode.domain:
        if definition.lifecycle.requires_published_configuration and instance.published_config_version_id is None:
            raise HTTPException(status_code=422, detail="Publique a configuracao antes do cutover.")
        if definition.migration is not None:
            validation_errors = await definition.migration.validate(session, guild_id)
            if validation_errors:
                raise HTTPException(status_code=422, detail={"detail": "Cutover bloqueado pela validacao do modulo.", "errors": validation_errors})
    before = instance.runtime_mode
    instance.runtime_mode = run.target_mode
    run.state = MigrationState.cutover
    run.finished_at = datetime.now(timezone.utc)
    await write_audit(
        session,
        guild_id=guild_id,
        module_key=run.module_key,
        action="migration.cutover",
        resource_type="module_instance",
        resource_id=str(instance.id),
        actor_id=actor_id,
        before={"runtime_mode": before.value},
        after={"runtime_mode": run.target_mode.value, "migration_run_id": run.id},
        correlation_id=correlation_id,
    )
    run.state = MigrationState.succeeded
    await session.commit()
    return run


async def rollback_cutover(
    session: AsyncSession,
    *,
    guild_id: str,
    run_id: str,
    actor_id: str,
    correlation_id: str,
) -> ModuleMigrationRun:
    run = (
        await session.execute(
            select(ModuleMigrationRun)
            .where(ModuleMigrationRun.id == run_id, ModuleMigrationRun.guild_id == guild_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Execucao de migracao nao encontrada nesta guild.")
    if run.state != MigrationState.succeeded:
        raise HTTPException(status_code=422, detail="Apenas um corte concluido pode ser revertido.")
    if (run.checkpoint or {}).get("incompatible_writes"):
        raise HTTPException(status_code=422, detail="Rollback inseguro; execute roll-forward.")
    instance = await ensure_module_instance(
        session, guild_id=guild_id, module_key=run.module_key, for_update=True
    )
    if instance.runtime_mode != run.target_mode:
        raise HTTPException(status_code=409, detail="Runtime atual nao corresponde ao corte.")
    instance.runtime_mode = run.source_mode
    run.state = MigrationState.rolled_back
    run.finished_at = datetime.now(timezone.utc)
    await write_audit(
        session,
        guild_id=guild_id,
        module_key=run.module_key,
        action="migration.rolled_back",
        resource_type="module_instance",
        resource_id=str(instance.id),
        actor_id=actor_id,
        after={"runtime_mode": run.source_mode.value, "migration_run_id": run.id},
        correlation_id=correlation_id,
    )
    await session.commit()
    return run
