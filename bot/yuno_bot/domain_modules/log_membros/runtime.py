"""Handlers de `on_member_join`/`on_member_remove` para Entrada e Saída de Membros.

Registrados via `member_join_handler`/`member_remove_handler` em `MODULE_UI`
(ver `platform/contracts.py`) e disparados por `YunoBot.on_member_join` /
`YunoBot.on_member_remove` para todo módulo que os declarar — este é o
primeiro a usá-los, mas o dispatch em si é genérico, no mesmo molde de
`message_handler` e `resource_delete_handler`.

Toda a leitura do log de auditoria é best-effort: falta de permissão
(`discord.Forbidden`) vira `LeaveCause(kind="unknown")` em vez de derrubar o
listener — perder o log de saída de um membro é ruim, mas silenciar o bot
inteiro por isso seria pior.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import discord
import httpx

from yuno_bot.domain_modules.log_membros.domain import (
    AuditCandidate,
    JoinSnapshot,
    LeaveCause,
    LeaveSnapshot,
    detect_leave_cause,
)
from yuno_bot.domain_modules.log_membros.embeds import build_join_embed, build_leave_embed

MODULE_KEY = "log_membros"
AUDIT_LOG_LOOKBACK = 5


async def _effective_config(api: Any, guild_id: int) -> dict[str, Any] | None:
    """Config publicada, ou `None` quando o módulo não está pronto para agir.

    "Pronto" exige as duas coisas: lifecycle ativo (o cliente pode publicar e
    depois pausar sem despublicar) e uma configuração publicada — checar só
    uma das duas deixaria o módulo agindo pausado ou quebrando em 404.
    """

    try:
        instance = await api.module_instance(guild_id, MODULE_KEY)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {403, 404}:
            return None
        raise
    if instance.get("lifecycle") != "active":
        return None
    try:
        version = await api.effective_configuration(guild_id, MODULE_KEY)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {403, 404}:
            return None
        raise
    return version.get("data") or {}


def _text_channel(guild: discord.Guild, channel_id: Any) -> discord.TextChannel | None:
    if not channel_id:
        return None
    try:
        channel = guild.get_channel(int(channel_id))
    except (TypeError, ValueError):
        return None
    return channel if isinstance(channel, discord.TextChannel) else None


async def handle_member_join(bot: discord.Client, api: Any, member: discord.Member) -> None:
    guild = member.guild
    config = await _effective_config(api, guild.id)
    if config is None:
        return

    role_ids = [str(item) for item in config.get("join_role_ids") or []]
    if role_ids:
        roles = [role for role in (guild.get_role(int(role_id)) for role_id in role_ids) if role is not None]
        if roles:
            try:
                await member.add_roles(*roles, reason="Yuno: cargo automático de entrada")
            except discord.Forbidden:
                bot.log.warning(
                    "Sem permissão para atribuir cargos de entrada na guild %s", guild.id
                )

    channel = _text_channel(guild, config.get("join_channel_id"))
    if channel is None:
        return
    snapshot = JoinSnapshot(
        member_id=member.id,
        member_mention=member.mention,
        display_name=str(member),
        account_created_at=member.created_at,
        joined_at=member.joined_at or datetime.now(timezone.utc),
        member_count=guild.member_count or len(guild.members),
    )
    embed = build_join_embed(snapshot, now=datetime.now(timezone.utc))
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        bot.log.warning("Sem permissão para publicar log de entrada no canal %s", channel.id)


async def _detect_leave_cause(guild: discord.Guild, member_id: int, left_at: datetime) -> LeaveCause:
    bot_member = guild.me
    if bot_member is None or not bot_member.guild_permissions.view_audit_log:
        return LeaveCause(kind="unknown")
    candidates: list[AuditCandidate] = []
    try:
        for action, label in (
            (discord.AuditLogAction.kick, "kick"),
            (discord.AuditLogAction.ban, "ban"),
        ):
            async for entry in guild.audit_logs(limit=AUDIT_LOG_LOOKBACK, action=action):
                if entry.target is None:
                    continue
                candidates.append(
                    AuditCandidate(
                        action=label,
                        target_id=entry.target.id,
                        moderator_id=entry.user.id if entry.user else None,
                        created_at=entry.created_at,
                        reason=entry.reason,
                    )
                )
    except discord.Forbidden:
        return LeaveCause(kind="unknown")
    return detect_leave_cause(candidates, member_id=member_id, left_at=left_at)


async def handle_member_remove(bot: discord.Client, api: Any, member: discord.Member) -> None:
    guild = member.guild
    config = await _effective_config(api, guild.id)
    if config is None:
        return

    channel = _text_channel(guild, config.get("leave_channel_id"))
    if channel is None:
        return

    now = datetime.now(timezone.utc)
    cause = await _detect_leave_cause(guild, member.id, now)
    snapshot = LeaveSnapshot(
        member_id=member.id,
        display_name=str(member),
        joined_at=member.joined_at,
        left_at=now,
        role_mentions=tuple(role.mention for role in member.roles if not role.is_default()),
        cause=cause,
        extra_message=str(config.get("leave_extra_message") or ""),
    )
    embed = build_leave_embed(snapshot)
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        bot.log.warning("Sem permissão para publicar log de saída no canal %s", channel.id)
