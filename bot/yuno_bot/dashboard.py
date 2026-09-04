"""Central de Gestão baseada em Components V2 e adapters domain-first.

A tipografia e os tokens de cor vêm de `platform/ui_kit.py`, o mesmo kit
usado pelos painéis públicos dos módulos."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import discord
from discord.ext import commands

from yuno_bot.control_plane import is_control_plane_admin
from yuno_bot.modules import ModuleSpec, discover_modules
from yuno_bot.platform import ui_kit as uk
from yuno_bot.platform.components_v2 import (
    action_row,
    button,
    container,
    edit_message,
    payload,
    section,
    send_message,
    separator,
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
        raise ValueError("custom_id inválido para a Central.")
    return value


@dataclass(frozen=True)
class DomainDashboardSpec:
    key: str
    nome: str
    icon: str
    ordem: int
    descricao: str = ""
    plano_minimo: str = "basico"


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
                descricao=adapter.description,
                plano_minimo=adapter.minimum_plan,
            )
        )
    return {
        spec.key: spec
        for spec in sorted(specs, key=lambda item: (item.ordem, item.key))
    }


#: Valor reservado da navegação para voltar à lista de módulos. Nenhum módulo
#: pode usar esta chave porque `ModuleSpec.key` é snake_case sem sublinhado
#: duplo nas pontas.
CENTRAL_HOME_VALUE = "__central__"

#: Ação reservada pela Central: é o botão de cada linha da lista. O dispatcher
#: só a trata como atalho quando o módulo não declara uma ação com esse nome.
CENTRAL_OPEN_ACTION = "open"

#: Uma mensagem Components V2 aceita 40 componentes. Cada linha da lista gasta
#: dois (seção + separador), então acima deste teto a Central volta a navegar
#: pelo seletor em vez de estourar o limite no servidor do cliente.
MAX_MODULE_ROWS = 12

BUTTON_PRIMARY = 1
BUTTON_SECONDARY = 2


def module_navigation(current_module: str | None = None) -> dict[str, Any]:
    """Navegação compartilhada entre páginas administrativas da Central.

    A primeira opção volta para a lista de módulos: as páginas de módulo
    substituem a mensagem da Central, então sem essa entrada só se sai de um
    módulo entrando em outro.
    """

    options: list[dict[str, Any]] = [
        {
            "label": "Central de Gestão",
            "value": CENTRAL_HOME_VALUE,
            "description": "Voltar para a lista de módulos",
            "emoji": {"name": "🏠"},
            "default": False,
        }
    ]
    options.extend(
        {
            "label": spec.nome[:100],
            "value": spec.key,
            "description": (
                "Módulo atual"
                if spec.key == current_module
                else "Abrir configuração do módulo"
            ),
            "emoji": {"name": spec.icon},
            "default": spec.key == current_module,
        }
        for spec in dashboard_specs().values()
    )
    return action_row(
        string_select(
            custom_id=central_custom_id("core", "select_module"),
            options=options,
            placeholder="Trocar de módulo",
        )
    )


@dataclass(frozen=True)
class ModuleStatus:
    """Como um módulo aparece na lista: selo, explicação e chamada do botão."""

    state: uk.State
    label: str
    hint: str
    action: str
    primary: bool = False


#: O rótulo responde "está no ar?" e a chamada do botão responde "e agora?".
#: Manter os dois na mesma tabela evita a combinação sem sentido — selo verde
#: com botão "Configurar" — que aparece quando cada um é decidido em um lugar.
MODULE_STATUSES: dict[str, ModuleStatus] = {
    "active": ModuleStatus(
        uk.State.APPROVED,
        "No ar",
        "Atendendo os membros deste servidor.",
        "Gerenciar",
    ),
    "unpublished": ModuleStatus(
        uk.State.PENDING,
        "Aguardando publicação",
        "As escolhas estão salvas como rascunho.",
        "Revisar e publicar",
        primary=True,
    ),
    "inactive": ModuleStatus(
        uk.State.DISABLED,
        "Desligado",
        "A configuração continua salva e nada foi apagado.",
        "Reativar",
        primary=True,
    ),
    "pending": ModuleStatus(
        uk.State.PENDING,
        "Não configurado",
        "Nada é criado no Discord antes da publicação.",
        "Configurar",
        primary=True,
    ),
    "paused": ModuleStatus(
        uk.State.RUNNING,
        "Pausado",
        "Retomar quando quiser, do ponto em que parou.",
        "Revisar",
        primary=True,
    ),
    "unknown": ModuleStatus(
        uk.State.PENDING,
        "Sem resposta",
        "Não consegui ler o estado deste módulo agora.",
        "Abrir",
    ),
}

#: Compatibilidade com quem só precisa do par estado/rótulo.
MODULE_LIFECYCLE_STATES: dict[str, tuple[uk.State, str]] = {
    key: (status.state, status.label) for key, status in MODULE_STATUSES.items()
}


def module_status(instance: dict[str, Any] | None) -> ModuleStatus:
    """Traduz o ciclo de vida do control plane para a linguagem do dono do servidor.

    `active` sem configuração publicada não é "no ar": é rascunho esperando o
    último passo — e dizer "no ar" aí é a mentira que vira ticket de suporte.
    """

    data = instance or {}
    lifecycle = str(data.get("lifecycle") or "unknown").strip().casefold()
    published = data.get("published_config_version_id") is not None
    if lifecycle == "active":
        return MODULE_STATUSES["active" if published else "unpublished"]
    if lifecycle == "inactive":
        return MODULE_STATUSES["inactive" if published else "pending"]
    return MODULE_STATUSES.get(lifecycle, MODULE_STATUSES["unknown"])


def _module_row(
    spec: ModuleSpec | DomainDashboardSpec,
    status: ModuleStatus | None,
    *,
    license_active: bool,
) -> dict[str, Any]:
    """Uma linha da lista: identidade à esquerda, o próximo passo à direita.

    Botão como acessório de seção é o que dá a leitura vertical — um módulo por
    linha, com a ação dele ao lado, em vez de tudo escondido dentro de um
    seletor.
    """

    lines = [uk.heading(spec.nome, emoji=spec.icon, level=3)]
    descricao = " ".join(str(getattr(spec, "descricao", "") or "").split())
    if status is not None and descricao:
        lines.append(
            f"{uk.badge(status.state, status.label, bold=True)} {uk.DASH} {descricao}"
        )
    elif status is not None:
        lines.append(uk.badge(status.state, status.label, bold=True))
    elif descricao:
        lines.append(descricao)
    footnotes = [status.hint] if status is not None else []
    plano = str(getattr(spec, "plano_minimo", "basico") or "basico")
    if plano != "basico":
        footnotes.append(f"Requer o plano {plano.capitalize()}")
    if footnotes:
        lines.append(uk.subtext(" · ".join(footnotes)))
    label = status.action if status is not None else "Abrir configuração"
    highlight = bool(status is not None and status.primary and license_active)
    return section(
        text_display(uk.clip("\n".join(lines))),
        accessory=button(
            custom_id=central_custom_id(spec.key, CENTRAL_OPEN_ACTION),
            label=label[:80],
            style=BUTTON_PRIMARY if highlight else BUTTON_SECONDARY,
            disabled=not license_active,
        ),
    )


def _status_summary(statuses: dict[str, ModuleStatus]) -> str:
    """Placar de uma linha: quantos módulos estão no ar e quantos esperam por você."""

    total = len(statuses)
    if not total:
        return ""
    no_ar = sum(1 for status in statuses.values() if status.state is uk.State.APPROVED)
    pendentes = sum(
        1
        for status in statuses.values()
        if status.state in (uk.State.PENDING, uk.State.RUNNING)
    )
    return uk.inline_fields(
        ("Módulos", total), ("No ar", no_ar), ("Aguardando você", pendentes)
    )


def build_payload(
    config: dict,
    page: int = 0,
    *,
    control_states: dict[str, dict[str, Any]] | None = None,
    license_active: bool = True,
) -> dict[str, Any]:
    """Primeira tela da Central: um módulo por linha, com estado e próximo passo."""

    del config, page
    specs = dashboard_specs()
    header = uk.heading("Central de Gestão Yuno", emoji="🟡")
    if license_active:
        header += "\n\nSelecione um módulo para configurar, revisar e publicar."
        accent = uk.BRAND
    else:
        header += "\n\n" + uk.empty_state(
            "Licença inativa neste servidor",
            "Os módulos ficam visíveis, mas nada é publicado até a licença voltar.",
        )
        accent = uk.DANGER

    if not specs:
        return payload(
            container(
                text_display(header),
                separator(spacing=1),
                text_display(
                    uk.empty_state(
                        "Nenhum módulo disponível",
                        "Nenhum módulo foi liberado para este servidor ainda.",
                    )
                ),
                accent_color=accent,
            )
        )

    statuses = (
        {key: module_status(control_states.get(key)) for key in specs}
        if control_states
        else {}
    )
    summary = _status_summary(statuses)
    if summary:
        header += f"\n\n{summary}"

    listed = list(specs.values())[:MAX_MODULE_ROWS]
    blocks: list[Any] = []
    for index, spec in enumerate(listed):
        if index:
            blocks.append(uk.rule())
        blocks.append(
            _module_row(spec, statuses.get(spec.key), license_active=license_active)
        )

    # O seletor só volta quando a lista não cabe: com poucos módulos ele seria um
    # segundo caminho para a mesma tela, e dois caminhos para a mesma coisa é o
    # que faz um painel parecer improvisado.
    actions = [module_navigation()] if len(specs) > MAX_MODULE_ROWS else []
    return payload(
        uk.panel(
            header=header,
            blocks=blocks,
            actions=actions,
            footer="Yuno · nenhuma alteração entra no ar antes da sua confirmação.",
            accent_color=accent,
        )
    )


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


async def refresh_existing(
    bot: commands.Bot,
    guild: discord.Guild,
    config: dict,
    *,
    control_states: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """Atualiza uma Central publicada sem criar mensagem nova no startup."""

    channel_id, message_id = dashboard_message_ref(config)
    if not channel_id or not message_id:
        return False
    channel = guild.get_channel(channel_id)
    if channel is None or not hasattr(channel, "fetch_message"):
        return False
    try:
        known_message = await channel.fetch_message(message_id)
        bot_member = guild.me
        if bot_member is not None and known_message.author.id != bot_member.id:
            return False
        await _edit_v2(
            bot,
            channel_id,
            message_id,
            build_payload(config, control_states=control_states),
        )
    except discord.HTTPException:
        return False
    return True


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
        await _deny(interaction, "Esta ação exige a Central publicada em um servidor.")
        return None
    bot = interaction.client
    try:
        config = await bot.api.get_guild_config(interaction.guild.id)
    except Exception:
        await _deny(interaction, "Não consegui revalidar a configuração da Central.")
        return None
    if not is_control_plane_admin(interaction.guild, interaction.user, config):
        await _deny(interaction, "Você não possui permissão para administrar a Central.")
        return None
    channel_id, message_id = dashboard_message_ref(config)
    if (
        interaction.message is None
        or channel_id != interaction.channel_id
        or message_id != interaction.message.id
    ):
        if interaction.message is None or not interaction.message.flags.ephemeral:
            await _deny(interaction, "Esta mensagem não é a Central ativa deste servidor.")
            return None
    return config


async def _deny(interaction: discord.Interaction, message: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


async def _acknowledge(interaction: discord.Interaction) -> None:
    """Reconhece a interacao antes de qualquer round-trip de API.

    O Discord da 3 segundos para responder. Qualquer chamada a API antes disso
    gasta esse orcamento, e quando o `defer` finalmente sai o token ja expirou:
    `discord.NotFound 404 (10062): Unknown interaction`, que para o usuario e
    simplesmente "o bot nao respondeu".

    E idempotente (`is_done()`), entao os `defer` que os modulos ja fazem lah na
    frente viram no-op em vez de erro.
    """

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
        await _deny(interaction, "Versão da Central não suportada.")
        return True

    try:
        component_type = int(data.get("component_type") or 0)
    except (TypeError, ValueError):
        component_type = 0

    if module_key == "core" and action_key == "select_module":
        values = list(data.get("values") or [])
        if component_type != 3 or not values:
            await _deny(interaction, "Seleção da Central inválida.")
            return True
        await _dispatch_page(interaction, str(values[0]))
        return True

    if _opens_module_page(module_key, action_key):
        await _dispatch_page(interaction, module_key)
        return True

    if component_type in _SELECT_COMPONENT_TYPES and not (
        module_key == "meta" and action_key == "select_goal"
    ):
        await _acknowledge(interaction)
    await _dispatch_action(interaction, module_key, action_key)
    return True


def _opens_module_page(module_key: str, action_key: str) -> bool:
    """O botão de cada linha da Central abre a página do módulo.

    A Central reserva `open`, mas cede a vez quando o módulo declara uma ação
    com esse nome: quem é dono do módulo decide o que o próprio botão faz.
    """

    return (
        action_key == CENTRAL_OPEN_ACTION
        and module_key != "core"
        and ui_registry.admin_action(module_key, CENTRAL_OPEN_ACTION) is None
    )


async def _dispatch_page(interaction: discord.Interaction, module_key: str) -> None:
    # Reconhecer aqui, e nao em cada chamador, porque este e o funil por onde
    # toda pagina de modulo passa -- e porque o que vem logo abaixo
    # (`_central_config`, depois o renderer do modulo) sao round-trips de API
    # que sozinhos ja estouram os 3 segundos do Discord. O botao de cada linha
    # da Central chegava aqui sem defer nenhum e morria com 10062.
    await _acknowledge(interaction)
    config = await _central_config(interaction)
    if config is None:
        return
    if module_key == CENTRAL_HOME_VALUE:
        await _render_home(interaction, config)
        return
    adapter = ui_registry.get(module_key)
    page = next(
        (item for item in (adapter.admin_pages if adapter else ()) if item.key == "overview"),
        None,
    )
    if page is None:
        await _deny(interaction, "Este módulo ainda não possui configuração na Central.")
        return
    await page.renderer(interaction, interaction.client.platform_api)


async def _render_home(interaction: discord.Interaction, config: dict) -> None:
    """Reescreve a mensagem da Central com a lista de módulos.

    As páginas de módulo editam a mesma mensagem, então a volta também edita —
    publicar uma Central nova a cada retorno deixaria o canal com várias.
    """

    channel_id = interaction.channel_id
    message_id = getattr(interaction.message, "id", None)
    if channel_id is None or message_id is None:
        await _deny(interaction, "Referência da Central indisponível.")
        return
    bot = interaction.client
    actor_id = getattr(interaction.user, "id", 0)
    states = await fetch_control_states(
        getattr(bot, "api", None),
        int(interaction.guild_id),
        actor_id,
        platform_api=getattr(bot, "platform_api", None),
    )
    await _edit_v2(
        bot,
        channel_id,
        message_id,
        build_payload(config, control_states=states),
    )


async def _dispatch_action(
    interaction: discord.Interaction, module_key: str, action_key: str
) -> None:
    if await _central_config(interaction) is None:
        return
    action = ui_registry.admin_action(module_key, action_key)
    if action is None:
        await _deny(interaction, "Ação administrativa indisponível.")
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
            await _deny(interaction, "Seleção da Central inválida.")
            return
        await _acknowledge(interaction)
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
            await _deny(interaction, "Versão da Central não suportada.")
            return
        if _opens_module_page(self.module_key, self.action_key):
            await _dispatch_page(interaction, self.module_key)
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
        await _acknowledge(interaction)
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
        await _acknowledge(interaction)
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
        await _acknowledge(interaction)
        await _dispatch_action(interaction, self.module_key, self.action_key)
