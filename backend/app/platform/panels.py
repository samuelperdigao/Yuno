from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.platform.audit import write_audit
from app.platform.models import PanelInstance, PanelState
from app.platform.registry import module_registry


TRANSITIONS: dict[PanelState, set[PanelState]] = {
    PanelState.draft: {PanelState.ready, PanelState.archived, PanelState.error},
    PanelState.ready: {PanelState.published, PanelState.error, PanelState.archived},
    PanelState.published: {PanelState.paused, PanelState.missing, PanelState.error, PanelState.archived},
    PanelState.paused: {PanelState.published, PanelState.missing, PanelState.error, PanelState.archived},
    PanelState.missing: {PanelState.ready, PanelState.published, PanelState.error, PanelState.archived},
    PanelState.error: {PanelState.ready, PanelState.published, PanelState.archived},
    PanelState.archived: set(),
}


async def ensure_panel(
    session: AsyncSession,
    *,
    guild_id: str,
    module_key: str,
    panel_key: str,
    resource_type: str,
    resource_id: str,
    definition_version: int,
    recovery_policy: str,
    actor_id: str,
    correlation_id: str,
) -> PanelInstance:
    definition = module_registry.get(module_key)
    if definition is None:
        raise HTTPException(status_code=404, detail="Modulo desconhecido.")
    panel_contract = definition.panel(panel_key)
    if panel_contract is None:
        raise HTTPException(status_code=422, detail="Painel nao declarado pelo modulo.")
    if not panel_contract.durable:
        raise HTTPException(status_code=422, detail="Painel efemero nao deve ser persistido.")
    query = select(PanelInstance).where(
        PanelInstance.guild_id == guild_id,
        PanelInstance.module_key == module_key,
        PanelInstance.panel_key == panel_key,
        PanelInstance.resource_type == resource_type,
        PanelInstance.resource_id == resource_id,
    )
    panel = (await session.execute(query)).scalar_one_or_none()
    if panel is not None:
        return panel
    panel = PanelInstance(
        guild_id=guild_id,
        module_key=module_key,
        panel_key=panel_key,
        resource_type=resource_type,
        resource_id=resource_id,
        definition_version=definition_version,
        recovery_policy=recovery_policy,
        created_by=actor_id,
        updated_by=actor_id,
    )
    try:
        async with session.begin_nested():
            session.add(panel)
            await session.flush()
    except IntegrityError:
        panel = (await session.execute(query)).scalar_one()
        return panel
    await write_audit(
        session,
        guild_id=guild_id,
        module_key=module_key,
        action=f"{module_key}.panel_created",
        resource_type="panel_instance",
        resource_id=panel.id,
        actor_id=actor_id,
        after={"panel_key": panel_key, "resource_type": resource_type, "resource_id": resource_id},
        correlation_id=correlation_id,
    )
    await session.commit()
    return panel


async def get_panel(
    session: AsyncSession, *, guild_id: str, panel_id: str, for_update: bool = False
) -> PanelInstance | None:
    query = select(PanelInstance).where(
        PanelInstance.id == panel_id,
        PanelInstance.guild_id == guild_id,
    )
    if for_update:
        query = query.with_for_update()
    return (await session.execute(query)).scalar_one_or_none()


async def get_panel_by_message(
    session: AsyncSession, *, guild_id: str, channel_id: str, message_id: str
) -> PanelInstance | None:
    return (
        await session.execute(
            select(PanelInstance).where(
                PanelInstance.guild_id == guild_id,
                PanelInstance.channel_id == channel_id,
                PanelInstance.message_id == message_id,
            )
        )
    ).scalar_one_or_none()


async def update_panel(
    session: AsyncSession,
    *,
    guild_id: str,
    panel_id: str,
    actor_id: str,
    expected_render_revision: int,
    state: PanelState | None,
    channel_id: str | None,
    message_id: str | None,
    config_version: int | None,
    last_error: str | None,
    verified: bool,
    correlation_id: str,
) -> PanelInstance:
    panel = await get_panel(session, guild_id=guild_id, panel_id=panel_id, for_update=True)
    if panel is None:
        raise HTTPException(status_code=404, detail="Painel nao encontrado nesta guild.")
    if panel.render_revision != expected_render_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"detail": "Painel alterado por outra execucao.", "current_revision": panel.render_revision},
        )
    before = {
        "state": panel.state.value,
        "channel_id": panel.channel_id,
        "message_id": panel.message_id,
        "render_revision": panel.render_revision,
    }
    if state is not None and state != panel.state:
        if state not in TRANSITIONS[panel.state]:
            raise HTTPException(
                status_code=422,
                detail=f"Transicao de painel invalida: {panel.state.value} -> {state.value}.",
            )
        panel.state = state
    if channel_id is not None:
        panel.channel_id = channel_id
    if message_id is not None:
        panel.message_id = message_id
    if config_version is not None:
        panel.config_version = config_version
    panel.last_error = last_error
    panel.updated_by = actor_id
    panel.render_revision += 1
    if verified:
        panel.last_verified_at = datetime.now(timezone.utc)
    await write_audit(
        session,
        guild_id=guild_id,
        module_key=panel.module_key,
        action=f"{panel.module_key}.panel_updated",
        resource_type="panel_instance",
        resource_id=panel.id,
        actor_id=actor_id,
        before=before,
        after={
            "state": panel.state.value,
            "channel_id": panel.channel_id,
            "message_id": panel.message_id,
            "render_revision": panel.render_revision,
        },
        config_version=panel.config_version,
        correlation_id=correlation_id,
    )
    await session.commit()
    return panel
