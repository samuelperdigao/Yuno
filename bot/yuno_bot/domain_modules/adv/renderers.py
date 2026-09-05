from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import discord

from yuno_bot.platform import ui_kit as uk

APPLIED_COLOR = uk.WARNING
REVOKED_COLOR = uk.BRAND


def _utc_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str) and value.strip():
        try:
            result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _safe_text(value: Any, *, limit: int = 1024) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = discord.utils.escape_mentions(text)
    text = discord.utils.escape_markdown(text)
    return text[:limit]


def _user_mention(user_id: str | None) -> str:
    value = str(user_id or "").strip()
    return f"<@{value}>" if value.isascii() and value.isdigit() else ""


@dataclass(frozen=True, slots=True)
class AdvLogData:
    discord_user_id: str | None = None
    member_display_name: str | None = None
    moderator_id: str | None = None
    moderator_display_name: str | None = None
    reason: str | None = None
    created_at: datetime | None = None
    log_title: str = "Nova advertência aplicada"
    kind: str = "applied"

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> AdvLogData:
        data = payload or {}
        return cls(
            discord_user_id=data.get("discord_user_id"),
            member_display_name=data.get("member_display_name"),
            moderator_id=data.get("moderator_id"),
            moderator_display_name=data.get("moderator_display_name"),
            reason=data.get("reason"),
            created_at=_utc_datetime(data.get("created_at")),
            log_title=str(data.get("log_title") or "Nova advertência aplicada"),
            kind=str(data.get("kind") or "applied"),
        )


class AdvRenderer:
    """Formata snapshots resolvidos de Advertência, sem consultar dominio ou Discord."""

    @staticmethod
    def _base(data: AdvLogData, *, title: str, description: str, color: int) -> discord.Embed:
        embed = discord.Embed(title=_safe_text(title, limit=256), description=description, color=color)
        return embed

    def render(self, data: AdvLogData) -> discord.Embed:
        applied = data.kind != "revoked"
        color = APPLIED_COLOR if applied else REVOKED_COLOR
        description = (
            "Uma nova advertência foi aplicada." if applied else "Uma advertência foi revogada."
        )
        embed = self._base(data, title=data.log_title, description=description, color=color)
        member = _user_mention(data.discord_user_id)
        if member:
            embed.add_field(name="👤 Membro", value=member, inline=True)
        name = _safe_text(data.member_display_name)
        if name:
            embed.add_field(name="📛 Nome", value=name, inline=True)
        moderator = _user_mention(data.moderator_id) or _safe_text(data.moderator_display_name)
        if moderator:
            embed.add_field(
                name="🛡️ Responsável" if applied else "🛡️ Revogado por",
                value=moderator,
                inline=True,
            )
        reason = _safe_text(data.reason)
        if reason:
            embed.add_field(name="📄 Motivo", value=reason, inline=False)
        if data.created_at is not None:
            embed.add_field(
                name="🕒 Quando",
                value=discord.utils.format_dt(data.created_at, style="F"),
                inline=False,
            )
        return embed
