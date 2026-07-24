from datetime import datetime
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass
from uuid import uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db import Base


JsonType = JSON().with_variant(JSONB, "postgresql")


class LicenseStatus(StrEnum):
    pending = "pending"
    active = "active"
    blocked = "blocked"
    revoked = "revoked"


class RecordStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    open = "open"
    in_progress = "in_progress"
    done = "done"
    cancelled = "cancelled"


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discord_user_id: Mapped[str | None] = mapped_column(String(32), index=True)
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    name: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    licenses: Mapped[list["License"]] = relationship(back_populates="customer")


class License(Base):
    __tablename__ = "licenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: uuid4().hex, index=True)
    status: Mapped[LicenseStatus] = mapped_column(Enum(LicenseStatus), default=LicenseStatus.pending, index=True)
    guild_id: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    guild_name: Mapped[str | None] = mapped_column(String(120))
    owner_discord_id: Mapped[str | None] = mapped_column(String(32), index=True)
    payment_provider: Mapped[str | None] = mapped_column(String(40))
    payment_reference: Mapped[str | None] = mapped_column(String(120), unique=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    customer: Mapped[Customer | None] = relationship(back_populates="licenses")


class GuildConfig(Base):
    __tablename__ = "guild_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    guild_name: Mapped[str | None] = mapped_column(String(120))
    admin_role_ids: Mapped[list[str]] = mapped_column(JsonType, default=list)
    log_channel_id: Mapped[str | None] = mapped_column(String(32))
    modules: Mapped[dict] = mapped_column(JsonType, default=dict)
    command_permissions: Mapped[dict] = mapped_column(JsonType, default=dict)
    messages: Mapped[dict] = mapped_column(JsonType, default=dict)
    settings: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("guild_id", "name", name="uq_products_guild_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(120))
    unit: Mapped[str] = mapped_column(String(40), default="unidade")
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SystemRecord(Base):
    __tablename__ = "system_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    module: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[RecordStatus] = mapped_column(Enum(RecordStatus), default=RecordStatus.pending, index=True)
    title: Mapped[str] = mapped_column(String(160))
    requester_id: Mapped[str] = mapped_column(String(32), index=True)
    reviewer_id: Mapped[str | None] = mapped_column(String(32), index=True)
    channel_id: Mapped[str | None] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str | None] = mapped_column(String(32), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class PaymentEvent(Base):
    __tablename__ = "payment_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    reference: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    raw_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Ausencia(Base):
    __tablename__ = "ausencias"

    guild_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    nome: Mapped[str | None] = mapped_column(String(120))
    dias: Mapped[int] = mapped_column(Integer)
    motivo: Mapped[str] = mapped_column(Text)
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fim: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    avisado: Mapped[int] = mapped_column(Integer, default=0, index=True)
    message_id: Mapped[str | None] = mapped_column(String(32))


class FarmTicketConfig(Base):
    __tablename__ = "farm_ticket_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    category_ids: Mapped[list[str]] = mapped_column(JsonType, default=list)
    admin_role_ids: Mapped[list[str]] = mapped_column(JsonType, default=list)
    log_channel_id: Mapped[str] = mapped_column(String(32))
    panel_channel_id: Mapped[str] = mapped_column(String(32))
    folders_category_id: Mapped[str | None] = mapped_column(String(32))
    participant_role_ids: Mapped[list[str]] = mapped_column(JsonType, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FarmWeeklyGoal(Base):
    __tablename__ = "farm_weekly_goals"
    __table_args__ = (UniqueConstraint("guild_id", "week_id", name="uq_farm_weekly_goal_guild_week"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    week_id: Mapped[str] = mapped_column(String(12), index=True)
    items: Mapped[list[dict]] = mapped_column(JsonType, default=list)
    active: Mapped[bool] = mapped_column(default=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FarmTicket(Base):
    __tablename__ = "farm_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    week_id: Mapped[str] = mapped_column(String(12), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    member_name: Mapped[str] = mapped_column(String(120))
    channel_id: Mapped[str | None] = mapped_column(String(32), index=True)
    panel_message_id: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(40), default="reservado", index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(32), index=True)
    goal_items: Mapped[list[dict]] = mapped_column(JsonType, default=list)
    progress: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_by: Mapped[str | None] = mapped_column(String(32))
    finalization_reason: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    entries: Mapped[list["FarmTicketEntry"]] = relationship(back_populates="ticket")
    actions: Mapped[list["FarmTicketAction"]] = relationship(back_populates="ticket")


class FarmTicketEntry(Base):
    __tablename__ = "farm_ticket_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("farm_tickets.id"), index=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    values: Mapped[dict] = mapped_column(JsonType, default=dict)
    proof_channel_id: Mapped[str] = mapped_column(String(32))
    proof_message_id: Mapped[str] = mapped_column(String(32))
    proof_url: Mapped[str] = mapped_column(Text)
    log_proof_url: Mapped[str | None] = mapped_column(Text)
    observacao: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="registrado", index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(32))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    ticket: Mapped[FarmTicket] = relationship(back_populates="entries")


class FarmTicketAction(Base):
    __tablename__ = "farm_ticket_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("farm_tickets.id"), index=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(32), index=True)
    event_id: Mapped[str | None] = mapped_column(String(80), index=True)
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    log_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    log_message_id: Mapped[str | None] = mapped_column(String(32))
    log_attempts: Mapped[int] = mapped_column(Integer, default=0)

    ticket: Mapped[FarmTicket | None] = relationship(back_populates="actions")
