from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.platform.audit import write_audit
from app.platform.lifecycle import ensure_module_instance
from app.platform.models import ModuleConfigDraft, ModuleConfigVersion, ModulePermissionGrant
from app.platform.registry import module_registry
from app.platform.schemas import PermissionGrantIn


def _hash(data: dict) -> str:
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _conflict(detail: str, **current: int) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"detail": detail, **current})


async def get_or_create_draft(
    session: AsyncSession, *, guild_id: str, module_key: str, for_update: bool = False
) -> ModuleConfigDraft:
    instance = await ensure_module_instance(
        session, guild_id=guild_id, module_key=module_key, for_update=for_update
    )
    query = select(ModuleConfigDraft).where(
        ModuleConfigDraft.module_instance_id == instance.id,
        ModuleConfigDraft.guild_id == guild_id,
    )
    if for_update:
        query = query.with_for_update()
    draft = (await session.execute(query)).scalar_one_or_none()
    if draft is not None:
        return draft
    definition = module_registry.get(module_key)
    if definition is None or definition.configuration is None:
        raise HTTPException(status_code=422, detail="Modulo nao possui contrato de configuracao domain.")
    draft = ModuleConfigDraft(
        module_instance_id=instance.id,
        guild_id=guild_id,
        module_key=module_key,
        schema_version=definition.configuration.schema_version,
        data=definition.configuration.defaults(),
    )
    try:
        async with session.begin_nested():
            session.add(draft)
            await session.flush()
    except IntegrityError:
        draft = (
            await session.execute(
                select(ModuleConfigDraft).where(
                    ModuleConfigDraft.module_instance_id == instance.id,
                    ModuleConfigDraft.guild_id == guild_id,
                )
            )
        ).scalar_one()
    return draft


async def save_draft(
    session: AsyncSession,
    *,
    guild_id: str,
    module_key: str,
    actor_id: str,
    expected_revision: int,
    expected_published_version: int,
    schema_version: int,
    data: dict,
    correlation_id: str,
) -> ModuleConfigDraft:
    definition = module_registry.get(module_key)
    if definition is None or definition.configuration is None:
        raise HTTPException(status_code=422, detail="Modulo nao possui contrato de configuracao domain.")
    if schema_version != definition.configuration.schema_version:
        raise HTTPException(status_code=422, detail="Versao de schema de configuracao incompativel.")
    errors = definition.configuration.validate(data)
    if errors:
        raise HTTPException(status_code=422, detail={"detail": "Configuracao invalida.", "errors": errors})
    draft = await get_or_create_draft(
        session, guild_id=guild_id, module_key=module_key, for_update=True
    )
    if draft.revision != expected_revision:
        raise _conflict("Rascunho alterado por outra sessao.", current_revision=draft.revision)
    if draft.base_published_version != expected_published_version:
        raise _conflict(
            "A configuracao publicada mudou desde a abertura do rascunho.",
            current_published_version=draft.base_published_version,
        )
    before_hash = _hash(draft.data or {})
    draft.data = data
    draft.schema_version = schema_version
    draft.revision += 1
    draft.updated_by = actor_id
    draft.updated_at = datetime.now(timezone.utc)
    await write_audit(
        session,
        guild_id=guild_id,
        module_key=module_key,
        action=f"{module_key}.config_updated",
        resource_type="module_config_draft",
        resource_id=str(draft.id),
        actor_id=actor_id,
        before={"revision": expected_revision, "content_hash": before_hash},
        after={"revision": draft.revision, "content_hash": _hash(data)},
        correlation_id=correlation_id,
    )
    await session.commit()
    return draft


async def _current_version(session: AsyncSession, instance_id: int) -> int:
    value = await session.scalar(
        select(func.max(ModuleConfigVersion.version)).where(
            ModuleConfigVersion.module_instance_id == instance_id
        )
    )
    return int(value or 0)


def _validate_grants(module_key: str, grants: list[PermissionGrantIn]) -> None:
    definition = module_registry.get(module_key)
    assert definition is not None
    capabilities = {item.key for item in definition.capabilities}
    seen: set[tuple[str, str, str, str, str]] = set()
    for grant in grants:
        if grant.capability not in capabilities:
            raise HTTPException(status_code=422, detail=f"Capability desconhecida: {grant.capability}.")
        identity = (
            grant.capability, grant.subject_type, grant.subject_id, grant.scope_type, grant.scope_id
        )
        if identity in seen:
            raise HTTPException(status_code=422, detail="Grant duplicado na publicacao.")
        seen.add(identity)


async def publish(
    session: AsyncSession,
    *,
    guild_id: str,
    module_key: str,
    actor_id: str,
    expected_revision: int,
    expected_published_version: int,
    grants: list[PermissionGrantIn],
    correlation_id: str,
    source_version: int | None = None,
) -> ModuleConfigVersion:
    _validate_grants(module_key, grants)
    instance = await ensure_module_instance(
        session, guild_id=guild_id, module_key=module_key, for_update=True
    )
    current = await _current_version(session, instance.id)
    if current != expected_published_version:
        raise _conflict("A versao publicada mudou.", current_published_version=current)
    draft = await get_or_create_draft(
        session, guild_id=guild_id, module_key=module_key, for_update=True
    )
    if draft.revision != expected_revision:
        raise _conflict("Rascunho alterado por outra sessao.", current_revision=draft.revision)
    if draft.base_published_version != expected_published_version:
        raise _conflict(
            "O rascunho foi criado sobre outra versao publicada.",
            current_published_version=current,
        )
    definition = module_registry.get(module_key)
    assert definition is not None and definition.configuration is not None
    errors = definition.configuration.validate(draft.data or {})
    if errors:
        raise HTTPException(status_code=422, detail={"detail": "Configuracao invalida.", "errors": errors})
    if definition.permission_validator is not None:
        permission_errors = definition.permission_validator(draft.data or {}, grants)
        if permission_errors:
            raise HTTPException(
                status_code=422,
                detail={"detail": "Permissoes publicadas invalidas.", "errors": permission_errors},
            )

    version = ModuleConfigVersion(
        module_instance_id=instance.id,
        guild_id=guild_id,
        module_key=module_key,
        version=current + 1,
        schema_version=draft.schema_version,
        data=dict(draft.data or {}),
        content_hash=_hash(draft.data or {}),
        source_version=source_version,
        published_by=actor_id,
    )
    session.add(version)
    await session.flush()
    for grant in grants:
        session.add(
            ModulePermissionGrant(
                module_instance_id=instance.id,
                config_version_id=version.id,
                guild_id=guild_id,
                module_key=module_key,
                **grant.model_dump(),
            )
        )
    instance.published_config_version_id = version.id
    draft.base_published_version = version.version
    await write_audit(
        session,
        guild_id=guild_id,
        module_key=module_key,
        action=(
            f"{module_key}.config_published"
            if source_version is None
            else f"{module_key}.config_rolled_back"
        ),
        resource_type="module_config_version",
        resource_id=str(version.id),
        actor_id=actor_id,
        before={"version": current},
        after={"version": version.version, "content_hash": version.content_hash},
        config_version=version.version,
        correlation_id=correlation_id,
    )
    await session.commit()
    return version


async def rollback(
    session: AsyncSession,
    *,
    guild_id: str,
    module_key: str,
    actor_id: str,
    source_version: int,
    expected_published_version: int,
    correlation_id: str,
) -> ModuleConfigVersion:
    instance = await ensure_module_instance(
        session, guild_id=guild_id, module_key=module_key, for_update=True
    )
    source = (
        await session.execute(
            select(ModuleConfigVersion).where(
                ModuleConfigVersion.module_instance_id == instance.id,
                ModuleConfigVersion.guild_id == guild_id,
                ModuleConfigVersion.version == source_version,
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Versao historica nao encontrada nesta guild.")
    draft = await get_or_create_draft(
        session, guild_id=guild_id, module_key=module_key, for_update=True
    )
    draft.data = dict(source.data or {})
    draft.schema_version = source.schema_version
    draft.base_published_version = expected_published_version
    draft.revision += 1
    draft.updated_by = actor_id
    grants = (
        await session.execute(
            select(ModulePermissionGrant).where(
                ModulePermissionGrant.config_version_id == source.id,
                ModulePermissionGrant.guild_id == guild_id,
            )
        )
    ).scalars().all()
    grant_inputs = [
        PermissionGrantIn(
            capability=item.capability,
            subject_type=item.subject_type,
            subject_id=item.subject_id,
            scope_type=item.scope_type,
            scope_id=item.scope_id,
            constraints=item.constraints or {},
        )
        for item in grants
    ]
    return await publish(
        session,
        guild_id=guild_id,
        module_key=module_key,
        actor_id=actor_id,
        expected_revision=draft.revision,
        expected_published_version=expected_published_version,
        grants=grant_inputs,
        correlation_id=correlation_id,
        source_version=source_version,
    )


async def effective_configuration(
    session: AsyncSession, *, guild_id: str, module_key: str
) -> ModuleConfigVersion | None:
    instance = await ensure_module_instance(session, guild_id=guild_id, module_key=module_key)
    if instance.published_config_version_id is None:
        return None
    return (
        await session.execute(
            select(ModuleConfigVersion).where(
                ModuleConfigVersion.id == instance.published_config_version_id,
                ModuleConfigVersion.module_instance_id == instance.id,
                ModuleConfigVersion.guild_id == guild_id,
            )
        )
    ).scalar_one_or_none()
