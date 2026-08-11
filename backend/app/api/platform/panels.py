from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import ActorHeader, CorrelationHeader, require_active_license, require_platform_admin
from app.core.security import require_bot_token
from app.db import get_session
from app.platform.panels import ensure_panel, get_panel, get_panel_by_message, update_panel
from app.platform.schemas import PanelEnsureIn, PanelOut, PanelUpdateIn


router = APIRouter(dependencies=[Depends(require_bot_token)])


def panel_out(item) -> PanelOut:
    return PanelOut(
        id=item.id,
        guild_id=item.guild_id,
        module_key=item.module_key,
        panel_key=item.panel_key,
        resource_type=item.resource_type,
        resource_id=item.resource_id,
        channel_id=item.channel_id,
        message_id=item.message_id,
        definition_version=item.definition_version,
        config_version=item.config_version,
        render_revision=item.render_revision,
        state=item.state,
        recovery_policy=item.recovery_policy,
        last_verified_at=item.last_verified_at,
        last_error=item.last_error,
    )


@router.post("/guilds/{guild_id}/modules/{module_key}/panels", response_model=PanelOut)
async def create_or_get_panel(
    guild_id: str,
    module_key: str,
    data: PanelEnsureIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> PanelOut:
    await require_active_license(session, guild_id)
    correlation = await require_platform_admin(
        session,
        guild_id=guild_id,
        actor_header=x_yuno_actor_id,
        actor=data.actor,
        correlation_header=x_yuno_correlation_id,
        allow_system=True,
    )
    panel = await ensure_panel(
        session,
        guild_id=guild_id,
        module_key=module_key,
        actor_id=x_yuno_actor_id,
        correlation_id=correlation,
        **data.model_dump(exclude={"actor"}),
    )
    return panel_out(panel)


@router.get("/guilds/{guild_id}/panels/by-message", response_model=PanelOut)
async def panel_from_message(
    guild_id: str,
    channel_id: str = Query(min_length=1, max_length=32),
    message_id: str = Query(min_length=1, max_length=32),
    session: AsyncSession = Depends(get_session),
) -> PanelOut:
    await require_active_license(session, guild_id)
    panel = await get_panel_by_message(
        session, guild_id=guild_id, channel_id=channel_id, message_id=message_id
    )
    if panel is None:
        raise HTTPException(status_code=404, detail="Painel nao encontrado nesta guild.")
    return panel_out(panel)


@router.patch("/guilds/{guild_id}/panels/{panel_id}", response_model=PanelOut)
async def patch_panel(
    guild_id: str,
    panel_id: str,
    data: PanelUpdateIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> PanelOut:
    await require_active_license(session, guild_id)
    correlation = await require_platform_admin(
        session,
        guild_id=guild_id,
        actor_header=x_yuno_actor_id,
        actor=data.actor,
        correlation_header=x_yuno_correlation_id,
        allow_system=True,
    )
    panel = await update_panel(
        session,
        guild_id=guild_id,
        panel_id=panel_id,
        actor_id=x_yuno_actor_id,
        correlation_id=correlation,
        **data.model_dump(exclude={"actor"}),
    )
    return panel_out(panel)
