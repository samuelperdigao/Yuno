"""Central de Gestão baseada em Components V2 e adapters domain-first.

A tipografia e os tokens de cor vêm de `platform/ui_kit.py`, o mesmo kit
usado pelos painéis públicos dos módulos."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import io
from pathlib import Path
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
    media,
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
CENTRAL_PAGE_BUTTON_PATTERN = re.compile(
    r"^yuno:central:v(?P<version>\d+):(?P<module>core):"
    r"(?P<action>page_\d+)$"
)

#: Extrai o número de página do action_key dos botões Voltar/Avançar
#: (`page_0`, `page_1`, ...). O alvo já vem calculado no render — o clique só
#: precisa ler o número, nenhum estado de sessão é necessário.
PAGE_ACTION_RE = re.compile(r"^page_(\d+)$")
GROUP_ACTION_RE = re.compile(r"^group_(\d+)$")

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
CENTRAL_BANNER_FILENAME = "yuno-central-banner.jpg"
CENTRAL_BANNER_URL = f"attachment://{CENTRAL_BANNER_FILENAME}"
CENTRAL_BANNER_PATH = Path(__file__).with_name("assets") / CENTRAL_BANNER_FILENAME

MAX_MODULE_OPTIONS = 25

BUTTON_PRIMARY = 1
BUTTON_SECONDARY = 2


@dataclass(frozen=True)
class CentralRoute:
    """Contrato visual de uma tela, sem guardar histórico por usuário."""

    module_key: str
    key: str
    parent: tuple[str, str] | None = None
    next_route: tuple[str, str] | None = None


CENTRAL_ROUTES: dict[tuple[str, str], CentralRoute] = {
    ("core", "home"): CentralRoute("core", "home", next_route=("core", "modules")),
    ("core", "modules"): CentralRoute("core", "modules", parent=("core", "home")),
    ("core", "system"): CentralRoute("core", "system", parent=("core", "home")),
    ("meta", "overview"): CentralRoute(
        "meta", "overview", parent=("core", "modules"), next_route=("meta", "configuration")
    ),
    ("meta", "configuration"): CentralRoute(
        "meta", "configuration", parent=("meta", "overview"), next_route=("meta", "diagnostic")
    ),
    ("meta", "diagnostic"): CentralRoute(
        "meta", "diagnostic", parent=("meta", "configuration")
    ),
    ("farm_tickets", "overview"): CentralRoute(
        "farm_tickets", "overview", parent=("core", "modules"), next_route=("farm_tickets", "configuration")
    ),
    ("farm_tickets", "configuration"): CentralRoute(
        "farm_tickets", "configuration", parent=("farm_tickets", "overview"), next_route=("farm_tickets", "diagnostic")
    ),
    ("farm_tickets", "diagnostic"): CentralRoute(
        "farm_tickets", "diagnostic", parent=("farm_tickets", "configuration")
    ),
    ("parceria", "overview"): CentralRoute(
        "parceria", "overview", parent=("core", "modules"), next_route=("parceria", "configuration")
    ),
    ("parceria", "configuration"): CentralRoute(
        "parceria", "configuration", parent=("parceria", "overview")
    ),
    ("parceria", "diagnostic"): CentralRoute(
        "parceria", "diagnostic", parent=("parceria", "configuration")
    ),
    ("registration", "overview"): CentralRoute(
        "registration", "overview", parent=("core", "modules"), next_route=("registration", "configuration")
    ),
    ("registration", "configuration"): CentralRoute(
        "registration", "configuration", parent=("registration", "overview"), next_route=("registration", "diagnostic")
    ),
    ("registration", "diagnostic"): CentralRoute(
        "registration", "diagnostic", parent=("registration", "configuration")
    ),
    ("chest", "overview"): CentralRoute(
        "chest", "overview", parent=("core", "modules")
    ),
    ("chest", "inventory"): CentralRoute(
        "chest", "inventory", parent=("chest", "overview")
    ),
    ("chest", "access"): CentralRoute(
        "chest", "access", parent=("chest", "overview")
    ),
    ("chest", "configuration"): CentralRoute(
        "chest", "configuration", parent=("chest", "overview")
    ),
    ("chest", "diagnostic"): CentralRoute(
        "chest", "diagnostic", parent=("chest", "configuration")
    ),
}


def module_navigation(current_module: str | None = None) -> dict[str, Any]:
    """Navegação compacta usada pelas telas de módulo ainda não migradas.

    O catálogo completo vive na tela Nexus de Módulos, que pagina a 25
    opções. Telas internas não tentam truncar silenciosamente esse catálogo:
    quando ele excede o limite do Discord, oferecem retorno à lista paginada.
    """

    options: list[dict[str, Any]] = [
        {
            "label": "Central",
            "value": CENTRAL_HOME_VALUE,
            "description": "Voltar para a Home",
            "default": False,
        }
    ]
    specs = list(dashboard_specs().values())
    if len(specs) + 1 > MAX_MODULE_OPTIONS:
        return action_row(
            button(
                custom_id=route_custom_id("core", "modules"),
                label="MÓDULOS",
                style=BUTTON_SECONDARY,
            )
        )
    options.extend(_module_option(spec, current_module=current_module) for spec in specs)
    return action_row(
        string_select(
            custom_id=central_custom_id("core", "select_module"),
            options=options,
            placeholder="Trocar de módulo",
        )
    )


def _module_option(
    spec: ModuleSpec | DomainDashboardSpec, *, current_module: str | None = None
) -> dict[str, Any]:
    return {
        "label": str(spec.nome)[:100],
        "value": spec.key,
        "description": "Módulo atual" if spec.key == current_module else "Abrir módulo",
        "default": spec.key == current_module,
    }


def module_select(
    *, page: int = 0, selected_module: str | None = None
) -> tuple[dict[str, Any], int, int]:
    """Select principal da tela de módulos, sempre dentro do limite do Discord."""

    specs = list(dashboard_specs().values())
    if not specs:
        return text_display(uk.notice("Nenhum módulo disponível.")), 0, 1
    if selected_module is None and page == 0:
        selected_module = specs[0].key
    total_pages = max(1, (len(specs) + MAX_MODULE_OPTIONS - 1) // MAX_MODULE_OPTIONS)
    if selected_module in {spec.key for spec in specs}:
        page = next(index for index, spec in enumerate(specs) if spec.key == selected_module) // MAX_MODULE_OPTIONS
    page = max(0, min(page, total_pages - 1))
    start = page * MAX_MODULE_OPTIONS
    options = [
        _module_option(spec, current_module=selected_module)
        for spec in specs[start : start + MAX_MODULE_OPTIONS]
    ]
    return (
        action_row(
            string_select(
                custom_id=central_custom_id("core", "select_module"),
                options=options,
                placeholder="Selecionar módulo",
            )
        ),
        page,
        total_pages,
    )


def pagination_row(page: int, total_pages: int) -> dict[str, Any]:
    """Botões reais de Voltar/Avançar no rodapé da lista de módulos.

    O alvo de cada botão já vem calculado aqui — a página não muda, o
    `custom_id` é que já aponta pra próxima. `disabled` cobre as pontas
    (primeira e última página) sem o handler precisar saber onde está.
    """

    prev_page = max(0, page - 1)
    next_page = min(total_pages - 1, page + 1)
    return action_row(
        button(
            custom_id=central_custom_id("core", f"page_{prev_page}"),
            label="‹ VOLTAR",
            style=BUTTON_SECONDARY,
            disabled=page <= 0,
        ),
        button(
            custom_id=central_custom_id("core", f"page_{next_page}"),
            label="AVANÇAR ›",
            style=BUTTON_SECONDARY,
            disabled=page >= total_pages - 1,
        ),
    )


def route_custom_id(module_key: str, route: str) -> str:
    """ID estável de uma rota visual; não representa uma ação de negócio."""

    return central_custom_id(module_key, f"route_{route}")


def central_shell(data: dict[str, Any]) -> dict[str, Any]:
    """Aplica a identidade comum da Central a qualquer tela Components V2."""

    components = list(data.get("components") or [])
    if components:
        first = components[0]
        if (
            first.get("type") == 12
            and first.get("items") == [{"media": {"url": CENTRAL_BANNER_URL}}]
        ):
            return data
    return {**data, "components": [media(CENTRAL_BANNER_URL), *components]}


def _central_banner_file() -> discord.File:
    if not CENTRAL_BANNER_PATH.is_file():
        raise FileNotFoundError(f"Banner da Central ausente: {CENTRAL_BANNER_PATH}")
    return discord.File(
        io.BytesIO(CENTRAL_BANNER_PATH.read_bytes()),
        filename=CENTRAL_BANNER_FILENAME,
    )


def navigation_row(
    *,
    parent: tuple[str, str] | None = None,
    next_route: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """Rodapé determinístico. Rotas inexistentes ficam desabilitadas."""

    buttons = []
    if parent is not None:
        buttons.append(
            button(
                custom_id=route_custom_id(*parent),
                label="‹ VOLTAR",
                style=BUTTON_SECONDARY,
            )
        )
    if next_route is not None:
        buttons.append(
            button(
                custom_id=route_custom_id(*next_route),
                label="AVANÇAR ›",
                style=BUTTON_SECONDARY,
            )
        )
    return action_row(*buttons) if buttons else text_display(uk.subtext("NEXUS CORE // SESSION ACTIVE"))


def route_navigation(module_key: str, route: str) -> dict[str, Any]:
    """Renderiza o rodapé a partir da declaração da tela."""

    definition = CENTRAL_ROUTES.get((module_key, route))
    if definition is None:
        return navigation_row()
    return navigation_row(parent=definition.parent, next_route=definition.next_route)


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

    lines = [uk.heading(spec.nome, level=3)]
    descricao = " ".join(str(getattr(spec, "descricao", "") or "").split())
    if status is not None and descricao:
        lines.append(
            f"{uk.nexus_state('STATUS', status.label, state=status.state)}\n{descricao}"
        )
    elif status is not None:
        lines.append(uk.nexus_state("STATUS", status.label, state=status.state))
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


def _status_summary(
    statuses: dict[str, ModuleStatus], *, total_available: int | None = None
) -> str:
    """Resumo curto da Home, usando apenas estados já carregados."""

    total = len(statuses) if total_available is None else total_available
    if not total:
        return ""
    active = sum(1 for status in statuses.values() if status.state is uk.State.APPROVED)
    pending = sum(
        1
        for status in statuses.values()
        if status.state in (uk.State.PENDING, uk.State.RUNNING)
    )
    errors = sum(
        1
        for status in statuses.values()
        if status.state in (uk.State.BLOCKED, uk.State.FAILED)
    )
    error_value = "Nenhum erro crítico" if errors == 0 else errors
    return uk.nexus_metrics(
        ("CORE", "ONLINE"),
        ("MÓDULOS", total),
        ("ATIVOS", active),
        ("PENDÊNCIAS", pending),
        ("ERROS", error_value),
    )


def build_payload(
    config: dict,
    page: int = 0,
    *,
    control_states: dict[str, dict[str, Any]] | None = None,
    license_active: bool = True,
) -> dict[str, Any]:
    """Home resumida da Central; a lista completa vive em ``build_modules_payload``."""

    del config, page
    specs = dashboard_specs()
    header = [uk.nexus_title("CENTRAL DE COMANDO", path="CORE", subtitle="Interface administrativa do servidor")]
    if license_active:
        accent = uk.NEXUS_VIOLET
    else:
        header.append(uk.notice("Licença inativa neste servidor; nada será publicado.", kind="warning"))
        accent = uk.DANGER

    if not specs:
        return central_shell(payload(
            container(
                *[text_display(item) for item in header if item],
                separator(spacing=1),
                text_display(uk.nexus_notice("ESTADO", "Nenhum módulo disponível", "Nenhum subsistema foi liberado para este servidor.")),
                separator(spacing=1),
                route_navigation("core", "home"),
                accent_color=accent,
            )
        ))

    statuses = (
        {key: module_status(control_states.get(key)) for key in specs}
        if control_states
        else {}
    )
    summary = _status_summary(statuses, total_available=len(specs)) if control_states is not None else uk.nexus_metrics(("CORE", "ONLINE"), ("MÓDULOS", len(specs)))
    blocks = [text_display("// STATUS GLOBAL\n\n" + summary)]
    for key, status in statuses.items():
        if status.state in (uk.State.PENDING, uk.State.RUNNING):
            spec = specs[key]
            blocks.append(
                section(
                    text_display(uk.nexus_notice("REQUER ATENÇÃO", spec.nome, status.hint)),
                    accessory=button(
                        custom_id=route_custom_id("core", "modules"),
                        label="REVISAR",
                        style=BUTTON_PRIMARY if license_active else BUTTON_SECONDARY,
                        disabled=not license_active,
                    ),
                )
            )
        elif status.state in (uk.State.BLOCKED, uk.State.FAILED):
            spec = specs[key]
            blocks.append(
                section(
                    text_display(uk.nexus_notice("INCIDENTE", spec.nome, status.hint)),
                    accessory=button(
                        custom_id=route_custom_id(key, "diagnostic"),
                        label="DIAGNÓSTICO",
                        style=BUTTON_SECONDARY,
                    ),
                )
            )
    actions = [
        action_row(
            button(custom_id=route_custom_id("core", "modules"), label="MÓDULOS", style=BUTTON_PRIMARY),
            button(custom_id=route_custom_id("core", "system"), label="SISTEMA", style=BUTTON_SECONDARY),
        )
    ]
    footer = "SYS://YUNO/NEXUS • OPERATIONAL"

    return central_shell(payload(
        uk.panel(
            header=header,
            blocks=blocks,
            actions=actions,
            footer=footer,
            accent_color=accent,
        )
    ))


def build_modules_payload(
    config: dict,
    *,
    page: int = 0,
    selected_module: str | None = None,
    control_states: dict[str, dict[str, Any]] | None = None,
    license_active: bool = True,
) -> dict[str, Any]:
    """Tela escalável de módulos, com no máximo 25 opções por select."""

    del config
    specs = dashboard_specs()
    if selected_module is None and page == 0 and specs:
        selected_module = next(iter(specs))
    select_row, page, total_pages = module_select(page=page, selected_module=selected_module)
    statuses = (
        {key: module_status(control_states.get(key)) for key in specs}
        if control_states
        else {}
    )
    blocks: list[Any] = [select_row]
    if selected_module in specs:
        spec = specs[selected_module]
        status = statuses.get(selected_module)
        summary = [uk.heading(spec.nome, level=2)]
        if spec.descricao:
            summary.append(str(spec.descricao))
        if status:
            summary.append(uk.nexus_state("STATUS", status.label, state=status.state))
            summary.append(uk.subtext(status.hint))
        blocks.append(section(text_display(uk.clip("\n".join(summary))), accessory=button(custom_id=central_custom_id(selected_module, CENTRAL_OPEN_ACTION), label="Abrir", style=BUTTON_PRIMARY if license_active else BUTTON_SECONDARY, disabled=not license_active)))
    else:
        blocks.append(text_display(uk.notice("Selecione um módulo para ver o resumo e abrir sua administração.")))
    actions: list[dict[str, Any]] = [route_navigation("core", "modules")]
    if total_pages > 1:
        previous = max(0, page - 1)
        following = min(total_pages - 1, page + 1)
        actions.insert(0, action_row(
            button(custom_id=central_custom_id("core", f"group_{previous}"), label="‹ ANTERIORES", style=BUTTON_SECONDARY, disabled=page == 0),
            button(custom_id=central_custom_id("core", f"group_{following}"), label="MAIS MÓDULOS ›", style=BUTTON_SECONDARY, disabled=page == total_pages - 1),
        ))
    return central_shell(payload(
        uk.panel(
            header=[uk.nexus_title("MÓDULOS", path="CORE / MODULES", subtitle="Subsistemas conectados ao Nexus")],
            blocks=blocks,
            actions=actions,
            footer=f"SYS://YUNO/NEXUS • GRUPO {page + 1}/{total_pages}" if total_pages > 1 else "SYS://YUNO/NEXUS • SESSION ACTIVE",
            accent_color=uk.NEXUS_VIOLET if license_active else uk.DANGER,
        )
    ))


def build_system_payload(config: dict) -> dict[str, Any]:
    """Área Sistema baseada somente na configuração já existente da Central."""

    dashboard_ref = (config.get("settings") or {}).get("dashboard") or {}
    channel = dashboard_ref.get("panel_channel_id")
    message = "READY" if channel and dashboard_ref.get("panel_message_id") else "NOT CONFIGURED"
    registry = len(dashboard_specs())
    return central_shell(payload(
        uk.panel(
            header=[uk.nexus_title("SISTEMA", path="CORE / SYSTEM", subtitle="Estado do núcleo e serviços")],
            blocks=[
                text_display(uk.nexus_metrics(
                    ("MODULE_REGISTRY", f"{registry:02d}/{registry:02d}"),
                    ("CENTRAL_MESSAGE", message),
                    ("CENTRAL_CHANNEL", "CONFIGURED" if channel else "NOT CONFIGURED"),
                )),
                text_display(uk.nexus_notice(
                    "ESTADO",
                    "SYS://YUNO/NEXUS",
                    "Configuração persistida da Central e registro de módulos.",
                )),
                text_display(f"Canal da Central: <#{channel}>" if channel else "Canal da Central: ainda não definido"),
            ],
            actions=[route_navigation("core", "system")],
            footer="SYS://YUNO/NEXUS • SESSION ACTIVE",
            accent_color=uk.NEXUS_VIOLET,
        )
    ))


def build_module_diagnostic_payload(
    module_key: str, checks: list[dict[str, Any]] | None
) -> dict[str, Any]:
    rows = list(checks or [])
    if rows:
        content = "\n\n".join(
            f"**{str(item.get('status') or 'UNKNOWN').upper()}** · "
            f"{str(item.get('summary') or 'Sem resumo').strip()}"
            + (f"\n{str(item.get('detail')).strip()}" if item.get("detail") else "")
            for item in rows
        )
    else:
        content = "Nenhum diagnóstico retornado pela Platform API."
    return central_shell(payload(
        uk.panel(
            header=[uk.nexus_title("DIAGNÓSTICO", path=f"MODULES / {module_key}", subtitle="Verificação do subsistema")],
            blocks=[text_display(content)],
            actions=[
                action_row(button(
                    custom_id=route_custom_id(module_key, "diagnostic"),
                    label="ATUALIZAR",
                    style=BUTTON_SECONDARY,
                )),
                route_navigation(module_key, "diagnostic"),
            ],
            footer="SYS://YUNO/NEXUS • DIAGNOSTIC COMPLETE",
            accent_color=uk.NEXUS_VIOLET,
        )
    ))


def build_invalid_route_payload(message: str = "Esta rota da Central não é mais válida.") -> dict[str, Any]:
    """Estado seguro para links antigos ou forjados, com retorno funcional."""

    return central_shell(payload(
        uk.panel(
            header=[uk.breadcrumb("YUNO", "Estado"), uk.heading("Rota inválida")],
            blocks=[text_display(uk.notice(message, kind="warning"))],
            actions=[action_row(button(custom_id=route_custom_id("core", "home"), label="Voltar à Home", style=BUTTON_SECONDARY))],
            accent_color=uk.WARNING,
        )
    ))


async def _send_v2(bot: commands.Bot, channel_id: int, data: dict) -> int:
    return await send_message(
        bot,
        channel_id,
        central_shell(data),
        files=[_central_banner_file()],
    )


async def _edit_v2(
    bot: commands.Bot,
    channel_id: int,
    message_id: int,
    data: dict,
    *,
    attach_banner: bool = False,
) -> None:
    """Atualiza a Central sem reenviar o banner já persistido na mensagem.

    O ``attachment://`` do Media Gallery continua válido para anexos existentes.
    Reenviar o mesmo arquivo em cada navegação cria uma atualização multipart
    inválida no Discord e deixa a interação já reconhecida sem conseguir editar
    a mensagem. O anexo só é necessário ao criar ou migrar uma Central legada.
    """
    await edit_message(
        bot,
        channel_id,
        message_id,
        central_shell(data),
        files=[_central_banner_file()] if attach_banner else None,
    )


async def edit_central_message(
    bot: commands.Bot, channel_id: int, message_id: int, data: dict[str, Any]
) -> None:
    """Edita uma tela interna usando o mesmo shell e banner da Central."""

    await _edit_v2(bot, channel_id, message_id, data)


async def _edit_existing_central(
    bot: commands.Bot, channel_id: int, message_id: int, data: dict
) -> None:
    """Edita uma Central existente e migra uma mensagem legada uma única vez."""

    try:
        await _edit_v2(bot, channel_id, message_id, data)
    except discord.HTTPException:
        # Mensagens publicadas antes do banner não possuem o attachment que o
        # Media Gallery referencia. Só nesse caso reenviamos o arquivo.
        await _edit_v2(bot, channel_id, message_id, data, attach_banner=True)


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
            await _edit_existing_central(bot, channel.id, previous_message_id, data)
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
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.HTTPException:
            return False
    if channel is None or not hasattr(channel, "fetch_message"):
        return False
    try:
        known_message = await channel.fetch_message(message_id)
        bot_member = guild.me
        if bot_member is not None and known_message.author.id != bot_member.id:
            return False
        await _edit_existing_central(
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
    async def fetch_state(adapter: Any) -> tuple[str, dict[str, Any]]:
        try:
            state = await platform_api.module_instance(
                guild_id, adapter.module_key
            )
        except Exception:
            state = {"lifecycle": "unknown"}
        return adapter.module_key, state

    states = await asyncio.gather(
        *(fetch_state(adapter) for adapter in ui_registry.all())
    )
    return dict(states)


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

    if module_key == "core":
        group_match = GROUP_ACTION_RE.fullmatch(action_key)
        if group_match is not None:
            await _dispatch_modules_group(interaction, int(group_match.group(1)))
            return True
        page_match = PAGE_ACTION_RE.fullmatch(action_key)
        if page_match is not None:
            await _dispatch_home_page(interaction, int(page_match.group(1)))
            return True
        if action_key.startswith("route_"):
            await _dispatch_visual_route(interaction, module_key, action_key[6:])
            return True
        if action_key == "select_module":
            values = list(data.get("values") or [])
            if component_type != 3 or not values:
                await _deny(interaction, "Seleção da Central inválida.")
                return True
            await _dispatch_page(interaction, str(values[0]))
            return True

    if action_key.startswith("route_"):
        await _dispatch_visual_route(interaction, module_key, action_key[6:])
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


async def _dispatch_visual_route(
    interaction: discord.Interaction, module_key: str, route: str
) -> None:
    """Resolve somente rotas visuais declaradas pelo piloto."""

    await _acknowledge(interaction)
    config = await _central_config(interaction)
    if config is None:
        return
    if module_key == "core":
        if route == "home":
            await _render_home(interaction, config)
            return
        if route == "modules":
            await _render_modules(interaction, config)
            return
        if route == "system":
            await _edit_v2(
                interaction.client,
                interaction.channel_id,
                interaction.message.id,
                build_system_payload(config),
            )
            return
    if module_key == "parceria":
        target_action = {
            "overview": None,
            "configuration": "open_system",
            "diagnostic": "diagnose",
        }.get(route, "__invalid__")
        if target_action == "__invalid__":
            await _render_invalid_route(interaction)
            return
        if target_action is None:
            await _dispatch_page(interaction, module_key)
            return
        await _dispatch_action(interaction, module_key, target_action)
        return
    if module_key == "chest":
        target_action = {
            "overview": None,
            "inventory": "inventory",
            "access": "chest_access",
            "configuration": "chest_settings",
            "diagnostic": "diagnose",
        }.get(route, "__invalid__")
        if target_action == "__invalid__":
            await _render_invalid_route(interaction)
            return
        if target_action is None:
            await _dispatch_page(interaction, module_key)
            return
        await _dispatch_action(interaction, module_key, target_action)
        return
    if module_key == "farm_tickets" and route != "diagnostic":
        target_action = {
            "overview": None,
            "configuration": "open_system",
        }.get(route, "__invalid__")
        if target_action == "__invalid__":
            await _render_invalid_route(interaction)
            return
        if target_action is None:
            await _dispatch_page(interaction, module_key)
            return
        await _dispatch_action(interaction, module_key, target_action)
        return
    if module_key == "registration" and route != "diagnostic":
        target_action = {
            "overview": None,
            "configuration": "open_system",
        }.get(route, "__invalid__")
        if target_action == "__invalid__":
            await _render_invalid_route(interaction)
            return
        if target_action is None:
            await _dispatch_page(interaction, module_key)
            return
        await _dispatch_action(interaction, module_key, target_action)
        return
    if route == "diagnostic" and module_key != "core":
        try:
            checks = await interaction.client.platform_api.diagnostics(
                interaction.guild_id, module_key
            )
        except Exception:
            checks = [{
                "status": "ERROR",
                "summary": "Diagnóstico indisponível.",
                "detail": "A Platform API não respondeu à verificação.",
            }]
        await _edit_v2(
            interaction.client,
            interaction.channel_id,
            interaction.message.id,
            build_module_diagnostic_payload(module_key, checks),
        )
        return
    if module_key == "meta":
        target_action = {
            "overview": None,
            "configuration": "settings",
        }.get(route, "__invalid__")
        if target_action == "__invalid__":
            await _render_invalid_route(interaction)
            return
        if target_action is None:
            await _dispatch_page(interaction, module_key)
            return
        await _dispatch_action(interaction, module_key, target_action)
        return
    await _render_invalid_route(interaction)


async def _render_home(
    interaction: discord.Interaction, config: dict, *, page: int = 0
) -> None:
    """Reescreve a mensagem da Central com a Home resumida.

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


async def _render_modules(interaction: discord.Interaction, config: dict, *, page: int = 0) -> None:
    channel_id = interaction.channel_id
    message_id = getattr(interaction.message, "id", None)
    if channel_id is None or message_id is None:
        await _deny(interaction, "Referência da Central indisponível.")
        return
    bot = interaction.client
    states = await fetch_control_states(
        getattr(bot, "api", None),
        int(interaction.guild_id),
        getattr(interaction.user, "id", 0),
        platform_api=getattr(bot, "platform_api", None),
    )
    await _edit_v2(
        bot,
        channel_id,
        message_id,
        build_modules_payload(config, page=page, control_states=states),
    )


async def _render_invalid_route(interaction: discord.Interaction) -> None:
    channel_id = interaction.channel_id
    message_id = getattr(interaction.message, "id", None)
    if channel_id is None or message_id is None:
        await _deny(interaction, "Rota inválida. Volte para a Home da Central.")
        return
    await _edit_v2(
        interaction.client,
        channel_id,
        message_id,
        build_invalid_route_payload(),
    )


async def _dispatch_home_page(interaction: discord.Interaction, page: int) -> None:
    """Rejeita a paginação antiga, que não é mais uma rota válida."""

    del page
    await _acknowledge(interaction)
    config = await _central_config(interaction)
    if config is None:
        return
    await _render_invalid_route(interaction)


async def _dispatch_modules_group(interaction: discord.Interaction, page: int) -> None:
    await _acknowledge(interaction)
    config = await _central_config(interaction)
    if config is None:
        return
    total_pages = max(
        1,
        (len(dashboard_specs()) + MAX_MODULE_OPTIONS - 1) // MAX_MODULE_OPTIONS,
    )
    if page >= total_pages:
        await _render_invalid_route(interaction)
        return
    await _render_modules(interaction, config, page=page)


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


class CentralPageButton(
    _CentralDynamic,
    discord.ui.DynamicItem[discord.ui.Button],
    template=CENTRAL_PAGE_BUTTON_PATTERN,
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
        match = PAGE_ACTION_RE.fullmatch(self.action_key)
        if match is None:
            await _deny(interaction, "Página da Central inválida.")
            return
        await _dispatch_home_page(interaction, int(match.group(1)))


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
