from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import discord

PENDING_COLOR = 0xFFC72C
APPROVED_COLOR = 0x57F287
REJECTED_COLOR = 0xED4245


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


def _role_mention(role_id: str | None) -> str:
    value = str(role_id or "").strip()
    return f"<@&{value}>" if value.isascii() and value.isdigit() else ""


@dataclass(frozen=True, slots=True)
class RegistrationLogData:
    decision: str
    discord_user_id: str | None = None
    submitted_name: str | None = None
    player_id: str | None = None
    reviewed_by: str | None = None
    reason: str | None = None
    target_nickname: str | None = None
    member_role_id: str | None = None
    decision_at: datetime | None = None
    avatar_url: str | None = None
    log_approved_title: str = "Registro aprovado"
    log_rejected_title: str = "Registro rejeitado"
    log_footer: str = "Yuno • Sistema de Registro"
    approved_dm_title: str = "Registro aprovado"
    rejected_dm_title: str = "Registro não aprovado"
    message: str | None = None

    @classmethod
    def from_payload(
        cls, payload: dict[str, Any] | None, *, avatar_url: str | None = None
    ) -> RegistrationLogData:
        data = payload or {}
        return cls(
            decision=str(data.get("decision") or "submitted"),
            discord_user_id=data.get("discord_user_id"),
            submitted_name=data.get("submitted_name"),
            player_id=data.get("player_id") or data.get("player_id_original"),
            reviewed_by=data.get("reviewed_by"),
            reason=data.get("reason"),
            target_nickname=data.get("target_nickname"),
            member_role_id=data.get("member_role_id"),
            decision_at=_utc_datetime(data.get("decision_at") or data.get("submitted_at")),
            avatar_url=avatar_url,
            log_approved_title=str(data.get("log_approved_title") or "Registro aprovado"),
            log_rejected_title=str(data.get("log_rejected_title") or "Registro rejeitado"),
            log_footer=str(data.get("log_footer") or "Yuno • Sistema de Registro"),
            approved_dm_title=str(data.get("approved_dm_title") or "Registro aprovado"),
            rejected_dm_title=str(data.get("rejected_dm_title") or "Registro não aprovado"),
            message=data.get("message"),
        )


class RegistrationLogRenderer:
    """Formata snapshots resolvidos do Registro, sem consultar domínio ou Discord."""

    @staticmethod
    def _base(
        data: RegistrationLogData,
        *,
        title: str,
        description: str,
        color: int,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=_safe_text(title, limit=256),
            description=description,
            color=color,
            timestamp=data.decision_at,
        )
        avatar_url = str(data.avatar_url or "")
        if avatar_url.startswith(("https://", "http://")):
            embed.set_thumbnail(url=avatar_url)
        footer = _safe_text(data.log_footer, limit=2048)
        if footer:
            embed.set_footer(text=footer)
        return embed

    @staticmethod
    def _identity_fields(embed: discord.Embed, data: RegistrationLogData) -> None:
        member = _user_mention(data.discord_user_id)
        if member:
            embed.add_field(name="Membro", value=member, inline=True)
        name = _safe_text(data.submitted_name)
        if name:
            embed.add_field(name="Nome informado", value=name, inline=True)
        player_id = _safe_text(data.player_id)
        if player_id:
            embed.add_field(name="ID informado", value=f"`{player_id}`", inline=True)

    def render_submitted(self, data: RegistrationLogData) -> discord.Embed:
        embed = self._base(
            data,
            title="Nova solicitação de registro",
            description="Uma nova solicitação aguarda análise da equipe responsável.",
            color=PENDING_COLOR,
        )
        self._identity_fields(embed, data)
        return embed

    def render_approved(self, data: RegistrationLogData) -> discord.Embed:
        embed = self._base(
            data,
            title=data.log_approved_title,
            description="O cadastro foi concluído e o acesso do membro foi liberado.",
            color=APPROVED_COLOR,
        )
        self._identity_fields(embed, data)
        reviewer = _user_mention(data.reviewed_by)
        if reviewer:
            embed.add_field(name="Aprovado por", value=reviewer, inline=True)
        role = _role_mention(data.member_role_id)
        if role:
            embed.add_field(name="Cargo aplicado", value=role, inline=True)
        nickname = _safe_text(data.target_nickname)
        if nickname:
            embed.add_field(name="Apelido aplicado", value=nickname, inline=False)
        return embed

    def render_rejected(self, data: RegistrationLogData) -> discord.Embed:
        embed = self._base(
            data,
            title=data.log_rejected_title,
            description="A solicitação foi analisada e não foi aprovada.",
            color=REJECTED_COLOR,
        )
        self._identity_fields(embed, data)
        reviewer = _user_mention(data.reviewed_by)
        if reviewer:
            embed.add_field(name="Rejeitado por", value=reviewer, inline=True)
        reason = _safe_text(data.reason)
        if reason:
            embed.add_field(name="Motivo", value=reason, inline=False)
        return embed

    def render_member_approved(self, data: RegistrationLogData) -> discord.Embed:
        embed = self._base(
            data,
            title=data.approved_dm_title,
            description=_safe_text(data.message, limit=4000)
            or "Seu registro foi aprovado.",
            color=APPROVED_COLOR,
        )
        name = _safe_text(data.submitted_name)
        player_id = _safe_text(data.player_id)
        if name:
            embed.add_field(name="Nome", value=name, inline=True)
        if player_id:
            embed.add_field(name="ID", value=f"`{player_id}`", inline=True)
        nickname = _safe_text(data.target_nickname)
        if nickname:
            embed.add_field(name="Seu novo apelido", value=nickname, inline=False)
        role = _role_mention(data.member_role_id)
        if role:
            embed.add_field(name="Cargo recebido", value=role, inline=False)
        return embed

    def render_member_rejected(self, data: RegistrationLogData) -> discord.Embed:
        embed = self._base(
            data,
            title=data.rejected_dm_title,
            description=_safe_text(data.message, limit=4000)
            or "Seu registro não foi aprovado.",
            color=REJECTED_COLOR,
        )
        reason = _safe_text(data.reason)
        if reason:
            embed.add_field(name="Motivo", value=reason, inline=False)
        return embed
