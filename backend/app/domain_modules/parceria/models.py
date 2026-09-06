from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.domain_modules.parceria.domain import ParceriaStatus, PublicationStatus, RegistrationAttemptStatus


def new_id() -> str:
    return str(uuid4())


class ParceriaFamily(Base):
    __tablename__ = "parceria_domain_families"
    __table_args__ = (
        UniqueConstraint("guild_id", "name_normalized", name="uq_parceria_domain_family_guild_name"),
        UniqueConstraint("guild_id", "legacy_id", name="uq_parceria_domain_family_guild_legacy"),
        Index("ix_parceria_domain_family_guild_active", "guild_id", "active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(100))
    name_normalized: Mapped[str] = mapped_column(String(100), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    legacy_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Parceria(Base):
    __tablename__ = "parceria_domain_partnerships"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive', 'publication_pending', 'degraded')",
            name="ck_parceria_domain_status",
        ),
        CheckConstraint("publication_revision >= 1", name="ck_parceria_domain_publication_revision"),
        UniqueConstraint("guild_id", "legacy_id", name="uq_parceria_domain_partnership_guild_legacy"),
        Index("ix_parceria_domain_guild_status", "guild_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    family_id: Mapped[str] = mapped_column(ForeignKey("parceria_domain_families.id"), index=True)
    status: Mapped[ParceriaStatus] = mapped_column(
        Enum(ParceriaStatus, native_enum=False, length=24),
        default=ParceriaStatus.publication_pending,
        index=True,
    )
    registered_by: Mapped[str] = mapped_column(String(32), index=True)
    image_asset_id: Mapped[str] = mapped_column(ForeignKey("parceria_domain_images.id"), index=True)
    public_channel_id: Mapped[str | None] = mapped_column(String(32), index=True)
    public_message_id: Mapped[str | None] = mapped_column(String(32), index=True)
    publication_revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    legacy_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ParceriaProduct(Base):
    __tablename__ = "parceria_domain_products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    parceria_id: Mapped[str] = mapped_column(ForeignKey("parceria_domain_partnerships.id", ondelete="CASCADE"), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ParceriaContact(Base):
    __tablename__ = "parceria_domain_contacts"
    __table_args__ = (
        UniqueConstraint("parceria_id", "position", name="uq_parceria_domain_contact_position"),
        CheckConstraint("position BETWEEN 1 AND 2", name="ck_parceria_domain_contact_position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    parceria_id: Mapped[str] = mapped_column(ForeignKey("parceria_domain_partnerships.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    value: Mapped[str] = mapped_column(String(150))


class ParceriaImage(Base):
    __tablename__ = "parceria_domain_images"
    __table_args__ = (UniqueConstraint("guild_id", "storage_key", name="uq_parceria_domain_image_storage"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    storage_key: Mapped[str] = mapped_column(String(255))
    storage_url: Mapped[str | None] = mapped_column(String(1000))
    content_type: Mapped[str] = mapped_column(String(40))
    size_bytes: Mapped[int] = mapped_column(Integer)
    source_kind: Mapped[str] = mapped_column(String(20), default="upload", server_default="upload")
    checksum: Mapped[str | None] = mapped_column(String(128), index=True)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    uploaded_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RegistrationAttempt(Base):
    __tablename__ = "parceria_registration_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('awaiting_image', 'completed', 'expired', 'cancelled')",
            name="ck_parceria_registration_attempt_status",
        ),
        Index("ix_parceria_registration_attempt_expiry", "guild_id", "status", "expires_at"),
        UniqueConstraint("guild_id", "idempotency_key", name="uq_parceria_registration_attempt_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    actor_id: Mapped[str] = mapped_column(String(32), index=True)
    channel_id: Mapped[str] = mapped_column(String(32), index=True)
    family_name: Mapped[str] = mapped_column(String(100))
    family_normalized: Mapped[str] = mapped_column(String(100), index=True)
    product_name: Mapped[str] = mapped_column(String(100))
    contact_01: Mapped[str | None] = mapped_column(String(150))
    contact_02: Mapped[str | None] = mapped_column(String(150))
    image_asset_id: Mapped[str | None] = mapped_column(ForeignKey("parceria_domain_images.id"), index=True)
    status: Mapped[RegistrationAttemptStatus] = mapped_column(
        Enum(RegistrationAttemptStatus, native_enum=False, length=20),
        default=RegistrationAttemptStatus.awaiting_image,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    correlation_id: Mapped[str] = mapped_column(String(160), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    completed_parceria_id: Mapped[str | None] = mapped_column(ForeignKey("parceria_domain_partnerships.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ParceriaPublication(Base):
    __tablename__ = "parceria_domain_publications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'published', 'missing', 'archived', 'failed')",
            name="ck_parceria_domain_publication_status",
        ),
        UniqueConstraint("guild_id", "idempotency_key", name="uq_parceria_domain_publication_idempotency"),
        Index("ix_parceria_domain_publication_current", "guild_id", "parceria_id", "status"),
        CheckConstraint("revision >= 1", name="ck_parceria_domain_publication_revision"),
        UniqueConstraint("guild_id", "parceria_id", "revision", name="uq_parceria_domain_publication_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    parceria_id: Mapped[str] = mapped_column(ForeignKey("parceria_domain_partnerships.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[str] = mapped_column(String(32))
    message_id: Mapped[str | None] = mapped_column(String(32))
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[PublicationStatus] = mapped_column(
        Enum(PublicationStatus, native_enum=False, length=20),
        default=PublicationStatus.pending,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(160))
    last_error: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
