from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GuildConfig, ModuleConfigState
from app.schemas import MODULES, ModuleConfigDraftIn, ModuleConfigPublishIn
from app.services import audit, get_or_create_config


# A Central transitória não possui mais módulos suportados. O domínio `meta`
# agora é integralmente atendido por /internal/platform/.../modules/meta.
CONTROL_PLANE_SCHEMA_VERSIONS: dict[str, int] = {}


def assert_module_key(module_key: str) -> None:
    if module_key not in MODULES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Modulo desconhecido.")
    if module_key == "meta":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Metas usa exclusivamente o dominio /internal/platform.",
        )


def assert_schema_version(module_key: str, schema_version: int) -> None:
    supported = CONTROL_PLANE_SCHEMA_VERSIONS.get(module_key)
    if supported is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Migracao deste modulo para a Central pendente.",
        )
    if schema_version != supported:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Versao de schema nao suportada. Use {supported}.",
        )


async def get_state(
    session: AsyncSession,
    *,
    guild_id: str,
    module_key: str,
    for_update: bool = False,
) -> ModuleConfigState | None:
    query = select(ModuleConfigState).where(
        ModuleConfigState.guild_id == guild_id,
        ModuleConfigState.module_key == module_key,
    )
    if for_update:
        query = query.with_for_update()
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_or_create_state(
    session: AsyncSession,
    *,
    guild_id: str,
    module_key: str,
    for_update: bool = False,
) -> ModuleConfigState:
    assert_module_key(module_key)
    state = await get_state(
        session,
        guild_id=guild_id,
        module_key=module_key,
        for_update=for_update,
    )
    if state is not None:
        return state
    state = ModuleConfigState(guild_id=guild_id, module_key=module_key)
    session.add(state)
    await session.flush()
    return state


def revision_conflict(expected: int, current: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "detail": "O rascunho foi alterado por outra sessao. Recarregue antes de continuar.",
            "expected_revision": expected,
            "current_revision": current,
        },
    )


async def save_draft(
    session: AsyncSession,
    *,
    guild_id: str,
    module_key: str,
    actor_id: str,
    data: ModuleConfigDraftIn,
) -> ModuleConfigState:
    assert_schema_version(module_key, data.schema_version)
    state = await get_or_create_state(
        session,
        guild_id=guild_id,
        module_key=module_key,
        for_update=True,
    )
    if state.draft_revision != data.expected_revision:
        raise revision_conflict(data.expected_revision, state.draft_revision)

    state.schema_version = data.schema_version
    state.draft_data = data.draft_data
    state.draft_revision += 1
    state.draft_updated_by = actor_id
    state.draft_updated_at = datetime.now(timezone.utc)
    await audit(
        session,
        action="control_plane.draft_saved",
        entity_type="module_config_state",
        entity_id=module_key,
        guild_id=guild_id,
        actor_id=actor_id,
        payload={
            "module": module_key,
            "draft_revision": state.draft_revision,
            "schema_version": state.schema_version,
        },
    )
    await session.commit()
    return state


def _merge_dict(current: dict | None, patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current or {})
    merged.update(patch)
    return merged


def apply_projection(
    config: GuildConfig,
    *,
    module_key: str,
    data: ModuleConfigPublishIn,
) -> None:
    projection = data.projection

    settings = dict(config.settings or {})
    settings[module_key] = _merge_dict(settings.get(module_key), projection.settings)
    config.settings = settings

    messages = dict(config.messages or {})
    messages[module_key] = _merge_dict(messages.get(module_key), projection.messages)
    config.messages = messages

    permissions = dict(config.command_permissions or {})
    permissions.update(projection.command_permissions)
    config.command_permissions = permissions

    if projection.enabled is not None:
        modules = dict(config.modules or {})
        modules[module_key] = projection.enabled
        config.modules = modules


async def publish(
    session: AsyncSession,
    *,
    guild_id: str,
    module_key: str,
    actor_id: str,
    data: ModuleConfigPublishIn,
) -> ModuleConfigState:
    assert_schema_version(module_key, data.schema_version)
    state = await get_or_create_state(
        session,
        guild_id=guild_id,
        module_key=module_key,
        for_update=True,
    )
    if state.draft_revision != data.expected_revision:
        raise revision_conflict(data.expected_revision, state.draft_revision)
    if not state.draft_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nao existe rascunho para publicar.",
        )

    config = await get_or_create_config(session, guild_id)
    apply_projection(config, module_key=module_key, data=data)

    state.schema_version = data.schema_version
    state.published_data = dict(state.draft_data)
    state.published_revision += 1
    state.published_by = actor_id
    state.published_at = datetime.now(timezone.utc)
    await audit(
        session,
        action="control_plane.published",
        entity_type="module_config_state",
        entity_id=module_key,
        guild_id=guild_id,
        actor_id=actor_id,
        payload={
            "module": module_key,
            "draft_revision": state.draft_revision,
            "published_revision": state.published_revision,
            "schema_version": state.schema_version,
            "snapshot": state.published_data,
            "panel_refs": data.panel_refs,
        },
    )
    await session.commit()
    return state
