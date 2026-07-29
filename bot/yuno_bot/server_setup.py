"""Criacao e reconciliacao da estrutura de canais do Yuno num servidor.

Duas ideias governam este modulo.

1. As listas de canais, canais de log e modulos sao DERIVADAS do registry
   (`yuno_bot.modules`). Antes eram constantes escritas a mao, e o bot divergiu
   do backend: `farm_tickets` estava em `schemas.MODULES` e faltava aqui.

2. A reconciliacao e feita por ID, nao por nome. O cliente renomeia canal, move
   canal de lugar e organiza o servidor do jeito dele — isso e esperado, nao e
   erro. O `/yuno configurar` precisa ser seguro de rodar quantas vezes ele
   quiser, sem duplicar canal nem desfazer a organizacao dele.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import discord

from yuno_bot import modules
from yuno_bot.modules import SetupChannel  # re-export para consumidores existentes

SETUP_CATEGORIES: dict[str, str] = {
    "admin": "Yuno - Administracao",
    "operacao": "Yuno - Operacao",
    "logs": "Yuno - Logs",
}

# Canais do proprio Yuno, nao pertencem a modulo nenhum.
CORE_CHANNELS: tuple[SetupChannel, ...] = (
    SetupChannel("logs", "yuno-logs", "admin", ()),
    SetupChannel("painel", "yuno-painel", "admin", ()),
)

# Permissoes que o bot precisa, com a explicacao que o cliente entende.
PERMISSOES_NECESSARIAS: tuple[tuple[str, str], ...] = (
    ("manage_channels", "criar e organizar os canais do Yuno"),
    ("manage_roles", "ajustar quem enxerga cada canal"),
    ("view_channel", "enxergar os canais onde os paineis ficam"),
    ("send_messages", "publicar os paineis e as respostas"),
    ("embed_links", "enviar os embeds dos formularios"),
    ("read_message_history", "reaproveitar o painel ja publicado em vez de duplicar"),
)


def setup_channels() -> tuple[SetupChannel, ...]:
    """Canais do core mais os declarados por cada modulo, na ordem canonica."""
    return CORE_CHANNELS + modules.setup_channels()


def log_channels() -> dict[str, str]:
    """`{chave_do_modulo: nome_do_canal_de_log}`."""
    return modules.log_channels()


def module_keys() -> tuple[str, ...]:
    return modules.module_keys()


# ── Leitura da configuracao salva ─────────────────────────────────────────────


def _setup_settings(config: dict) -> dict:
    return (config.get("settings") or {}).get("discord_setup") or {}


def saved_category_id(config: dict, key: str) -> int | None:
    return _to_int((_setup_settings(config).get("category_ids") or {}).get(key))


def saved_channel_id(config: dict, key: str) -> int | None:
    return _to_int((_setup_settings(config).get("channel_ids") or {}).get(key))


def saved_log_channel_id(config: dict, module_key: str) -> int | None:
    return _to_int((_setup_settings(config).get("log_channel_ids") or {}).get(module_key))


def _to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ── Resolucao ─────────────────────────────────────────────────────────────────


def _by_id(guild: discord.Guild, channel_id: int | None, tipo: type):
    if not channel_id:
        return None
    canal = guild.get_channel(channel_id)
    return canal if isinstance(canal, tipo) else None


def _category_by_name(guild: discord.Guild, name: str) -> discord.CategoryChannel | None:
    alvo = name.casefold()
    return next((c for c in guild.categories if c.name.casefold() == alvo), None)


def _text_channel_by_name(guild: discord.Guild, name: str) -> discord.TextChannel | None:
    alvo = name.casefold()
    return next((c for c in guild.text_channels if c.name.casefold() == alvo), None)


@dataclass
class SetupResult:
    categories: dict[str, discord.CategoryChannel] = field(default_factory=dict)
    channels: dict[str, discord.TextChannel] = field(default_factory=dict)
    created: list[str] = field(default_factory=list)
    adopted: list[str] = field(default_factory=list)
    reused: list[str] = field(default_factory=list)

    def resumo(self) -> str:
        partes = []
        if self.created:
            partes.append(f"criei {len(self.created)}")
        if self.adopted:
            partes.append(f"adotei {len(self.adopted)} que ja existiam")
        if self.reused:
            partes.append(f"reaproveitei {len(self.reused)}")
        return ", ".join(partes) if partes else "nada a fazer"


async def _ensure_category(
    guild: discord.Guild, key: str, name: str, config: dict, result: SetupResult
) -> discord.CategoryChannel:
    categoria = _by_id(guild, saved_category_id(config, key), discord.CategoryChannel)
    if categoria:
        result.reused.append(f"categoria {categoria.name}")
        return categoria

    # Sem ID salvo (primeira execucao, ou servidor configurado antes desta versao):
    # adota a categoria de mesmo nome em vez de criar uma duplicada.
    categoria = _category_by_name(guild, name)
    if categoria:
        result.adopted.append(f"categoria {categoria.name}")
        return categoria

    categoria = await guild.create_category(name=name, reason="Setup do Yuno")
    result.created.append(f"categoria {name}")
    return categoria


async def _ensure_channel(
    guild: discord.Guild,
    *,
    saved_id: int | None,
    name: str,
    category: discord.CategoryChannel,
    result: SetupResult,
) -> discord.TextChannel:
    canal = _by_id(guild, saved_id, discord.TextChannel)
    if canal:
        # Resolvido pelo ID: o cliente pode ter renomeado ou movido de categoria.
        # Os dois casos sao legitimos e o bot nao desfaz nenhum deles.
        result.reused.append(f"#{canal.name}")
        return canal

    canal = _text_channel_by_name(guild, name)
    if canal:
        result.adopted.append(f"#{canal.name}")
        return canal

    canal = await category.create_text_channel(name=name, reason="Setup do Yuno")
    result.created.append(f"#{name}")
    return canal


async def ensure_setup_channels(guild: discord.Guild, current_config: dict | None = None) -> SetupResult:
    """Garante a estrutura do Yuno no servidor, de forma idempotente.

    Rodar duas vezes seguidas nao cria nada na segunda. Canal renomeado ou movido
    pelo cliente continua sendo o mesmo canal, porque a identidade e o ID.
    """
    config = current_config or {}
    result = SetupResult()

    for key, name in SETUP_CATEGORIES.items():
        result.categories[key] = await _ensure_category(guild, key, name, config, result)

    for spec in setup_channels():
        result.channels[spec.key] = await _ensure_channel(
            guild,
            saved_id=saved_channel_id(config, spec.key),
            name=spec.name,
            category=result.categories[spec.category],
            result=result,
        )

    for module_key, name in log_channels().items():
        result.channels[f"log_{module_key}"] = await _ensure_channel(
            guild,
            saved_id=saved_log_channel_id(config, module_key),
            name=name,
            category=result.categories["logs"],
            result=result,
        )

    return result


def build_setup_config(
    *,
    current_config: dict,
    guild: discord.Guild,
    categories: dict[str, discord.CategoryChannel],
    channels: dict[str, discord.TextChannel],
) -> dict:
    command_permissions = dict(current_config.get("command_permissions") or {})
    for spec in setup_channels():
        canal = channels.get(spec.key)
        if canal is None:
            continue
        for command_key in spec.command_keys:
            regra = dict(command_permissions.get(command_key) or {})
            regra["channel_ids"] = [str(canal.id)]
            command_permissions[command_key] = regra

    # Modulos ja configurados mantem o estado atual; modulos novos entram ligados.
    # Isso evita que uma atualizacao do Yuno reative um modulo que o cliente
    # desligou de proposito.
    modules_atuais = dict(current_config.get("modules") or {})
    modules_config = {key: modules_atuais.get(key, True) for key in module_keys()}

    settings = dict(current_config.get("settings") or {})
    settings["discord_setup"] = {
        "category_ids": {key: str(c.id) for key, c in categories.items()},
        "channel_ids": {key: str(c.id) for key, c in channels.items() if not key.startswith("log_")},
        "log_channel_ids": {
            module_key: str(channels[f"log_{module_key}"].id)
            for module_key in log_channels()
            if f"log_{module_key}" in channels
        },
    }

    return {
        "guild_name": guild.name,
        "admin_role_ids": current_config.get("admin_role_ids") or [],
        "log_channel_id": str(channels["logs"].id),
        "modules": modules_config,
        "command_permissions": command_permissions,
        "messages": current_config.get("messages") or {},
        "settings": settings,
    }
