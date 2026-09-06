from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def new_id() -> str:
    return str(uuid4())


class AbsenceRecord(Base):
    """Estado atual da ausencia de um membro: um registro novo sobrescreve o anterior."""

    __tablename__ = "absence_records"
    __table_args__ = (
        UniqueConstraint("guild_id", "discord_user_id", name="uq_absence_records_guild_user"),
        Index("ix_absence_records_guild_ends_at", "guild_id", "ends_at"),
        Index(
            "ix_absence_records_guild_overdue",
            "guild_id",
            "overdue_notified",
            "ends_at",
        ),
        CheckConstraint("days >= 1", name="ck_absence_records_days_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    discord_user_id: Mapped[str] = mapped_column(String(32), index=True)
    member_display_name: Mapped[str] = mapped_column(String(120))
    days: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    overdue_notified: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
