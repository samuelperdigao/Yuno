from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.platform.audit import write_audit
from app.platform.models import ModuleInstance, ModuleLifecycle, RuntimeMode
from app.platform.registry import module_registry


LIFECYCLE_TRANSITIONS: dict[ModuleLifecycle, set[ModuleLifecycle]] = {
    ModuleLifecycle.inactive: {ModuleLifecycle.active, ModuleLifecycle.degraded},
    ModuleLifecycle.active: {
        ModuleLifecycle.paused,
        ModuleLifecycle.inactive,
        ModuleLifecycle.degraded,
    },
    ModuleLifecycle.paused: {
        ModuleLifecycle.active,
        ModuleLifecycle.inactive,
        ModuleLifecycle.degraded,
    },
    ModuleLifecycle.degraded: {
        ModuleLifecycle.active,
        ModuleLifecycle.paused,
        ModuleLifecycle.inactive,
    },
}


async def get_module_instance(
    session: AsyncSession,
    *,
    guild_id: str,
    module_key: str,
    for_update: bool = False,
) -> ModuleInstance | None:
    query = select(ModuleInstance).where(
        ModuleInstance.guild_id == guild_id,
        ModuleInstance.module_key == module_key,
    )
    if for_update:
        query = query.with_for_update()
    return (await session.execute(query)).scalar_one_or_none()


async def ensure_module_instance(
    session: AsyncSession,
    *,
    guild_id: str,
    module_key: str,
    for_update: bool = False,
    initial_runtime_mode: RuntimeMode | None = None,
) -> ModuleInstance:
    definition = module_registry.get(module_key)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Modulo desconhecido.")
    instance = await get_module_instance(
        session, guild_id=guild_id, module_key=module_key, for_update=for_update
    )
    if instance is not None:
        return instance
    default_mode = initial_runtime_mode or RuntimeMode(definition.manifest.default_runtime_mode)
    if default_mode.value not in definition.manifest.runtime_modes:
        raise HTTPException(status_code=422, detail="Runtime inicial nao suportado pelo modulo.")
    instance = ModuleInstance(
        guild_id=guild_id,
        module_key=module_key,
        lifecycle=ModuleLifecycle.inactive,
        runtime_mode=default_mode,
        contract_version=definition.manifest.contract_version,
        domain_version=definition.manifest.domain_version,
    )
    try:
        async with session.begin_nested():
            session.add(instance)
            await session.flush()
    except IntegrityError:
        instance = await get_module_instance(
            session, guild_id=guild_id, module_key=module_key, for_update=for_update
        )
        if instance is None:
            raise
    return instance


async def update_lifecycle(
    session: AsyncSession,
    *,
    guild_id: str,
    module_key: str,
    actor_id: str,
    expected: ModuleLifecycle,
    target: ModuleLifecycle,
    reason: str | None,
    correlation_id: str,
) -> ModuleInstance:
    instance = await ensure_module_instance(
        session, guild_id=guild_id, module_key=module_key, for_update=True
    )
    if instance.lifecycle != expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"detail": "Lifecycle alterado por outra sessao.", "current": instance.lifecycle},
        )
    if target == expected:
        await session.commit()
        return instance
    if target not in LIFECYCLE_TRANSITIONS[expected]:
        raise HTTPException(
            status_code=422,
            detail=f"Transicao de lifecycle invalida: {expected.value} -> {target.value}.",
        )
    definition = module_registry.get(module_key)
    assert definition is not None
    if target == ModuleLifecycle.active and definition.lifecycle.requires_published_configuration:
        if instance.published_config_version_id is None:
            raise HTTPException(status_code=422, detail="Publique uma configuracao valida antes de ativar.")
    if target == ModuleLifecycle.paused and not definition.lifecycle.may_pause:
        raise HTTPException(status_code=422, detail="Este modulo nao pode ser pausado.")
    if target == ModuleLifecycle.inactive and not definition.lifecycle.may_deactivate:
        raise HTTPException(status_code=422, detail="Este modulo nao pode ser desativado.")

    before = instance.lifecycle.value
    instance.lifecycle = target
    instance.last_error = reason if target == ModuleLifecycle.degraded else None
    await write_audit(
        session,
        guild_id=guild_id,
        module_key=module_key,
        action="module.lifecycle_changed",
        resource_type="module_instance",
        resource_id=str(instance.id),
        actor_id=actor_id,
        before={"lifecycle": before},
        after={"lifecycle": target.value, "reason": reason},
        correlation_id=correlation_id,
    )
    if module_key == "tags":
        await write_audit(
            session,
            guild_id=guild_id,
            module_key="tags",
            action="tags.lifecycle_changed",
            resource_type="module_instance",
            resource_id=str(instance.id),
            actor_id=actor_id,
            before={"lifecycle": before},
            after={"lifecycle": target.value, "reason": reason},
            correlation_id=correlation_id,
        )
    await session.commit()
    if module_key == "tags" and target == ModuleLifecycle.active:
        from app.domain_modules.tags.domain import TagSyncRunMode
        from app.domain_modules.tags.services import create_sync_run

        await create_sync_run(
            session,
            guild_id=guild_id,
            mode=TagSyncRunMode.effective,
            reason="activated",
            actor_id=actor_id,
            correlation_id=correlation_id,
            supersede_active=True,
        )
    return instance
