from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.domain_modules.registration.domain import (
    CompensationState,
    OrganizationMemberStatus,
    RegistrationRequestStatus,
)


def new_id() -> str:
    return str(uuid4())


class OrganizationMember(Base):
    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint(
            "guild_id", "discord_user_id", name="uq_organization_members_guild_user"
        ),
        Index(
            "uq_organization_members_active_player_id",
            "guild_id",
            "player_id_normalized",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "ix_organization_members_guild_status_updated",
            "guild_id",
            "status",
            "updated_at",
        ),
        Index(
            "ix_organization_members_active_pagination",
            "guild_id",
            "status",
            "discord_user_id",
        ),
        CheckConstraint("status IN ('active', 'inactive')", name="ck_organization_members_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    discord_user_id: Mapped[str] = mapped_column(String(32), index=True)
    player_id_original: Mapped[str] = mapped_column(String(120))
    player_id_normalized: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[OrganizationMemberStatus] = mapped_column(
        Enum(OrganizationMemberStatus, native_enum=False, length=20),
        default=OrganizationMemberStatus.active,
        index=True,
    )
    approved_request_id: Mapped[str | None] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RegistrationRequest(Base):
    __tablename__ = "registration_requests"
    __table_args__ = (
        Index(
            "uq_registration_requests_open_user",
            "guild_id",
            "discord_user_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'processing')"),
            sqlite_where=text("status IN ('pending', 'processing')"),
        ),
        Index(
            "uq_registration_requests_processing_player_id",
            "guild_id",
            "player_id_normalized",
            unique=True,
            postgresql_where=text("status = 'processing'"),
            sqlite_where=text("status = 'processing'"),
        ),
        Index(
            "ix_registration_requests_guild_status_created",
            "guild_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_registration_requests_guild_lease",
            "guild_id",
            "status",
            "processing_lease_until",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'approved', 'rejected')",
            name="ck_registration_requests_status",
        ),
        CheckConstraint(
            "compensation_state IN ('none', 'prepared', 'required', 'complete', 'failed')",
            name="ck_registration_requests_compensation_state",
        ),
        CheckConstraint("revision > 0", name="ck_registration_requests_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    discord_user_id: Mapped[str] = mapped_column(String(32), index=True)
    submitted_name: Mapped[str] = mapped_column(String(120))
    player_id_original: Mapped[str] = mapped_column(String(120))
    player_id_normalized: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[RegistrationRequestStatus] = mapped_column(
        Enum(RegistrationRequestStatus, native_enum=False, length=20),
        default=RegistrationRequestStatus.pending,
        index=True,
    )
    config_version_submitted_id: Mapped[int] = mapped_column(
        ForeignKey("module_config_versions.id"), index=True
    )
    config_version_reviewed_id: Mapped[int | None] = mapped_column(
        ForeignKey("module_config_versions.id"), index=True
    )
    review_channel_id: Mapped[str | None] = mapped_column(String(32), index=True)
    review_message_id: Mapped[str | None] = mapped_column(String(32), index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(32), index=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    last_error_code: Mapped[str | None] = mapped_column(String(120))
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    processing_token: Mapped[str | None] = mapped_column(String(160), index=True)
    processing_actor_id: Mapped[str | None] = mapped_column(String(32), index=True)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    previous_nickname: Mapped[str | None] = mapped_column(String(32))
    target_nickname: Mapped[str | None] = mapped_column(String(32))
    role_was_present: Mapped[bool | None] = mapped_column(Boolean)
    nickname_applied: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    role_applied: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    compensation_state: Mapped[CompensationState] = mapped_column(
        Enum(CompensationState, native_enum=False, length=20),
        default=CompensationState.none,
        server_default=CompensationState.none.value,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
