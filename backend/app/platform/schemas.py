from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.platform.models import MigrationState, ModuleLifecycle, PanelState, RuntimeMode, WorkState


class ModuleManifestOut(BaseModel):
    key: str
    name: str
    description: str
    contract_version: int
    domain_version: str
    minimum_plan: str
    dependencies: list[dict[str, Any]] = Field(default_factory=list)
    required_discord_permissions: list[str] = Field(default_factory=list)
    provided_resources: list[str] = Field(default_factory=list)
    runtime_modes: list[str] = Field(default_factory=list)
    default_runtime_mode: str
    configuration: dict[str, Any] | None = None
    capabilities: list[dict[str, Any]] = Field(default_factory=list)
    lifecycle: dict[str, Any] = Field(default_factory=dict)
    panels: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    jobs: list[dict[str, Any]] = Field(default_factory=list)
    notifications: list[dict[str, Any]] = Field(default_factory=list)
    health_checks: list[str] = Field(default_factory=list)
    has_migration: bool = False


class PlatformManifestOut(BaseModel):
    platform_contract_version: int
    modules: list[ModuleManifestOut]


class ActorContextIn(BaseModel):
    guild_id: str = Field(min_length=1, max_length=32)
    user_id: str | None = Field(default=None, max_length=32)
    role_ids: list[str] = Field(default_factory=list)
    discord_permissions: list[str] = Field(default_factory=list)
    channel_id: str | None = Field(default=None, max_length=32)
    category_id: str | None = Field(default=None, max_length=32)
    actor_type: Literal["user", "system"] = "user"
    is_guild_owner: bool = False
    resource_owner_id: str | None = Field(default=None, max_length=32)
    correlation_id: str = Field(min_length=1, max_length=80)


class GuildProfileIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    locale: str = Field(default="pt-BR", min_length=2, max_length=20)
    timezone: str = Field(default="America/Sao_Paulo", min_length=1, max_length=64)
    preferences: dict[str, Any] = Field(default_factory=dict)


class GuildProfileOut(GuildProfileIn):
    guild_id: str
    admin_role_ids: list[str] = Field(default_factory=list)


class GuildAdminRolesIn(BaseModel):
    role_ids: list[str] = Field(default_factory=list, max_length=100)
    actor: ActorContextIn


class GuildProfileUpdateIn(GuildProfileIn):
    actor: ActorContextIn


class AdministrativeActionIn(BaseModel):
    actor: ActorContextIn


class ModuleInstanceOut(BaseModel):
    guild_id: str
    module_key: str
    lifecycle: ModuleLifecycle
    runtime_mode: RuntimeMode
    contract_version: int
    domain_version: str
    published_config_version_id: int | None = None
    last_error: str | None = None


class LifecycleUpdateIn(BaseModel):
    lifecycle: ModuleLifecycle
    expected_lifecycle: ModuleLifecycle
    reason: str | None = Field(default=None, max_length=500)
    actor: ActorContextIn


class ConfigDraftIn(BaseModel):
    expected_revision: int = Field(ge=0)
    expected_published_version: int = Field(ge=0)
    schema_version: int = Field(ge=1)
    data: dict[str, Any]
    actor: ActorContextIn


class PermissionGrantIn(BaseModel):
    capability: str = Field(min_length=3, max_length=120)
    subject_type: Literal["role", "user", "everyone", "system"]
    subject_id: str = Field(default="", max_length=64)
    scope_type: Literal["guild", "resource", "channel", "category"] = "guild"
    scope_id: str = Field(default="", max_length=80)
    constraints: dict[str, Any] = Field(default_factory=dict)


class ConfigPublishIn(BaseModel):
    expected_revision: int = Field(ge=0)
    expected_published_version: int = Field(ge=0)
    grants: list[PermissionGrantIn] = Field(default_factory=list)
    actor: ActorContextIn


class ConfigRollbackIn(BaseModel):
    source_version: int = Field(ge=1)
    expected_published_version: int = Field(ge=0)
    actor: ActorContextIn


class ConfigDraftOut(BaseModel):
    guild_id: str
    module_key: str
    schema_version: int
    revision: int
    base_published_version: int
    data: dict[str, Any]
    updated_by: str | None = None
    updated_at: datetime


class ConfigVersionOut(BaseModel):
    id: int
    guild_id: str
    module_key: str
    version: int
    schema_version: int
    data: dict[str, Any]
    content_hash: str
    source_version: int | None = None
    published_by: str
    published_at: datetime


class AuthorizationIn(BaseModel):
    capability: str = Field(min_length=3, max_length=120)
    actor: ActorContextIn
    resource_type: str = Field(default="", max_length=80)
    resource_id: str = Field(default="", max_length=80)


class AuthorizationOut(BaseModel):
    allowed: bool
    reason: str


class PanelEnsureIn(BaseModel):
    panel_key: str = Field(min_length=1, max_length=80)
    resource_type: str = Field(default="", max_length=80)
    resource_id: str = Field(default="", max_length=80)
    definition_version: int = Field(default=1, ge=1)
    recovery_policy: Literal["automatic", "manual", "none"] = "manual"
    actor: ActorContextIn


class PanelUpdateIn(BaseModel):
    expected_render_revision: int = Field(ge=0)
    state: PanelState | None = None
    channel_id: str | None = Field(default=None, max_length=32)
    message_id: str | None = Field(default=None, max_length=32)
    config_version: int | None = Field(default=None, ge=1)
    last_error: str | None = Field(default=None, max_length=2000)
    verified: bool = False
    actor: ActorContextIn


class PanelOut(BaseModel):
    id: str
    guild_id: str
    module_key: str
    panel_key: str
    resource_type: str
    resource_id: str
    channel_id: str | None
    message_id: str | None
    definition_version: int
    config_version: int | None
    render_revision: int
    state: PanelState
    recovery_policy: str
    last_verified_at: datetime | None
    last_error: str | None


class TaskScheduleIn(BaseModel):
    job_key: str = Field(min_length=1, max_length=100)
    resource_type: str = Field(default="", max_length=80)
    resource_id: str = Field(default="", max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)
    due_at: datetime
    idempotency_key: str = Field(min_length=1, max_length=160)
    correlation_id: str = Field(min_length=1, max_length=80)
    max_attempts: int | None = Field(default=None, ge=1, le=50)


class WorkClaimIn(BaseModel):
    worker_id: str = Field(min_length=1, max_length=80)
    limit: int = Field(default=10, ge=1, le=100)
    lease_seconds: int = Field(default=60, ge=10, le=3600)


class WorkCompleteIn(BaseModel):
    worker_id: str = Field(min_length=1, max_length=80)
    result: dict[str, Any] = Field(default_factory=dict)
    external_id: str | None = Field(default=None, max_length=80)


class WorkFailIn(BaseModel):
    worker_id: str = Field(min_length=1, max_length=80)
    error: str = Field(min_length=1, max_length=2000)
    retry_at: datetime | None = None


class WorkItemOut(BaseModel):
    id: str
    guild_id: str
    module_key: str
    key: str
    resource_type: str
    resource_id: str
    payload: dict[str, Any]
    state: WorkState
    attempts: int
    max_attempts: int
    correlation_id: str


class DeliveryCreateIn(BaseModel):
    renderer_key: str = Field(min_length=1, max_length=100)
    destination_type: Literal["channel", "user", "panel"]
    destination_id: str = Field(min_length=1, max_length=80)
    resource_type: str = Field(default="", max_length=80)
    resource_id: str = Field(default="", max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=100, ge=0, le=1000)
    available_at: datetime
    idempotency_key: str = Field(min_length=1, max_length=160)
    correlation_id: str = Field(min_length=1, max_length=80)
    max_attempts: int = Field(default=5, ge=1, le=50)


class InteractionBeginIn(BaseModel):
    interaction_id: str = Field(min_length=1, max_length=32)
    module_key: str = Field(min_length=1, max_length=64)
    action_key: str = Field(min_length=1, max_length=100)
    resource_type: str = Field(default="", max_length=80)
    resource_id: str = Field(default="", max_length=80)
    correlation_id: str = Field(min_length=1, max_length=80)


class InteractionCompleteIn(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = Field(default=None, max_length=2000)


class InteractionReceiptOut(BaseModel):
    receipt_id: str
    duplicate: bool
    state: WorkState
    result: dict[str, Any]


class MigrationStartIn(BaseModel):
    migration_key: str = Field(min_length=1, max_length=100)
    target_mode: RuntimeMode = RuntimeMode.domain
    actor: ActorContextIn


class MigrationUpdateIn(BaseModel):
    state: MigrationState
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    counts: dict[str, Any] = Field(default_factory=dict)
    checksum: str | None = Field(default=None, max_length=128)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    actor: ActorContextIn


class MigrationOut(BaseModel):
    id: str
    guild_id: str
    module_key: str
    migration_key: str
    attempt: int
    source_mode: RuntimeMode
    target_mode: RuntimeMode
    state: MigrationState
    checkpoint: dict[str, Any]
    counts: dict[str, Any]
    checksum: str | None
    warnings: list[str]
    errors: list[str]


class HealthCheckOut(BaseModel):
    status: Literal["OK", "WARNING", "ERROR", "UNKNOWN"]
    code: str
    summary: str
    detail: str = ""
    action: str = ""
    reference: str | None = None
    checked_at: datetime


class AuditEntryOut(BaseModel):
    id: str
    guild_id: str
    actor_type: str
    actor_id: str | None
    module_key: str | None
    action: str
    resource_type: str
    resource_id: str | None
    before: dict[str, Any]
    after: dict[str, Any]
    config_version: int | None
    result: str
    correlation_id: str
    metadata: dict[str, Any]
    created_at: datetime
