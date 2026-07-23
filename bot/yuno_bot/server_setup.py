from dataclasses import dataclass

import discord


@dataclass(frozen=True)
class SetupChannel:
    key: str
    name: str
    category_key: str
    command_keys: tuple[str, ...]


SETUP_CATEGORIES: dict[str, str] = {
    "admin": "Yuno - Administracao",
    "operacao": "Yuno - Operacao",
    "logs": "Yuno - Logs",
}

SETUP_CHANNELS: tuple[SetupChannel, ...] = (
    SetupChannel("logs", "yuno-logs", "admin", ()),
    SetupChannel("set_solicitar", "set-solicitar", "operacao", ("set.solicitar",)),
    SetupChannel("set_aprovacao", "set-aprovacao", "admin", ("set.aprovar", "set.reprovar")),
    SetupChannel("metas", "metas-semanais", "operacao", ("meta.registrar",)),
    SetupChannel("tickets", "tickets", "operacao", ("ticket.abrir",)),
    SetupChannel("parcerias", "parcerias", "operacao", ("parceria.cadastrar",)),
    SetupChannel("encomendas", "encomendas", "operacao", ("encomenda.criar",)),
    SetupChannel("ausencias", "ausencias", "operacao", ("ausencia.avisar",)),
    SetupChannel("radio", "radio", "operacao", ("radio.alterar",)),
    SetupChannel("producao", "producao", "operacao", ("producao.registrar",)),
)

SETUP_LOG_CHANNELS: dict[str, str] = {
    "set": "logs-set",
    "meta": "logs-meta",
    "ticket": "logs-ticket",
    "parceria": "logs-parceria",
    "encomenda": "logs-encomenda",
    "ausencia": "logs-ausencia",
    "radio": "logs-radio",
    "producao": "logs-producao",
}

MODULES: tuple[str, ...] = (
    "set",
    "meta",
    "ticket",
    "parceria",
    "encomenda",
    "ausencia",
    "radio",
    "producao",
)


def _find_category(guild: discord.Guild, name: str) -> discord.CategoryChannel | None:
    normalized = name.casefold()
    return next((category for category in guild.categories if category.name.casefold() == normalized), None)


def _find_text_channel(guild: discord.Guild, name: str) -> discord.TextChannel | None:
    normalized = name.casefold()
    return next((channel for channel in guild.text_channels if channel.name.casefold() == normalized), None)


async def ensure_setup_channels(guild: discord.Guild) -> tuple[dict[str, discord.CategoryChannel], dict[str, discord.TextChannel], list[str]]:
    created: list[str] = []
    categories: dict[str, discord.CategoryChannel] = {}
    channels: dict[str, discord.TextChannel] = {}

    for key, name in SETUP_CATEGORIES.items():
        category = _find_category(guild, name)
        if not category:
            category = await guild.create_category(name=name, reason="Setup inicial do Yuno")
            created.append(f"categoria {name}")
        categories[key] = category

    for channel_spec in SETUP_CHANNELS:
        channel = _find_text_channel(guild, channel_spec.name)
        if not channel:
            channel = await categories[channel_spec.category_key].create_text_channel(
                name=channel_spec.name,
                reason="Setup inicial do Yuno",
            )
            created.append(f"canal #{channel_spec.name}")
        elif channel.category_id != categories[channel_spec.category_key].id:
            await channel.edit(category=categories[channel_spec.category_key], reason="Organizacao inicial do Yuno")
        channels[channel_spec.key] = channel

    for module, name in SETUP_LOG_CHANNELS.items():
        channel = _find_text_channel(guild, name)
        if not channel:
            channel = await categories["logs"].create_text_channel(
                name=name,
                reason="Setup inicial dos logs do Yuno",
            )
            created.append(f"canal #{name}")
        elif channel.category_id != categories["logs"].id:
            await channel.edit(category=categories["logs"], reason="Organizacao inicial dos logs do Yuno")
        channels[f"log_{module}"] = channel

    return categories, channels, created


def build_setup_config(
    *,
    current_config: dict,
    guild: discord.Guild,
    categories: dict[str, discord.CategoryChannel],
    channels: dict[str, discord.TextChannel],
) -> dict:
    command_permissions = dict(current_config.get("command_permissions") or {})
    for channel_spec in SETUP_CHANNELS:
        channel = channels[channel_spec.key]
        for command_key in channel_spec.command_keys:
            existing_rule = dict(command_permissions.get(command_key) or {})
            existing_rule["channel_ids"] = [str(channel.id)]
            command_permissions[command_key] = existing_rule

    settings = dict(current_config.get("settings") or {})
    settings["discord_setup"] = {
        "category_ids": {key: str(category.id) for key, category in categories.items()},
        "channel_ids": {key: str(channel.id) for key, channel in channels.items() if not key.startswith("log_")},
        "log_channel_ids": {
            module: str(channels[f"log_{module}"].id)
            for module in SETUP_LOG_CHANNELS
            if f"log_{module}" in channels
        },
    }

    return {
        "guild_name": guild.name,
        "admin_role_ids": current_config.get("admin_role_ids") or [],
        "log_channel_id": str(channels["logs"].id),
        "modules": {module: True for module in MODULES},
        "command_permissions": command_permissions,
        "messages": current_config.get("messages") or {},
        "settings": settings,
    }
