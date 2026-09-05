from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def new_id() -> str:
    return str(uuid4())


class Warning(Base):
    """Uma advertência aplicada a um membro. Histórico completo: nunca sobrescreve."""

    __tablename__ = "adv_warnings"
    __table_args__ = (
        Index("ix_adv_warnings_guild_user", "guild_id", "discord_user_id"),
        Index("ix_adv_warnings_guild_created", "guild_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    discord_user_id: Mapped[str] = mapped_column(String(32), index=True)
    member_display_name: Mapped[str] = mapped_column(String(120))
    moderator_id: Mapped[str] = mapped_column(String(32))
    moderator_display_name: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[str | None] = mapped_column(String(32))
    revoke_reason: Mapped[str | None] = mapped_column(Text)
