from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.domain_modules.tags.domain import TagSyncRunMode, TagSyncRunStatus, TagSyncState


def new_id() -> str:
    return str(uuid4())


class TagRoleBindingDraft(Base):
    __tablename__ = "tag_role_binding_drafts"
    __table_args__ = (
        UniqueConstraint("module_instance_id", "discord_role_id", name="uq_tag_draft_instance_role"),
        Index("ix_tag_draft_guild_role", "guild_id", "discord_role_id"),
        CheckConstraint("discord_role_id <> guild_id", name="ck_tag_draft_not_everyone"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    module_instance_id: Mapped[int] = mapped_column(ForeignKey("module_instances.id", ondelete="CASCADE"), index=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    discord_role_id: Mapped[str] = mapped_column(String(32), index=True)
    tag: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_by: Mapped[str] = mapped_column(String(32))
    updated_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TagRoleBindingVersion(Base):
    __tablename__ = "tag_role_binding_versions"
    __table_args__ = (
        UniqueConstraint("config_version_id", "discord_role_id", name="uq_tag_version_config_role"),
        Index("ix_tag_version_effective", "module_instance_id", "config_version_id", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    config_version_id: Mapped[int] = mapped_column(ForeignKey("module_config_versions.id", ondelete="CASCADE"), index=True)
    module_instance_id: Mapped[int] = mapped_column(ForeignKey("module_instances.id", ondelete="CASCADE"), index=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    discord_role_id: Mapped[str] = mapped_column(String(32), index=True)
    tag: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class TagSyncIntent(Base):
    __tablename__ = "tag_sync_intents"
    __table_args__ = (
        UniqueConstraint("guild_id", "discord_user_id", name="uq_tag_intent_guild_user"),
        Index("ix_tag_intent_queue", "guild_id", "state", "updated_at"),
        CheckConstraint("desired_revision >= applied_revision", name="ck_tag_intent_revisions"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    discord_user_id: Mapped[str] = mapped_column(String(32), index=True)
    desired_revision: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    applied_revision: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    observed_fingerprint: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[TagSyncState] = mapped_column(Enum(TagSyncState, native_enum=False, length=20), default=TagSyncState.pending, index=True)
    processing_token: Mapped[str | None] = mapped_column(String(64), index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    winning_role_id: Mapped[str | None] = mapped_column(String(32))
    expected_nickname_hash: Mapped[str | None] = mapped_column(String(64))
    applied_nickname_hash: Mapped[str | None] = mapped_column(String(64))
    last_result: Mapped[str | None] = mapped_column(String(80))
    last_error_code: Mapped[str | None] = mapped_column(String(120))
    last_error_detail: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    correlation_id: Mapped[str | None] = mapped_column(String(80), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TagSyncRun(Base):
    __tablename__ = "tag_sync_runs"
    __table_args__ = (
        Index("ix_tag_run_guild_status_created", "guild_id", "status", "created_at"),
        Index(
            "uq_tag_run_active_guild",
            "guild_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'planning', 'running')"),
            sqlite_where=text("status IN ('pending', 'planning', 'running')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    mode: Mapped[TagSyncRunMode] = mapped_column(Enum(TagSyncRunMode, native_enum=False, length=20), default=TagSyncRunMode.effective)
    reason: Mapped[str] = mapped_column(String(80), index=True)
    config_version_id: Mapped[int | None] = mapped_column(ForeignKey("module_config_versions.id"), index=True)
    cursor_user_id: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[TagSyncRunStatus] = mapped_column(Enum(TagSyncRunStatus, native_enum=False, length=32), default=TagSyncRunStatus.pending, index=True)
    total_items: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    planned_items: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    succeeded_items: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    skipped_items: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    blocked_items: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    failed_items: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    requested_by: Mapped[str | None] = mapped_column(String(32))
    correlation_id: Mapped[str] = mapped_column(String(80), index=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TagSyncRunItem(Base):
    __tablename__ = "tag_sync_run_items"
    __table_args__ = (
        UniqueConstraint("run_id", "discord_user_id", name="uq_tag_run_item_user"),
        Index("ix_tag_run_item_progress", "run_id", "state"),
        Index("ix_tag_run_item_guild_user", "guild_id", "discord_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("tag_sync_runs.id", ondelete="CASCADE"), index=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    discord_user_id: Mapped[str] = mapped_column(String(32), index=True)
    intent_revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[TagSyncState] = mapped_column(Enum(TagSyncState, native_enum=False, length=20), default=TagSyncState.pending, index=True)
    result_code: Mapped[str | None] = mapped_column(String(120))
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
