from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, JsonType


def new_id() -> str:
    return str(uuid4())


class ModuleLifecycle(StrEnum):
    inactive = "inactive"
    active = "active"
    paused = "paused"
    degraded = "degraded"


class RuntimeMode(StrEnum):
    legacy = "legacy"
    shadow = "shadow"
    domain = "domain"


class PanelState(StrEnum):
    draft = "draft"
    ready = "ready"
    published = "published"
    paused = "paused"
    missing = "missing"
    error = "error"
    archived = "archived"


class WorkState(StrEnum):
    pending = "pending"
    claimed = "claimed"
    retry = "retry"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class MigrationState(StrEnum):
    inventory = "inventory"
    backfill = "backfill"
    validating = "validating"
    ready = "ready"
    cutover = "cutover"
    succeeded = "succeeded"
    failed = "failed"
    rolled_back = "rolled_back"


class GuildProfile(Base):
    __tablename__ = "guild_profiles"

    guild_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(120))
    locale: Mapped[str] = mapped_column(String(20), default="pt-BR", server_default="pt-BR")
    timezone: Mapped[str] = mapped_column(String(64), default="America/Sao_Paulo", server_default="America/Sao_Paulo")
    preferences: Mapped[dict] = mapped_column(JsonType, default=dict, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class GuildAdminRole(Base):
    __tablename__ = "guild_admin_roles"

    guild_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    role_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_by: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModuleInstance(Base):
    __tablename__ = "module_instances"
    __table_args__ = (
        UniqueConstraint("guild_id", "module_key", name="uq_module_instances_guild_module"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    module_key: Mapped[str] = mapped_column(String(64), index=True)
    lifecycle: Mapped[ModuleLifecycle] = mapped_column(
        Enum(ModuleLifecycle, native_enum=False, length=20), default=ModuleLifecycle.inactive, index=True
    )
    runtime_mode: Mapped[RuntimeMode] = mapped_column(
        Enum(RuntimeMode, native_enum=False, length=20), default=RuntimeMode.legacy, index=True
    )
    contract_version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    domain_version: Mapped[str] = mapped_column(String(32), default="legacy", server_default="legacy")
    published_config_version_id: Mapped[int | None] = mapped_column(Integer, index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    draft: Mapped["ModuleConfigDraft | None"] = relationship(back_populates="module_instance", uselist=False)
    config_versions: Mapped[list["ModuleConfigVersion"]] = relationship(back_populates="module_instance")


class ModuleConfigDraft(Base):
    __tablename__ = "module_config_drafts"
    __table_args__ = (
        UniqueConstraint("module_instance_id", name="uq_module_config_drafts_instance"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module_instance_id: Mapped[int] = mapped_column(ForeignKey("module_instances.id"), index=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    module_key: Mapped[str] = mapped_column(String(64), index=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    base_published_version: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    data: Mapped[dict] = mapped_column(JsonType, default=dict, server_default=text("'{}'"))
    updated_by: Mapped[str | None] = mapped_column(String(32), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    module_instance: Mapped[ModuleInstance] = relationship(back_populates="draft")


class ModuleConfigVersion(Base):
    __tablename__ = "module_config_versions"
    __table_args__ = (
        UniqueConstraint("module_instance_id", "version", name="uq_module_config_versions_instance_version"),
        UniqueConstraint("id", "module_instance_id", name="uq_module_config_versions_id_instance"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module_instance_id: Mapped[int] = mapped_column(ForeignKey("module_instances.id"), index=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    module_key: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JsonType, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64))
    source_version: Mapped[int | None] = mapped_column(Integer)
    published_by: Mapped[str] = mapped_column(String(32), index=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    module_instance: Mapped[ModuleInstance] = relationship(back_populates="config_versions")


class ModulePermissionGrant(Base):
    __tablename__ = "module_permission_grants"
    __table_args__ = (
        UniqueConstraint(
            "config_version_id", "capability", "subject_type", "subject_id", "scope_type", "scope_id",
            name="uq_module_permission_grants_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module_instance_id: Mapped[int] = mapped_column(ForeignKey("module_instances.id"), index=True)
    config_version_id: Mapped[int] = mapped_column(ForeignKey("module_config_versions.id"), index=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    module_key: Mapped[str] = mapped_column(String(64), index=True)
    capability: Mapped[str] = mapped_column(String(120), index=True)
    subject_type: Mapped[str] = mapped_column(String(20))
    subject_id: Mapped[str] = mapped_column(String(64), default="", server_default="")
    scope_type: Mapped[str] = mapped_column(String(20), default="guild", server_default="guild")
    scope_id: Mapped[str] = mapped_column(String(80), default="", server_default="")
    constraints: Mapped[dict] = mapped_column(JsonType, default=dict, server_default=text("'{}'"))


class PanelInstance(Base):
    __tablename__ = "panel_instances"
    __table_args__ = (
        UniqueConstraint(
            "guild_id", "module_key", "panel_key", "resource_type", "resource_id",
            name="uq_panel_instances_logical_identity",
        ),
        UniqueConstraint("guild_id", "channel_id", "message_id", name="uq_panel_instances_discord_message"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    module_key: Mapped[str] = mapped_column(String(64), index=True)
    panel_key: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str] = mapped_column(String(80), default="", server_default="")
    resource_id: Mapped[str] = mapped_column(String(80), default="", server_default="")
    channel_id: Mapped[str | None] = mapped_column(String(32), index=True)
    message_id: Mapped[str | None] = mapped_column(String(32), index=True)
    definition_version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    config_version: Mapped[int | None] = mapped_column(Integer)
    render_revision: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    state: Mapped[PanelState] = mapped_column(
        Enum(PanelState, native_enum=False, length=20), default=PanelState.draft, index=True
    )
    recovery_policy: Mapped[str] = mapped_column(String(20), default="manual", server_default="manual")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(32))
    updated_by: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AutomationTask(Base):
    __tablename__ = "automation_tasks"
    __table_args__ = (
        UniqueConstraint("guild_id", "module_key", "job_key", "idempotency_key", name="uq_automation_tasks_idempotency"),
        Index("ix_automation_tasks_claim", "state", "due_at", "lease_until"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    module_key: Mapped[str] = mapped_column(String(64), index=True)
    job_key: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str] = mapped_column(String(80), default="", server_default="")
    resource_id: Mapped[str] = mapped_column(String(80), default="", server_default="")
    payload: Mapped[dict] = mapped_column(JsonType, default=dict, server_default=text("'{}'"))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    state: Mapped[WorkState] = mapped_column(
        Enum(WorkState, native_enum=False, length=20), default=WorkState.pending, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, server_default=text("5"))
    lease_owner: Mapped[str | None] = mapped_column(String(80), index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    correlation_id: Mapped[str] = mapped_column(String(80), index=True)
    result: Mapped[dict] = mapped_column(JsonType, default=dict, server_default=text("'{}'"))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AutomationRun(Base):
    __tablename__ = "automation_runs"
    __table_args__ = (UniqueConstraint("task_id", "attempt", name="uq_automation_runs_task_attempt"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("automation_tasks.id"), index=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    module_key: Mapped[str] = mapped_column(String(64), index=True)
    job_key: Mapped[str] = mapped_column(String(100), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    state: Mapped[WorkState] = mapped_column(
        Enum(WorkState, native_enum=False, length=20), default=WorkState.claimed
    )
    worker_id: Mapped[str] = mapped_column(String(80))
    correlation_id: Mapped[str] = mapped_column(String(80), index=True)
    result: Mapped[dict] = mapped_column(JsonType, default=dict, server_default=text("'{}'"))
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeliveryOutbox(Base):
    __tablename__ = "delivery_outbox"
    __table_args__ = (
        UniqueConstraint("guild_id", "module_key", "idempotency_key", name="uq_delivery_outbox_idempotency"),
        Index("ix_delivery_outbox_claim", "state", "available_at", "lease_until"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    module_key: Mapped[str] = mapped_column(String(64), index=True)
    renderer_key: Mapped[str] = mapped_column(String(100))
    destination_type: Mapped[str] = mapped_column(String(30))
    destination_id: Mapped[str] = mapped_column(String(80))
    resource_type: Mapped[str] = mapped_column(String(80), default="", server_default="")
    resource_id: Mapped[str] = mapped_column(String(80), default="", server_default="")
    payload: Mapped[dict] = mapped_column(JsonType, default=dict, server_default=text("'{}'"))
    priority: Mapped[int] = mapped_column(Integer, default=100, server_default=text("100"))
    state: Mapped[WorkState] = mapped_column(
        Enum(WorkState, native_enum=False, length=20), default=WorkState.pending, index=True
    )
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, server_default=text("5"))
    lease_owner: Mapped[str | None] = mapped_column(String(80), index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    correlation_id: Mapped[str] = mapped_column(String(80), index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"
    __table_args__ = (UniqueConstraint("delivery_id", "attempt", name="uq_delivery_attempts_delivery_attempt"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    delivery_id: Mapped[str] = mapped_column(ForeignKey("delivery_outbox.id"), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    worker_id: Mapped[str] = mapped_column(String(80))
    state: Mapped[WorkState] = mapped_column(
        Enum(WorkState, native_enum=False, length=20), default=WorkState.claimed
    )
    external_id: Mapped[str | None] = mapped_column(String(80))
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEntry(Base):
    __tablename__ = "audit_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    actor_type: Mapped[str] = mapped_column(String(20), default="user", server_default="user")
    actor_id: Mapped[str | None] = mapped_column(String(64), index=True)
    module_key: Mapped[str | None] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str | None] = mapped_column(String(80), index=True)
    before: Mapped[dict] = mapped_column(JsonType, default=dict, server_default=text("'{}'"))
    after: Mapped[dict] = mapped_column(JsonType, default=dict, server_default=text("'{}'"))
    config_version: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[str] = mapped_column(String(30), default="success", server_default="success")
    correlation_id: Mapped[str] = mapped_column(String(80), index=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JsonType, default=dict, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ModuleMigrationRun(Base):
    __tablename__ = "module_migration_runs"
    __table_args__ = (
        UniqueConstraint("guild_id", "module_key", "migration_key", "attempt", name="uq_module_migration_runs_attempt"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    module_key: Mapped[str] = mapped_column(String(64), index=True)
    migration_key: Mapped[str] = mapped_column(String(100))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    source_mode: Mapped[RuntimeMode] = mapped_column(
        Enum(RuntimeMode, native_enum=False, length=20), default=RuntimeMode.legacy
    )
    target_mode: Mapped[RuntimeMode] = mapped_column(
        Enum(RuntimeMode, native_enum=False, length=20), default=RuntimeMode.domain
    )
    state: Mapped[MigrationState] = mapped_column(
        Enum(MigrationState, native_enum=False, length=20), default=MigrationState.inventory, index=True
    )
    checkpoint: Mapped[dict] = mapped_column(JsonType, default=dict, server_default=text("'{}'"))
    counts: Mapped[dict] = mapped_column(JsonType, default=dict, server_default=text("'{}'"))
    checksum: Mapped[str | None] = mapped_column(String(128))
    warnings: Mapped[list] = mapped_column(JsonType, default=list, server_default=text("'[]'"))
    errors: Mapped[list] = mapped_column(JsonType, default=list, server_default=text("'[]'"))
    started_by: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InteractionReceipt(Base):
    __tablename__ = "interaction_receipts"
    __table_args__ = (
        UniqueConstraint("guild_id", "interaction_id", name="uq_interaction_receipts_guild_interaction"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    interaction_id: Mapped[str] = mapped_column(String(32))
    module_key: Mapped[str] = mapped_column(String(64), index=True)
    action_key: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(80), default="", server_default="")
    resource_id: Mapped[str] = mapped_column(String(80), default="", server_default="")
    state: Mapped[WorkState] = mapped_column(
        Enum(WorkState, native_enum=False, length=20), default=WorkState.claimed
    )
    correlation_id: Mapped[str] = mapped_column(String(80), index=True)
    result: Mapped[dict] = mapped_column(JsonType, default=dict, server_default=text("'{}'"))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
