from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import ActorHeader, CorrelationHeader, require_active_license, require_platform_admin
from app.core.security import require_bot_token
from app.db import get_session
from app.platform.lifecycle import ensure_module_instance, update_lifecycle
from app.platform.registry import PLATFORM_CONTRACT_VERSION, module_registry
from app.platform.schemas import LifecycleUpdateIn, ModuleInstanceOut, PlatformManifestOut


router = APIRouter(dependencies=[Depends(require_bot_token)])


def instance_out(instance) -> ModuleInstanceOut:
    return ModuleInstanceOut(
        guild_id=instance.guild_id,
        module_key=instance.module_key,
        lifecycle=instance.lifecycle,
        runtime_mode=instance.runtime_mode,
        contract_version=instance.contract_version,
        domain_version=instance.domain_version,
        published_config_version_id=instance.published_config_version_id,
        last_error=instance.last_error,
    )


@router.get("/manifest", response_model=PlatformManifestOut)
async def manifest() -> PlatformManifestOut:
    return PlatformManifestOut(
        platform_contract_version=PLATFORM_CONTRACT_VERSION,
        modules=module_registry.manifests(),
    )


@router.get("/guilds/{guild_id}/modules/{module_key}", response_model=ModuleInstanceOut)
async def read_instance(
    guild_id: str,
    module_key: str,
    session: AsyncSession = Depends(get_session),
) -> ModuleInstanceOut:
    await require_active_license(session, guild_id)
    instance = await ensure_module_instance(session, guild_id=guild_id, module_key=module_key)
    await session.commit()
    return instance_out(instance)


@router.put("/guilds/{guild_id}/modules/{module_key}/lifecycle", response_model=ModuleInstanceOut)
async def change_lifecycle(
    guild_id: str,
    module_key: str,
    data: LifecycleUpdateIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> ModuleInstanceOut:
    await require_active_license(session, guild_id)
    correlation = await require_platform_admin(
        session,
        guild_id=guild_id,
        actor_header=x_yuno_actor_id,
        actor=data.actor,
        correlation_header=x_yuno_correlation_id,
    )
    instance = await update_lifecycle(
        session,
        guild_id=guild_id,
        module_key=module_key,
        actor_id=x_yuno_actor_id,
        expected=data.expected_lifecycle,
        target=data.lifecycle,
        reason=data.reason,
        correlation_id=correlation,
    )
    return instance_out(instance)
