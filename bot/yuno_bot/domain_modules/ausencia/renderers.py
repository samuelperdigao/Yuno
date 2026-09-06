from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import discord

from yuno_bot.platform import ui_kit as uk

CONFIRMATION_COLOR = uk.BRAND
WARNING_COLOR = uk.WARNING
REMINDER_COLOR = uk.DANGER


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
class AusenciaLogData:
    discord_user_id: str | None = None
    member_display_name: str | None = None
    days: int = 0
    reason: str | None = None
    started_at: datetime | None = None
    ends_at: datetime | None = None
    near_limit: bool = False
    log_title: str = "Nova ausência registrada"
    reminder_title: str = "Sua ausência venceu"
    reminder_message: str = "Sua ausência chegou ao fim."

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> AusenciaLogData:
        data = payload or {}
        return cls(
            discord_user_id=data.get("discord_user_id"),
            member_display_name=data.get("member_display_name"),
            days=int(data.get("days") or 0),
            reason=data.get("reason"),
            started_at=_utc_datetime(data.get("started_at")),
            ends_at=_utc_datetime(data.get("ends_at")),
            near_limit=bool(data.get("near_limit")),
            log_title=str(data.get("log_title") or "Nova ausência registrada"),
            reminder_title=str(data.get("reminder_title") or "Sua ausência venceu"),
            reminder_message=str(data.get("reminder_message") or "Sua ausência chegou ao fim."),
        )


class AusenciaRenderer:
    """Formata snapshots resolvidos de Ausencia, sem consultar dominio ou Discord."""

    @staticmethod
    def _base(data: AusenciaLogData, *, title: str, description: str, color: int) -> discord.Embed:
        embed = discord.Embed(title=_safe_text(title, limit=256), description=description, color=color)
        return embed

    def render_registered(self, data: AusenciaLogData) -> discord.Embed:
        color = WARNING_COLOR if data.near_limit else CONFIRMATION_COLOR
        embed = self._base(
            data,
            title=data.log_title,
            description="Uma nova ausência foi registrada.",
            color=color,
        )
        member = _user_mention(data.discord_user_id)
        if member:
            embed.add_field(name="👤 Membro", value=member, inline=True)
        name = _safe_text(data.member_display_name)
        if name:
            embed.add_field(name="📛 Nome", value=name, inline=True)
        embed.add_field(name="📅 Dias", value=str(data.days), inline=True)
        if data.ends_at is not None:
            embed.add_field(
                name="🔁 Retorno previsto",
                value=discord.utils.format_dt(data.ends_at, style="F"),
                inline=False,
            )
        reason = _safe_text(data.reason)
        if reason:
            embed.add_field(name="📄 Motivo", value=reason, inline=False)
        if data.near_limit:
            embed.add_field(
                name="⚠️ Atenção",
                value="Esta ausência está próxima do limite permitido.",
                inline=False,
            )
        return embed

    def render_overdue_reminder(self, data: AusenciaLogData) -> discord.Embed:
        embed = self._base(
            data,
            title=data.reminder_title,
            description=_safe_text(data.reminder_message, limit=4000)
            or "Sua ausência chegou ao fim.",
            color=REMINDER_COLOR,
        )
        if data.ends_at is not None:
            embed.add_field(
                name="🕒 Venceu em",
                value=discord.utils.format_dt(data.ends_at, style="F"),
                inline=False,
            )
        return embed
