from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import ActorHeader, CorrelationHeader, require_active_license, require_platform_admin
from app.core.security import require_bot_token
from app.db import get_session
from app.platform.configuration import effective_configuration, get_or_create_draft, publish, rollback, save_draft
from app.platform.schemas import (
    ConfigDraftIn,
    ConfigDraftOut,
    ConfigPublishIn,
    ConfigRollbackIn,
    ConfigVersionOut,
)


router = APIRouter(dependencies=[Depends(require_bot_token)])


def draft_out(item) -> ConfigDraftOut:
    return ConfigDraftOut(
        guild_id=item.guild_id,
        module_key=item.module_key,
        schema_version=item.schema_version,
        revision=item.revision,
        base_published_version=item.base_published_version,
        data=item.data or {},
        updated_by=item.updated_by,
        updated_at=item.updated_at,
    )


def version_out(item) -> ConfigVersionOut:
    return ConfigVersionOut(
        id=item.id,
        guild_id=item.guild_id,
        module_key=item.module_key,
        version=item.version,
        schema_version=item.schema_version,
        data=item.data or {},
        content_hash=item.content_hash,
        source_version=item.source_version,
        published_by=item.published_by,
        published_at=item.published_at,
    )


@router.get("/guilds/{guild_id}/modules/{module_key}/configuration/draft", response_model=ConfigDraftOut)
async def read_draft(
    guild_id: str,
    module_key: str,
    session: AsyncSession = Depends(get_session),
) -> ConfigDraftOut:
    await require_active_license(session, guild_id)
    draft = await get_or_create_draft(session, guild_id=guild_id, module_key=module_key)
    await session.commit()
    return draft_out(draft)


@router.put("/guilds/{guild_id}/modules/{module_key}/configuration/draft", response_model=ConfigDraftOut)
async def write_draft(
    guild_id: str,
    module_key: str,
    data: ConfigDraftIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> ConfigDraftOut:
    await require_active_license(session, guild_id)
    correlation = await require_platform_admin(
        session,
        guild_id=guild_id,
        actor_header=x_yuno_actor_id,
        actor=data.actor,
        correlation_header=x_yuno_correlation_id,
    )
    draft = await save_draft(
        session,
        guild_id=guild_id,
        module_key=module_key,
        actor_id=x_yuno_actor_id,
        correlation_id=correlation,
        **data.model_dump(exclude={"actor"}),
    )
    return draft_out(draft)


@router.get("/guilds/{guild_id}/modules/{module_key}/configuration/effective", response_model=ConfigVersionOut)
async def read_effective(
    guild_id: str,
    module_key: str,
    session: AsyncSession = Depends(get_session),
) -> ConfigVersionOut:
    await require_active_license(session, guild_id)
    version = await effective_configuration(session, guild_id=guild_id, module_key=module_key)
    if version is None:
        raise HTTPException(status_code=404, detail="Modulo sem configuracao publicada.")
    return version_out(version)


@router.post("/guilds/{guild_id}/modules/{module_key}/configuration/publish", response_model=ConfigVersionOut)
async def publish_configuration(
    guild_id: str,
    module_key: str,
    data: ConfigPublishIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> ConfigVersionOut:
    await require_active_license(session, guild_id)
    correlation = await require_platform_admin(
        session,
        guild_id=guild_id,
        actor_header=x_yuno_actor_id,
        actor=data.actor,
        correlation_header=x_yuno_correlation_id,
    )
    version = await publish(
        session,
        guild_id=guild_id,
        module_key=module_key,
        actor_id=x_yuno_actor_id,
        correlation_id=correlation,
        expected_revision=data.expected_revision,
        expected_published_version=data.expected_published_version,
        grants=data.grants,
    )
    return version_out(version)


@router.post("/guilds/{guild_id}/modules/{module_key}/configuration/rollback", response_model=ConfigVersionOut)
async def rollback_configuration(
    guild_id: str,
    module_key: str,
    data: ConfigRollbackIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> ConfigVersionOut:
    await require_active_license(session, guild_id)
    correlation = await require_platform_admin(
        session,
        guild_id=guild_id,
        actor_header=x_yuno_actor_id,
        actor=data.actor,
        correlation_header=x_yuno_correlation_id,
    )
    version = await rollback(
        session,
        guild_id=guild_id,
        module_key=module_key,
        actor_id=x_yuno_actor_id,
        correlation_id=correlation,
        **data.model_dump(exclude={"actor"}),
    )
    return version_out(version)
