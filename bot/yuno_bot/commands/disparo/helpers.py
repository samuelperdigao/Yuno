"""Selecao de canais-alvo do disparo e envio do log do modulo.

O Yuno nao tem hoje um mapeamento formal "membro -> canal privado" acessivel
entre modulos: o antigo `farm_tickets` tinha `parse_member_folder`, removido no
cutover da v2, e o modulo `set` nunca chegou a ter uma implementacao real (so
existe como catalogo). O destino do disparo vem, entao, de uma categoria
configuravel mais uma lista de exclusao explicita, guardadas em
`settings.disparo` pelo `/disparo painel`. Canais com "livre" no nome (pasta
sem dono, convencao ja usada no MDM) sao pulados automaticamente -- o resto da
categoria e responsabilidade do admin marcar na lista de exclusao.
"""

from __future__ import annotations

from typing import Any

import discord

LOG_MODULE_KEY = "disparo"


def parse_excluded_ids(raw: str | None) -> list[str]:
    """Extrai IDs de canal de uma lista digitada a mao (mencao, ID cru ou ambos)."""
    if not raw:
        return []
    ids: list[str] = []
    for token in raw.replace("\n", ",").split(","):
        digits = "".join(char for char in token if char.isdigit())
        if digits and digits not in ids:
            ids.append(digits)
    return ids


def valid_target_channels(
    category: discord.CategoryChannel, excluded_ids: list[str] | None = None
) -> list[discord.TextChannel]:
    """Canais validos da categoria: exclui a lista manual e pastas livres/sem dono."""
    excluidos = set(excluded_ids or [])
    return [
        channel
        for channel in category.text_channels
        if str(channel.id) not in excluidos and "livre" not in channel.name.casefold()
    ]


def log_channel_id(config: dict[str, Any]) -> int | None:
    setup = (config.get("settings") or {}).get("discord_setup") or {}
    channel_id = (setup.get("log_channel_ids") or {}).get(LOG_MODULE_KEY)
    try:
        return int(channel_id) if channel_id else None
    except (TypeError, ValueError):
        return None


async def send_log(guild: discord.Guild, config: dict[str, Any], embed: discord.Embed) -> None:
    channel_id = log_channel_id(config)
    if not channel_id:
        return
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass
