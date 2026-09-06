from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import require_active_license
from app.core.security import require_admin_token
from app.db import get_session
from app.platform.configuration import effective_configuration, get_or_create_draft, publish, save_draft
from app.platform.lifecycle import ensure_module_instance, update_lifecycle
from app.platform.models import ModuleLifecycle
from app.platform.schemas import PermissionGrantIn
from pydantic import BaseModel, Field


MODULE_KEY = "parceria"
ACTOR_ID = "dashboard-admin"
MANAGER_CAPABILITIES = ("parceria.register", "parceria.edit", "parceria.deactivate")


class DashboardParceriaDraftIn(BaseModel):
    expected_revision: int = Field(ge=0)
    expected_published_version: int = Field(ge=0)
    schema_version: int = Field(ge=1)
    data: dict


class DashboardParceriaPublishIn(BaseModel):
    expected_revision: int = Field(ge=0)
    expected_published_version: int = Field(ge=0)


class DashboardParceriaLifecycleIn(BaseModel):
    lifecycle: ModuleLifecycle
    expected_lifecycle: ModuleLifecycle
    reason: str | None = Field(default=None, max_length=500)


router = APIRouter(
    prefix="/dashboard/platform/guilds",
    tags=["dashboard-platform"],
    dependencies=[Depends(require_admin_token)],
)


def _draft_out(draft) -> dict:
    return {
        "guild_id": draft.guild_id,
        "module_key": draft.module_key,
        "schema_version": draft.schema_version,
        "revision": draft.revision,
        "base_published_version": draft.base_published_version,
        "data": draft.data or {},
        "updated_by": draft.updated_by,
        "updated_at": draft.updated_at,
    }


def _instance_out(instance) -> dict:
    return {
        "guild_id": instance.guild_id,
        "module_key": instance.module_key,
        "lifecycle": instance.lifecycle.value,
        "runtime_mode": instance.runtime_mode.value,
        "published_config_version_id": instance.published_config_version_id,
        "last_error": instance.last_error,
    }


async def _overview(session: AsyncSession, guild_id: str) -> dict:
    instance = await ensure_module_instance(session, guild_id=guild_id, module_key=MODULE_KEY)
    draft = await get_or_create_draft(session, guild_id=guild_id, module_key=MODULE_KEY)
    effective = await effective_configuration(session, guild_id=guild_id, module_key=MODULE_KEY)
    return {
        "instance": _instance_out(instance),
        "draft": _draft_out(draft),
        "effective": {
            "version": effective.version,
            "data": effective.data or {},
        } if effective else None,
    }


@router.get("/{guild_id}/modules/parceria")
async def read_parceria(guild_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    result = await _overview(session, guild_id)
    await session.commit()
    return result


@router.put("/{guild_id}/modules/parceria/draft")
async def write_parceria_draft(guild_id: str, data: DashboardParceriaDraftIn, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    draft = await save_draft(
        session,
        guild_id=guild_id,
        module_key=MODULE_KEY,
        actor_id=ACTOR_ID,
        expected_revision=data.expected_revision,
        expected_published_version=data.expected_published_version,
        schema_version=data.schema_version,
        data=data.data,
        correlation_id=f"dashboard:parceria:{guild_id}:draft",
    )
    return _draft_out(draft)


@router.post("/{guild_id}/modules/parceria/publish")
async def publish_parceria(guild_id: str, data: DashboardParceriaPublishIn, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    draft = await get_or_create_draft(session, guild_id=guild_id, module_key=MODULE_KEY)
    role_ids = [str(role_id) for role_id in (draft.data or {}).get("manager_role_ids") or []]
    grants = [
        PermissionGrantIn(
            capability=capability,
            subject_type="role",
            subject_id=role_id,
            scope_type="guild",
            scope_id="",
        )
        for capability in MANAGER_CAPABILITIES
        for role_id in role_ids
    ]
    version = await publish(
        session,
        guild_id=guild_id,
        module_key=MODULE_KEY,
        actor_id=ACTOR_ID,
        expected_revision=data.expected_revision,
        expected_published_version=data.expected_published_version,
        grants=grants,
        correlation_id=f"dashboard:parceria:{guild_id}:publish",
    )
    return {"version": version.version, "data": version.data or {}, "published_by": version.published_by}


@router.put("/{guild_id}/modules/parceria/lifecycle")
async def change_parceria_lifecycle(guild_id: str, data: DashboardParceriaLifecycleIn, session: AsyncSession = Depends(get_session)) -> dict:
    await require_active_license(session, guild_id)
    instance = await update_lifecycle(
        session,
        guild_id=guild_id,
        module_key=MODULE_KEY,
        actor_id=ACTOR_ID,
        expected=data.expected_lifecycle,
        target=data.lifecycle,
        reason=data.reason,
        correlation_id=f"dashboard:parceria:{guild_id}:lifecycle",
    )
    return _instance_out(instance)
