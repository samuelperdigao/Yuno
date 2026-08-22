from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, JsonType
from app.domain_modules.meta.domain import (
    CycleState,
    GoalEndReason,
    GoalState,
    ObjectiveKind,
    ParticipantRemovalReason,
    ParticipationKind,
    RecurrenceKind,
)


def new_id() -> str:
    return str(uuid4())


class MetaGuildSettings(Base):
    __tablename__ = "meta_guild_settings"

    guild_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    notice_channel_id: Mapped[str | None] = mapped_column(String(32))
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    updated_by: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MetaProduct(Base):
    __tablename__ = "meta_products"
    __table_args__ = (
        UniqueConstraint("guild_id", "active_key", name="uq_meta_products_guild_active_key"),
        CheckConstraint(
            "last_suggested_quantity IS NULL OR last_suggested_quantity > 0",
            name="ck_meta_products_suggested_positive",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(100))
    normalized_name: Mapped[str] = mapped_column(String(100), index=True)
    active_key: Mapped[str | None] = mapped_column(String(100))
    unit: Mapped[str] = mapped_column(String(30), default="unidade")
    last_suggested_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 3))
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MetaGoal(Base):
    __tablename__ = "meta_goals"
    __table_args__ = (
        UniqueConstraint("guild_id", "created_sequence", name="uq_meta_goals_guild_sequence"),
        UniqueConstraint("guild_id", "creation_key", name="uq_meta_goals_creation_key"),
        CheckConstraint("version > 0", name="ck_meta_goals_version"),
        Index("ix_meta_goals_selectable", "guild_id", "state", "created_sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    created_sequence: Mapped[int] = mapped_column(BigInteger)
    creation_key: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(120))
    state: Mapped[GoalState] = mapped_column(
        Enum(GoalState, native_enum=False, length=24), default=GoalState.scheduled, index=True
    )
    recurrence: Mapped[RecurrenceKind] = mapped_column(
        Enum(RecurrenceKind, native_enum=False, length=16), index=True
    )
    recurrence_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    current_config_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("meta_goal_config_versions.id", ondelete="RESTRICT"), index=True
    )
    future_config_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("meta_goal_config_versions.id", ondelete="RESTRICT"), index=True
    )
    next_transition_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    end_reason: Mapped[GoalEndReason | None] = mapped_column(
        Enum(GoalEndReason, native_enum=False, length=20)
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MetaGoalConfigVersion(Base):
    __tablename__ = "meta_goal_config_versions"
    __table_args__ = (
        UniqueConstraint("goal_id", "version", name="uq_meta_goal_config_version"),
        CheckConstraint("version > 0", name="ck_meta_goal_config_version_positive"),
        CheckConstraint(
            "weekday IS NULL OR (weekday >= 0 AND weekday <= 6)", name="ck_meta_goal_weekday"
        ),
        CheckConstraint(
            "month_day IS NULL OR (month_day >= 1 AND month_day <= 31)",
            name="ck_meta_goal_month_day",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("meta_goals.id", ondelete="CASCADE"), index=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(120))
    recurrence: Mapped[RecurrenceKind] = mapped_column(
        Enum(RecurrenceKind, native_enum=False, length=16)
    )
    timezone: Mapped[str] = mapped_column(String(64))
    daily_time: Mapped[str | None] = mapped_column(String(5))
    weekday: Mapped[int | None] = mapped_column(Integer)
    month_day: Mapped[int | None] = mapped_column(Integer)
    scheduled_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    participation: Mapped[ParticipationKind] = mapped_column(
        Enum(ParticipationKind, native_enum=False, length=20)
    )
    notice_text: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    roles: Mapped[list["MetaGoalConfigRole"]] = relationship(cascade="all, delete-orphan")
    objectives: Mapped[list["MetaGoalConfigObjective"]] = relationship(cascade="all, delete-orphan")


class MetaGoalConfigRole(Base):
    __tablename__ = "meta_goal_config_roles"
    __table_args__ = (UniqueConstraint("config_version_id", "role_id", name="uq_meta_goal_config_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config_version_id: Mapped[int] = mapped_column(
        ForeignKey("meta_goal_config_versions.id", ondelete="CASCADE"), index=True
    )
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    role_id: Mapped[str] = mapped_column(String(32), index=True)


class MetaGoalConfigObjective(Base):
    __tablename__ = "meta_goal_config_objectives"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'item' AND item_quantity IS NOT NULL AND item_quantity > 0 AND money_amount IS NULL) "
            "OR (kind = 'money' AND money_amount IS NOT NULL AND money_amount > 0 AND item_quantity IS NULL)",
            name="ck_meta_config_objective_shape",
        ),
        UniqueConstraint("config_version_id", "position", name="uq_meta_config_objective_position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config_version_id: Mapped[int] = mapped_column(
        ForeignKey("meta_goal_config_versions.id", ondelete="CASCADE"), index=True
    )
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[ObjectiveKind] = mapped_column(Enum(ObjectiveKind, native_enum=False, length=10))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("meta_products.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(100))
    unit: Mapped[str | None] = mapped_column(String(30))
    item_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 3))
    money_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    position: Mapped[int] = mapped_column(Integer)


class MetaAdminDraft(Base):
    __tablename__ = "meta_admin_drafts"
    __table_args__ = (
        UniqueConstraint("guild_id", "admin_id", name="uq_meta_admin_draft"),
        CheckConstraint("revision > 0", name="ck_meta_admin_draft_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    admin_id: Mapped[str] = mapped_column(String(32), index=True)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("meta_goals.id", ondelete="SET NULL"))
    expected_goal_version: Mapped[int | None] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    step: Mapped[str] = mapped_column(String(32), default="name")
    data: Mapped[dict] = mapped_column(JsonType, default=dict)
    submitted_goal_id: Mapped[int | None] = mapped_column(ForeignKey("meta_goals.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MetaCycle(Base):
    __tablename__ = "meta_cycles"
    __table_args__ = (
        UniqueConstraint("goal_id", "cycle_key", name="uq_meta_cycle_key"),
        UniqueConstraint("guild_id", "notice_reference", name="uq_meta_cycle_notice_reference"),
        CheckConstraint("ends_at > starts_at", name="ck_meta_cycle_dates"),
        Index("ix_meta_cycles_guild_state_ends", "guild_id", "state", "ends_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("meta_goals.id", ondelete="CASCADE"), index=True)
    config_version_id: Mapped[int] = mapped_column(
        ForeignKey("meta_goal_config_versions.id", ondelete="RESTRICT"), index=True
    )
    cycle_key: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(120))
    notice_text: Mapped[str] = mapped_column(Text)
    state: Mapped[CycleState] = mapped_column(
        Enum(CycleState, native_enum=False, length=24), default=CycleState.launch_pending, index=True
    )
    timezone: Mapped[str] = mapped_column(String(64))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    notice_channel_id: Mapped[str] = mapped_column(String(32))
    notice_message_id: Mapped[str | None] = mapped_column(String(32), index=True)
    notice_reference: Mapped[str] = mapped_column(String(100))
    end_reason: Mapped[GoalEndReason | None] = mapped_column(
        Enum(GoalEndReason, native_enum=False, length=20)
    )
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    objectives: Mapped[list["MetaCycleObjective"]] = relationship(cascade="all, delete-orphan")
    participants: Mapped[list["MetaCycleParticipant"]] = relationship(cascade="all, delete-orphan")


class MetaCycleObjective(Base):
    __tablename__ = "meta_cycle_objectives"
    __table_args__ = (
        UniqueConstraint("cycle_id", "position", name="uq_meta_cycle_objective_position"),
        CheckConstraint(
            "(kind = 'item' AND item_quantity IS NOT NULL AND item_quantity > 0 AND money_amount IS NULL) "
            "OR (kind = 'money' AND money_amount IS NOT NULL AND money_amount > 0 AND item_quantity IS NULL)",
            name="ck_meta_cycle_objective_shape",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("meta_cycles.id", ondelete="CASCADE"), index=True)
    kind: Mapped[ObjectiveKind] = mapped_column(Enum(ObjectiveKind, native_enum=False, length=10))
    product_id: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(100))
    unit: Mapped[str | None] = mapped_column(String(30))
    item_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 3))
    money_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    position: Mapped[int] = mapped_column(Integer)


class MetaCycleParticipant(Base):
    __tablename__ = "meta_cycle_participants"
    __table_args__ = (
        UniqueConstraint("cycle_id", "member_id", name="uq_meta_cycle_participant_member"),
        Index(
            "uq_meta_active_participant",
            "guild_id",
            "member_id",
            unique=True,
            postgresql_where=text("active = true"),
            sqlite_where=text("active = 1"),
        ),
        Index("ix_meta_cycle_participant_cycle_active", "cycle_id", "active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("meta_cycles.id", ondelete="CASCADE"), index=True)
    member_id: Mapped[str] = mapped_column(String(32), index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    role_ids: Mapped[list[str]] = mapped_column(JsonType, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), index=True)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removal_reason: Mapped[ParticipantRemovalReason | None] = mapped_column(
        Enum(ParticipantRemovalReason, native_enum=False, length=32)
    )


class MetaIntegrationEvent(Base):
    __tablename__ = "meta_integration_events"
    __table_args__ = (
        UniqueConstraint("guild_id", "sequence", name="uq_meta_event_sequence"),
        UniqueConstraint("guild_id", "deduplication_key", name="uq_meta_event_deduplication"),
        Index("ix_meta_events_read", "guild_id", "sequence", "event_type"),
        CheckConstraint("sequence > 0", name="ck_meta_event_sequence_positive"),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    sequence: Mapped[int] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    event_version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    causation_id: Mapped[str] = mapped_column(String(100), index=True)
    deduplication_key: Mapped[str] = mapped_column(String(180))
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
