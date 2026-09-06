"""Funcoes puras do modulo de Radio: validacao, formatacao e embeds.

Sem I/O e sem dependencia de `discord.Interaction`, para serem testaveis sem
subir bot nem mockar rede. O canal de radio em si nao mora aqui: e resolvido
por ID salvo via `server_setup.saved_channel_id(config, "radio")` (o mesmo
mecanismo usado por todo canal criado por `/yuno configurar`). O unico estado
proprio deste modulo e o id da mensagem do painel, para republicar sem
duplicar.
"""

from __future__ import annotations

import re

import discord

from yuno_bot.platform import ui_kit as uk

COLOR = uk.BRAND

_SANITIZE_PATTERN = re.compile(r"[^\w\s-]", re.UNICODE)
_SLUG_INVALID_PATTERN = re.compile(r"[^\w-]", re.UNICODE)
_SLUG_REPEATED_DASH = re.compile(r"-+")

MAX_FREQUENCIA_LENGTH = 20


def normalize_frequencia(raw: str) -> str:
    """Limpa a frequencia informada no modal.

    Aceita texto livre curto (numeros, letras, espacos, hifen) e rejeita o
    resto para o valor nao quebrar o nome do canal nem o anuncio.
    """
    valor = _SANITIZE_PATTERN.sub("", (raw or "").strip())
    valor = re.sub(r"\s+", " ", valor).strip()
    if not valor:
        raise ValueError("Informe a frequência da rádio.")
    if len(valor) > MAX_FREQUENCIA_LENGTH:
        raise ValueError(f"A frequência deve ter no máximo {MAX_FREQUENCIA_LENGTH} caracteres.")
    return valor


def channel_name_for(numero: str) -> str:
    """Nome do canal apos a nova frequencia ser definida.

    Mantem o numero visivel, no padrao usado pelo MDM (`radio-<numero>`).
    """
    slug = _SLUG_INVALID_PATTERN.sub("-", numero.strip().lower())
    slug = _SLUG_REPEATED_DASH.sub("-", slug).strip("-")
    return f"┃📻-radio-{slug}!"


def _as_int(value) -> int | None:
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def radio_panel_message_id(config: dict) -> int | None:
    settings = (config.get("settings") or {}).get("radio") or {}
    return _as_int(settings.get("panel_message_id"))


def with_radio_panel_message_id(current_config: dict, *, message_id: int) -> dict:
    settings = dict(current_config.get("settings") or {})
    radio = dict(settings.get("radio") or {})
    radio["panel_message_id"] = str(message_id)
    settings["radio"] = radio

    return {
        "guild_name": current_config.get("guild_name"),
        "admin_role_ids": current_config.get("admin_role_ids") or [],
        "log_channel_id": current_config.get("log_channel_id"),
        "modules": current_config.get("modules") or {},
        "command_permissions": current_config.get("command_permissions") or {},
        "messages": current_config.get("messages") or {},
        "settings": settings,
    }


def panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📻 Painel de Rádio",
        description=(
            "Clique no botão abaixo para definir a nova frequência da rádio "
            "deste servidor. Este canal será renomeado e receberá o anúncio."
        ),
        color=COLOR,
    )
    embed.set_footer(text="Sistema de Rádio")
    return embed


def radio_announcement_embed(numero: str, autor: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(
        title="📻 Nova frequência da rádio",
        description=f"A rádio deste servidor agora está sintonizada em **{numero}**.",
        color=COLOR,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text=f"Definida por {autor.display_name}")
    return embed
