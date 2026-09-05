"""Monta os embeds de entrada e saída a partir de dados já resolvidos.

Funções puras: recebem os snapshots de `domain.py` (mais um `now` explícito
quando a comparação depende do instante da chamada) e devolvem um
`discord.Embed` pronto. Nenhuma chamada de rede, nenhuma leitura de canal —
quem busca os dados é `runtime.py`.
"""

from __future__ import annotations

from datetime import datetime

import discord

from yuno_bot.domain_modules.log_membros.domain import (
    JoinSnapshot,
    LeaveCause,
    LeaveSnapshot,
    format_duration,
    is_new_account,
)

JOIN_COLOR = 0x2ECC71
LEAVE_COLOR = 0xE74C3C


def build_join_embed(snapshot: JoinSnapshot, *, now: datetime) -> discord.Embed:
    created_ts = int(snapshot.account_created_at.timestamp())
    embed = discord.Embed(
        title="📥 Entrada de membro",
        description=f"{snapshot.member_mention} entrou no servidor.",
        color=JOIN_COLOR,
        timestamp=snapshot.joined_at,
    )
    embed.add_field(
        name="Usuário", value=f"{snapshot.display_name}\n`{snapshot.member_id}`", inline=True
    )
    embed.add_field(
        name="Conta criada em",
        value=f"<t:{created_ts}:F> (<t:{created_ts}:R>)",
        inline=True,
    )
    embed.add_field(name="Membros no servidor", value=str(snapshot.member_count), inline=True)
    if is_new_account(snapshot.account_created_at, now=now):
        embed.add_field(
            name="⚠️ Atenção",
            value="**CONTA NOVA** — criada há menos de 7 dias.",
            inline=False,
        )
    embed.set_footer(text=f"ID: {snapshot.member_id}")
    return embed


def _cause_text(cause: LeaveCause) -> str:
    moderator = f"<@{cause.moderator_id}>" if cause.moderator_id else "um responsável não identificado"
    if cause.kind == "kicked":
        text = f"Expulso por {moderator}."
    elif cause.kind == "banned":
        text = f"Banido por {moderator}."
    elif cause.kind == "unknown":
        text = "Motivo desconhecido (sem permissão para consultar o log de auditoria)."
    else:
        text = "Saiu do servidor por conta própria."
    if cause.reason:
        text += f"\nMotivo informado: {cause.reason}"
    return text


def build_leave_embed(snapshot: LeaveSnapshot) -> discord.Embed:
    embed = discord.Embed(
        title="📤 Saída de membro",
        description=f"**{snapshot.display_name}** saiu do servidor.",
        color=LEAVE_COLOR,
        timestamp=snapshot.left_at,
    )
    embed.add_field(
        name="Usuário", value=f"{snapshot.display_name}\n`{snapshot.member_id}`", inline=True
    )
    if snapshot.joined_at is not None:
        joined_ts = int(snapshot.joined_at.timestamp())
        embed.add_field(name="Entrou em", value=f"<t:{joined_ts}:F>", inline=True)
        embed.add_field(
            name="Tempo no servidor",
            value=format_duration(snapshot.left_at - snapshot.joined_at),
            inline=True,
        )
    else:
        embed.add_field(name="Entrou em", value="Desconhecido", inline=True)
    embed.add_field(name="Motivo da saída", value=_cause_text(snapshot.cause), inline=False)
    embed.add_field(
        name="Cargos",
        value=", ".join(snapshot.role_mentions) if snapshot.role_mentions else "Nenhum cargo.",
        inline=False,
    )
    if snapshot.extra_message:
        embed.add_field(name="Observação", value=snapshot.extra_message, inline=False)
    embed.set_footer(text=f"ID: {snapshot.member_id}")
    return embed
