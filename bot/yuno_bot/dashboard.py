"""Central de Gestao baseada em Components V2 e adapters domain-first."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import discord
from discord.ext import commands

from yuno_bot.control_plane import is_control_plane_admin
from yuno_bot.modules import ModuleSpec, discover_modules
from yuno_bot.platform.components_v2 import (
    action_row,
    container,
    edit_message,
    payload,
    send_message,
    string_select,
    text_display,
)
from yuno_bot.platform.registry import discover_ui_modules, ui_registry


CENTRAL_CUSTOM_ID_PATTERN = re.compile(
    r"^yuno:central:v(?P<version>\d+):(?P<module>[a-z0-9_]{1,32}):"
    r"(?P<action>[a-z0-9_]{1,40})$"
)
CENTRAL_MODULE_SELECT_PATTERN = re.compile(
    r"^yuno:central:v(?P<version>\d+):(?P<module>core):"
    r"(?P<action>select_module)$"
)
CENTRAL_ACTION_PATTERN = re.compile(
    r"^yuno:central:v(?P<version>\d+):(?P<module>(?!core:)[a-z0-9_]{1,32}):"
    r"(?P<action>[a-z0-9_]{1,40})$"
)

_SELECT_COMPONENT_TYPES = frozenset({3, 5, 6, 7, 8})


def central_custom_id(module_key: str, action: str, *, version: int = 1) -> str:
    value = f"yuno:central:v{version}:{module_key}:{action}"
    if len(value) > 100 or CENTRAL_CUSTOM_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("custom_id invalido para a Central.")
    return value


@dataclass(frozen=True)
class DomainDashboardSpec:
    key: str
    nome: str
    icon: str
    ordem: int


def dashboard_specs() -> dict[str, ModuleSpec | DomainDashboardSpec]:
    if not ui_registry.all():
        discover_ui_modules()
    specs: list[ModuleSpec | DomainDashboardSpec] = [
        item for item in discover_modules().values() if not getattr(item, "retired", False)
    ]
    legacy_keys = {spec.key for spec in specs}
    for adapter in ui_registry.all():
        if adapter.module_key in legacy_keys:
            continue
        specs.append(
            DomainDashboardSpec(
                key=adapter.module_key,
                nome=adapter.name or adapter.module_key.replace("_", " ").title(),
                icon=adapter.icon,
                ordem=adapter.order,
            )
        )
    return {
        spec.key: spec
        for spec in sorted(specs, key=lambda item: (item.ordem, item.key))
    }


def build_payload(
    config: dict,
    page: int = 0,
    *,
    control_states: dict[str, dict[str, Any]] | None = None,
    license_active: bool = True,
) -> dict[str, Any]:
    del config, page, control_states, license_active
    options = [
        {
            "label": spec.nome[:100],
            "value": spec.key,
            "description": "Abrir configuracao do modulo",
            "emoji": {"name": spec.icon},
        }
        for spec in dashboard_specs().values()
    ]
    components = [
        text_display(
            "# Central de Gestao Yuno\n\nSelecione um modulo para configurar, revisar e publicar."
        )
    ]
    if options:
        components.append(
            action_row(
                string_select(
                    custom_id=central_custom_id("core", "select_module"),
                    options=options,
                    placeholder="Selecione um modulo",
                )
            )
        )
    else:
        components.append(text_display("_Nenhum modulo disponivel._"))
    return payload(container(*components, accent_color=0xFFC72C))


async def _send_v2(bot: commands.Bot, channel_id: int, data: dict) -> int:
    return await send_message(bot, channel_id, data)


async def _edit_v2(
    bot: commands.Bot, channel_id: int, message_id: int, data: dict
) -> None:
    await edit_message(bot, channel_id, message_id, data)


def dashboard_message_ref(config: dict) -> tuple[int | None, int | None]:
    settings = (config.get("settings") or {}).get("dashboard") or {}
    channel_id = settings.get("panel_channel_id")
    message_id = settings.get("panel_message_id")
    try:
        normalized_channel_id = int(channel_id) if channel_id else None
    except (TypeError, ValueError):
        normalized_channel_id = None
    try:
        normalized_message_id = int(message_id) if message_id else None
    except (TypeError, ValueError):
        normalized_message_id = None
    return normalized_channel_id, normalized_message_id


def with_dashboard_ref(config: dict, *, channel_id: int, message_id: int) -> dict:
    settings = dict(config.get("settings") or {})
    settings["dashboard"] = {
        "panel_channel_id": str(channel_id),
        "panel_message_id": str(message_id),
    }
    return {**config, "settings": settings}


async def publish_or_update(
    bot: commands.Bot,
    channel: discord.TextChannel,
    config: dict,
    *,
    control_states: dict[str, dict[str, Any]] | None = None,
) -> int:
    data = build_payload(config, control_states=control_states)
    previous_channel_id, previous_message_id = dashboard_message_ref(config)
    if previous_message_id and previous_channel_id == channel.id:
        try:
            known_message = await channel.fetch_message(previous_message_id)
            if channel.guild.me and known_message.author.id != channel.guild.me.id:
                return await _send_v2(bot, channel.id, data)
            await _edit_v2(bot, channel.id, previous_message_id, data)
            return previous_message_id
        except discord.HTTPException:
            pass
    return await _send_v2(bot, channel.id, data)


async def rollback_unsaved_dashboard(
    config: dict, channel: discord.TextChannel, message_id: int
) -> None:
    previous_channel_id, previous_message_id = dashboard_message_ref(config)
    if previous_channel_id == channel.id and previous_message_id == message_id:
        return
    try:
        message = await channel.fetch_message(message_id)
        if channel.guild.me and message.author.id == channel.guild.me.id:
            await message.delete()
    except discord.HTTPException:
        pass


async def remove_previous_dashboard(
    config: dict, channel: discord.TextChannel, message_id: int
) -> None:
    previous_channel_id, previous_message_id = dashboard_message_ref(config)
    if not previous_channel_id or not previous_message_id:
        return
    if previous_channel_id == channel.id and previous_message_id == message_id:
        return
    old_channel = channel.guild.get_channel(previous_channel_id)
    if not isinstance(old_channel, discord.TextChannel):
        return
    try:
        message = await old_channel.fetch_message(previous_message_id)
        if channel.guild.me and message.author.id == channel.guild.me.id:
            await message.delete()
    except discord.HTTPException:
        pass


async def fetch_control_states(
    api: Any,
    guild_id: int,
    actor_id: int,
    *,
    platform_api: Any | None = None,
) -> dict[str, dict[str, Any]]:
    del api, actor_id
    if platform_api is None:
        return {}
    states: dict[str, dict[str, Any]] = {}
    for adapter in ui_registry.all():
        try:
            states[adapter.module_key] = await platform_api.module_instance(
                guild_id, adapter.module_key
            )
        except Exception:
            states[adapter.module_key] = {"lifecycle": "unknown"}
    return states


async def _central_config(interaction: discord.Interaction) -> dict | None:
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await _deny(interaction, "Esta acao exige a Central publicada em um servidor.")
        return None
    bot = interaction.client
    try:
        config = await bot.api.get_guild_config(interaction.guild.id)
    except Exception:
        await _deny(interaction, "Nao consegui revalidar a configuracao da Central.")
        return None
    if not is_control_plane_admin(interaction.guild, interaction.user, config):
        await _deny(interaction, "Voce nao possui permissao para administrar a Central.")
        return None
    channel_id, message_id = dashboard_message_ref(config)
    if (
        interaction.message is None
        or channel_id != interaction.channel_id
        or message_id != interaction.message.id
    ):
        await _deny(interaction, "Esta mensagem nao e a Central ativa desta guild.")
        return None
    return config


async def _deny(interaction: discord.Interaction, message: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


async def _acknowledge_select(interaction: discord.Interaction) -> None:
    """Acknowledge Components V2 selects before any API round-trip."""

    if not interaction.response.is_done():
        await interaction.response.defer()


async def dispatch_components_v2(interaction: discord.Interaction) -> bool:
    """Dispatch a Central component directly from the gateway payload.

    discord.py 2.4 cannot rebuild children nested in a Components V2 container,
    so its DynamicItem store silently skips these interactions.  The raw
    interaction event still contains the stable custom ID and selected values.
    """

    data = interaction.data or {}
    custom_id = str(data.get("custom_id") or "")
    match = CENTRAL_CUSTOM_ID_PATTERN.fullmatch(custom_id)
    if match is None:
        return False

    version = int(match.group("version"))
    module_key = match.group("module")
    action_key = match.group("action")
    if version != 1:
        await _deny(interaction, "Versao da Central nao suportada.")
        return True

    try:
        component_type = int(data.get("component_type") or 0)
    except (TypeError, ValueError):
        component_type = 0

    if module_key == "core" and action_key == "select_module":
        values = list(data.get("values") or [])
        if component_type != 3 or not values:
            await _deny(interaction, "Selecao da Central invalida.")
            return True
        await _acknowledge_select(interaction)
        await _dispatch_page(interaction, str(values[0]))
        return True

    if component_type in _SELECT_COMPONENT_TYPES:
        await _acknowledge_select(interaction)
    await _dispatch_action(interaction, module_key, action_key)
    return True


async def _dispatch_page(interaction: discord.Interaction, module_key: str) -> None:
    if await _central_config(interaction) is None:
        return
    adapter = ui_registry.get(module_key)
    page = next(
        (item for item in (adapter.admin_pages if adapter else ()) if item.key == "overview"),
        None,
    )
    if page is None:
        await _deny(interaction, "Este modulo ainda nao possui configuracao na Central.")
        return
    await page.renderer(interaction, interaction.client.platform_api)


async def _dispatch_action(
    interaction: discord.Interaction, module_key: str, action_key: str
) -> None:
    if await _central_config(interaction) is None:
        return
    action = ui_registry.admin_action(module_key, action_key)
    if action is None:
        await _deny(interaction, "Acao administrativa indisponivel.")
        return
    await action.handler(interaction, interaction.client.platform_api)


class _CentralDynamic:
    def _init_central(self, *, version: int, module_key: str, action_key: str) -> None:
        self.version = version
        self.module_key = module_key
        self.action_key = action_key

    @classmethod
    def _arguments(cls, match) -> dict[str, Any]:
        return {
            "version": int(match.group("version")),
            "module_key": match.group("module"),
            "action_key": match.group("action"),
        }


class CentralModuleSelect(
    _CentralDynamic,
    discord.ui.DynamicItem[discord.ui.Select],
    template=CENTRAL_MODULE_SELECT_PATTERN,
):
    def __init__(self, item, **kwargs) -> None:
        super().__init__(item)
        self._init_central(**kwargs)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        del interaction
        return cls(item, **cls._arguments(match))

    async def callback(self, interaction: discord.Interaction) -> None:
        values = list((interaction.data or {}).get("values") or [])
        if (
            self.version != 1
            or self.module_key != "core"
            or self.action_key != "select_module"
            or not values
        ):
            await _deny(interaction, "Selecao da Central invalida.")
            return
        await _acknowledge_select(interaction)
        await _dispatch_page(interaction, str(values[0]))


class CentralActionButton(
    _CentralDynamic,
    discord.ui.DynamicItem[discord.ui.Button],
    template=CENTRAL_ACTION_PATTERN,
):
    def __init__(self, item, **kwargs) -> None:
        super().__init__(item)
        self._init_central(**kwargs)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        del interaction
        return cls(item, **cls._arguments(match))

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.version != 1:
            await _deny(interaction, "Versao da Central nao suportada.")
            return
        await _dispatch_action(interaction, self.module_key, self.action_key)


class CentralActionSelect(
    _CentralDynamic,
    discord.ui.DynamicItem[discord.ui.Select],
    template=CENTRAL_ACTION_PATTERN,
):
    def __init__(self, item, **kwargs) -> None:
        super().__init__(item)
        self._init_central(**kwargs)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        del interaction
        return cls(item, **cls._arguments(match))

    async def callback(self, interaction: discord.Interaction) -> None:
        await _acknowledge_select(interaction)
        await _dispatch_action(interaction, self.module_key, self.action_key)


class CentralChannelSelect(
    _CentralDynamic,
    discord.ui.DynamicItem[discord.ui.ChannelSelect],
    template=CENTRAL_ACTION_PATTERN,
):
    def __init__(self, item, **kwargs) -> None:
        super().__init__(item)
        self._init_central(**kwargs)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        del interaction
        return cls(item, **cls._arguments(match))

    async def callback(self, interaction: discord.Interaction) -> None:
        await _acknowledge_select(interaction)
        await _dispatch_action(interaction, self.module_key, self.action_key)


class CentralRoleSelect(
    _CentralDynamic,
    discord.ui.DynamicItem[discord.ui.RoleSelect],
    template=CENTRAL_ACTION_PATTERN,
):
    def __init__(self, item, **kwargs) -> None:
        super().__init__(item)
        self._init_central(**kwargs)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        del interaction
        return cls(item, **cls._arguments(match))

    async def callback(self, interaction: discord.Interaction) -> None:
        await _acknowledge_select(interaction)
        await _dispatch_action(interaction, self.module_key, self.action_key)
