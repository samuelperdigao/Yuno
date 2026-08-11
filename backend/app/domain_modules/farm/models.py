from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.domain_modules.farm.domain import (
    CycleStatus,
    ParticipationMode,
    ProductStatus,
    ReviewDecision,
    SubmissionStatus,
    TemplateStatus,
    TicketStatus,
)


def new_key() -> str:
    return str(uuid4())


class FarmProduct(Base):
    __tablename__ = "farm_products"
    __table_args__ = (
        UniqueConstraint("guild_id", "active_key", name="uq_farm_products_guild_active_key"),
        CheckConstraint("precision >= 0 AND precision <= 3", name="ck_farm_products_precision"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(80))
    normalized_name: Mapped[str] = mapped_column(String(80), index=True)
    active_key: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(30))
    precision: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    status: Mapped[ProductStatus] = mapped_column(
        Enum(ProductStatus, native_enum=False, length=20), default=ProductStatus.active, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    created_by: Mapped[str] = mapped_column(String(32))
    archived_by: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FarmTemplate(Base):
    __tablename__ = "farm_templates"
    __table_args__ = (
        UniqueConstraint("guild_id", "template_key", "version", name="uq_farm_templates_key_version"),
        CheckConstraint("version > 0", name="ck_farm_templates_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    template_key: Mapped[str] = mapped_column(String(36), default=new_key, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TemplateStatus] = mapped_column(
        Enum(TemplateStatus, native_enum=False, length=20), default=TemplateStatus.draft, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    created_by: Mapped[str] = mapped_column(String(32))
    activated_by: Mapped[str | None] = mapped_column(String(32))
    archived_by: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list["FarmTemplateItem"]] = relationship(back_populates="template", cascade="all, delete-orphan")


class FarmTemplateItem(Base):
    __tablename__ = "farm_template_items"
    __table_args__ = (
        UniqueConstraint("template_id", "product_id", name="uq_farm_template_items_product"),
        CheckConstraint("quantity > 0", name="ck_farm_template_items_quantity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("farm_templates.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("farm_products.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    position: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))

    template: Mapped[FarmTemplate] = relationship(back_populates="items")
    product: Mapped[FarmProduct] = relationship()


class FarmCycle(Base):
    __tablename__ = "farm_cycles"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_farm_cycles_dates"),
        CheckConstraint("review_deadline_at IS NULL OR review_deadline_at >= ends_at", name="ck_farm_cycles_review_deadline"),
        Index("ix_farm_cycles_guild_status_start", "guild_id", "status", "starts_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("farm_templates.id"), index=True)
    config_version_id: Mapped[int] = mapped_column(ForeignKey("module_config_versions.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    review_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    participation_mode: Mapped[ParticipationMode] = mapped_column(Enum(ParticipationMode, native_enum=False, length=20))
    proof_required: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    status: Mapped[CycleStatus] = mapped_column(
        Enum(CycleStatus, native_enum=False, length=20), default=CycleStatus.draft, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    created_by: Mapped[str] = mapped_column(String(32))
    cancelled_by: Mapped[str | None] = mapped_column(String(32))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    template: Mapped[FarmTemplate] = relationship()
    goals: Mapped[list["FarmCycleGoal"]] = relationship(back_populates="cycle", cascade="all, delete-orphan")


class FarmCycleGoal(Base):
    __tablename__ = "farm_cycle_goals"
    __table_args__ = (
        UniqueConstraint("cycle_id", "product_id", name="uq_farm_cycle_goals_product"),
        CheckConstraint("quantity_required > 0", name="ck_farm_cycle_goals_quantity"),
        CheckConstraint("precision >= 0 AND precision <= 3", name="ck_farm_cycle_goals_precision"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("farm_cycles.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("farm_products.id"), index=True)
    product_name: Mapped[str] = mapped_column(String(80))
    unit: Mapped[str] = mapped_column(String(30))
    precision: Mapped[int] = mapped_column(Integer)
    quantity_required: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    position: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))

    cycle: Mapped[FarmCycle] = relationship(back_populates="goals")
    product: Mapped[FarmProduct] = relationship()


class FarmCycleParticipant(Base):
    __tablename__ = "farm_cycle_participants"
    __table_args__ = (UniqueConstraint("cycle_id", "member_id", name="uq_farm_cycle_participants_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("farm_cycles.id"), index=True)
    member_id: Mapped[str] = mapped_column(String(32), index=True)
    member_display_name: Mapped[str] = mapped_column(String(120))
    assigned_by: Mapped[str] = mapped_column(String(32))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FarmCycleTicket(Base):
    __tablename__ = "farm_cycle_tickets"
    __table_args__ = (
        UniqueConstraint("cycle_id", "member_id", name="uq_farm_cycle_tickets_member"),
        Index("ix_farm_cycle_tickets_guild_member_status", "guild_id", "member_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("farm_cycles.id"), index=True)
    member_id: Mapped[str] = mapped_column(String(32), index=True)
    member_display_name: Mapped[str] = mapped_column(String(120))
    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus, native_enum=False, length=20), default=TicketStatus.open, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    created_by: Mapped[str] = mapped_column(String(32), index=True)
    cancelled_by: Mapped[str | None] = mapped_column(String(32))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    cycle: Mapped[FarmCycle] = relationship()
    submissions: Mapped[list["FarmSubmission"]] = relationship(back_populates="ticket")


class FarmSubmission(Base):
    __tablename__ = "farm_submissions"
    __table_args__ = (
        UniqueConstraint("guild_id", "idempotency_key", name="uq_farm_submissions_idempotency"),
        Index("ix_farm_submissions_guild_status_created", "guild_id", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("farm_cycle_tickets.id"), index=True)
    correction_of_submission_id: Mapped[int | None] = mapped_column(ForeignKey("farm_submissions.id"), index=True)
    status: Mapped[SubmissionStatus] = mapped_column(
        Enum(SubmissionStatus, native_enum=False, length=24), default=SubmissionStatus.submitted, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    submitted_by: Mapped[str] = mapped_column(String(32), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    claimed_by: Mapped[str | None] = mapped_column(String(32), index=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    ticket: Mapped[FarmCycleTicket] = relationship(back_populates="submissions")
    items: Mapped[list["FarmSubmissionItem"]] = relationship(back_populates="submission", cascade="all, delete-orphan")
    proofs: Mapped[list["FarmProof"]] = relationship(back_populates="submission", cascade="all, delete-orphan")
    reviews: Mapped[list["FarmReview"]] = relationship(back_populates="submission")


class FarmSubmissionItem(Base):
    __tablename__ = "farm_submission_items"
    __table_args__ = (
        UniqueConstraint("submission_id", "goal_id", name="uq_farm_submission_items_goal"),
        CheckConstraint("quantity > 0", name="ck_farm_submission_items_quantity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("farm_submissions.id"), index=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("farm_cycle_goals.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))

    submission: Mapped[FarmSubmission] = relationship(back_populates="items")
    goal: Mapped[FarmCycleGoal] = relationship()


class FarmProof(Base):
    __tablename__ = "farm_proofs"
    __table_args__ = (
        UniqueConstraint("guild_id", "message_id", "attachment_id", name="uq_farm_proofs_discord_attachment"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("farm_submissions.id"), index=True)
    channel_id: Mapped[str] = mapped_column(String(32))
    message_id: Mapped[str] = mapped_column(String(32), index=True)
    attachment_id: Mapped[str | None] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String(120))
    submitted_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    submission: Mapped[FarmSubmission] = relationship(back_populates="proofs")


class FarmReview(Base):
    __tablename__ = "farm_reviews"
    __table_args__ = (
        UniqueConstraint("guild_id", "idempotency_key", name="uq_farm_reviews_idempotency"),
        Index("ix_farm_reviews_guild_submission_created", "guild_id", "submission_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("farm_submissions.id"), index=True)
    decision: Mapped[ReviewDecision] = mapped_column(Enum(ReviewDecision, native_enum=False, length=24), index=True)
    reviewer_id: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    submission: Mapped[FarmSubmission] = relationship(back_populates="reviews")
