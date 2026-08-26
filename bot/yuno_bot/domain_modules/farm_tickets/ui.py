from __future__ import annotations

from collections.abc import Sequence
from math import ceil
from typing import Any

import discord

from yuno_bot.domain_modules.farm_tickets.api import module_api
from yuno_bot.platform.components_v2 import (
    action_row,
    button,
    container,
    media_gallery,
    modal_label,
    modal_payload,
    payload,
    separator,
    text_display,
)
from yuno_bot.platform.contracts import (
    ComponentsV2Payload,
    InteractionResult,
    RoutedContext,
)
from yuno_bot.platform.router import RoutedModal, module_custom_id
from yuno_bot.platform import ui_kit as uk

_PROOF_PAGES: dict[tuple[int, int | None, str], int] = {}


MODULE_KEY = "farm_tickets"
CONTRACT_VERSION = 2
ACCENT_COLOR = uk.BRAND
ITEMS_PER_MODAL = 5
PROOFS_PER_PAGE = 10

# O vocabulário do domínio traduzido para os estados do kit: é daqui que saem a
# cor do container e o emoji do selo, do mesmo jeito nos três módulos.
TICKET_STATES: dict[str, tuple[uk.State, str]] = {
    "IN_PROGRESS": (uk.State.RUNNING, "Em andamento"),
    "APPROVED": (uk.State.APPROVED, "Aprovado"),
    "FINALIZED_INCOMPLETE": (uk.State.FAILED, "Finalizado incompleto"),
    "CLOSED_MANUALLY": (uk.State.CLOSED, "Encerrado manualmente"),
}

#: Rodapé do painel público. Descreve a regra de permissão que o próprio
#: módulo publica (`admin.build_grants`), sem citar cargo, prazo ou guild.
GLOBAL_PANEL_FOOTER = (
    "Abrir o próprio ticket é liberado para todos os membros. "
    "As demais ações são restritas aos cargos administradores."
)

GLOBAL_ACTIONS = (
    ("open_ticket", "Abrir Ticket", "🎫", 3),
    ("open_for_member", "Abrir para Membro", "👤", 1),
    ("delete_ticket_global", "Excluir Ticket", "🗑️", 4),
)

TICKET_ACTION_ROWS = (
    (
        ("create_entry", "Lançar Farm", "📦", 3),
        ("edit_entry", "Editar Lançamento", "✏️", 2),
        ("list_proofs", "Ver Comprovantes", "🖼️", 2),
        ("withdraw", "Recolhimento", "📤", 1),
        ("assign", "Assumir Ticket", "👮", 2),
    ),
    (
        ("approve", "Aprovar Meta", "✅", 3),
        ("finalize", "Finalizar Ticket", "🔒", 4),
    ),
)


def ticket_custom_id(surface: str, action: str) -> str:
    return module_custom_id(MODULE_KEY, surface, action, version=CONTRACT_VERSION)


def _safe_text(value: Any, *, fallback: str = "Não informado") -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:500] if text else fallback


def _discord_timestamp(value: Any, style: str = "f") -> str:
    return uk.timestamp(value, style)


def _chunk_lines(lines: Sequence[str], *, limit: int = uk.CHUNK_LIMIT) -> list[str]:
    """Mesma regra de corte do kit — um único teto de 4000 por `text_display`."""

    return uk.chunk_lines(lines, limit=limit)


def _action_button(
    surface: str,
    action: str,
    label: str,
    emoji: str,
    style: int,
    *,
    disabled: bool = False,
) -> dict[str, Any]:
    return button(
        custom_id=ticket_custom_id(surface, action),
        label=label,
        emoji=emoji,
        style=style,
        disabled=disabled,
    )


def _instruction_steps(value: Any) -> str:
    """Instruções configuradas na Central viram onboarding numerado.

    Aceita lista de textos, lista de pares título/corpo ou um texto com uma
    instrução por linha. Sem instrução configurada não inventa nenhuma — o
    conteúdo é do cliente, o formato é do kit.
    """

    if not value:
        return ""
    if isinstance(value, str):
        items: list[Any] = [line for line in value.splitlines() if line.strip()]
    else:
        items = list(value)
    entries: list[Any] = []
    for item in items:
        if isinstance(item, dict):
            entries.append((item.get("title") or item.get("label"), item.get("body") or ""))
        elif isinstance(item, (list, tuple)):
            entries.append(item)
        else:
            entries.append((str(item), ""))
    return uk.steps(*entries)


async def render_global(context: dict[str, Any]) -> ComponentsV2Payload:
    config = context.get("config") or {}
    title = _safe_text(config.get("panel_title"), fallback="Tickets de Farm")
    description = _safe_text(
        config.get("panel_description"),
        fallback="Abra seu ticket de ciclo ou use as ações administrativas disponíveis.",
    )
    controls = action_row(
        *(
            _action_button("global", action, label, emoji, style)
            for action, label, emoji, style in GLOBAL_ACTIONS
        )
    )
    return ComponentsV2Payload(
        payload(
            uk.panel(
                header=f"{uk.heading(title, emoji='🎫')}\n\n{description}",
                blocks=[_instruction_steps(config.get("panel_instructions"))],
                actions=[controls],
                footer=config.get("panel_footer") or GLOBAL_PANEL_FOOTER,
                accent_color=ACCENT_COLOR,
            )
        )
    )


def _measure(value: Any, unit: Any) -> str:
    return uk.quantity(value if value is not None else 0, unit, fallback="0")


def _ticket_footer(ticket: dict[str, Any], config: dict[str, Any]) -> str:
    """Regra do sistema no rodapé, sempre derivada do ciclo — nunca prazo literal."""

    configured = str(config.get("panel_footer") or "").strip()
    if configured:
        return configured
    ends_at = uk.timestamp(ticket.get("cycle_ends_at"), "R", fallback="")
    if not ends_at:
        return ""
    return f"Este ticket segue o ciclo da Meta e encerra {ends_at}."


async def render_ticket(context: dict[str, Any]) -> ComponentsV2Payload:
    ticket = context.get("ticket") or {}
    config = context.get("config") or {}
    member_name = _safe_text(
        ticket.get("member_display_name") or ticket.get("member_name"),
        fallback="Membro indisponível",
    )
    status = _safe_text(ticket.get("status"), fallback="Estado indisponível")
    progress = ticket.get("progress_percent", context.get("progress_percent"))
    responsible_id = str(
        ticket.get("assigned_admin_id") or ticket.get("assigned_to") or ""
    )
    responsible = (
        f"<@{responsible_id}>"
        if responsible_id.isascii() and responsible_id.isdigit()
        else "Não atribuído"
    )
    state, state_text = TICKET_STATES.get(status, (None, status))
    status_label = uk.badge(state, state_text) if state is not None else status

    objective_lines = [
        uk.objective_row(
            objective.get("name"),
            objective.get("launched"),
            objective.get("target"),
            unit=objective.get("unit"),
            remaining=objective.get("remaining_to_goal", 0),
            remaining_label="Restante da Meta",
            extra=(
                f"Recolhido: {_measure(objective.get('withdrawn'), objective.get('unit'))}",
                f"Saldo: {_measure(objective.get('available'), objective.get('unit'))}",
            ),
        )
        for objective in ticket.get("objectives") or []
    ]
    objective_chunks = _chunk_lines(
        objective_lines
        or [uk.empty_state("Sem objetivo neste ciclo", "A Meta ainda não definiu o que farmar.")]
    )
    period = (
        f"{_discord_timestamp(ticket.get('cycle_starts_at'))} → "
        f"{_discord_timestamp(ticket.get('cycle_ends_at'))}"
    )
    ends_in = uk.timestamp(ticket.get("cycle_ends_at"), "R", fallback="")
    if ends_in:
        period = f"{period}\nEncerra {ends_in}"
    member_left = (
        f"\n\n{uk.badge(uk.State.BLOCKED, 'Membro saiu do servidor', bold=True)}"
        if ticket.get("member_left_at")
        else ""
    )

    supplied_actions = ticket.get("allowed_actions", context.get("allowed_actions"))
    allowed_actions = set(supplied_actions) if supplied_actions is not None else None
    rows = []
    for definitions in TICKET_ACTION_ROWS:
        rows.append(
            action_row(
                *(
                    _action_button(
                        "ticket",
                        action,
                        label,
                        emoji,
                        style,
                        disabled=allowed_actions is not None
                        and action not in allowed_actions,
                    )
                    for action, label, emoji, style in definitions
                )
            )
        )

    identity = "\n\n".join(
        (
            uk.field("Membro", f"<@{ticket.get('member_id')}> · {_safe_text(ticket.get('base_nickname'))}", emoji="👤"),
            uk.field("ID do Jogo", f"`{_safe_text(ticket.get('player_id'))}`", emoji="🎮"),
        )
    )

    return ComponentsV2Payload(
        payload(
            uk.panel(
                header=uk.heading(f"Ticket de Farm · {member_name}", emoji="🎫"),
                blocks=[
                    uk.avatar_section(
                        identity,
                        avatar_url=context.get("avatar_url"),
                        description="Foto do membro",
                    ),
                    uk.space(),
                    "\n\n".join(
                        (
                            uk.field("Meta e ciclo", _safe_text(ticket.get("goal_name")), emoji="🎯"),
                            uk.field("Período", period, emoji="📅"),
                            uk.field("Status", status_label, emoji="📌"),
                        )
                    ),
                    uk.rule(),
                    uk.progress_block(progress),
                    uk.space(),
                    uk.field("Objetivos", objective_chunks[0], emoji="📦"),
                    *objective_chunks[1:],
                    uk.rule(),
                    "\n\n".join(
                        (
                            uk.field(
                                "Operação",
                                uk.inline_fields(
                                    ("Lançamentos", ticket.get("entry_count", 0)),
                                    ("Recolhimentos", ticket.get("withdrawal_count", 0)),
                                ),
                                emoji="🧾",
                            ),
                            f"{uk.field('Responsável', responsible, emoji='👮')}{member_left}",
                        )
                    ),
                ],
                actions=rows,
                footer=_ticket_footer(ticket, config),
                state=state,
                accent_color=None if state is not None else ACCENT_COLOR,
            )
        )
    )


def _proof_url(proof: str | dict[str, Any]) -> str:
    if isinstance(proof, str):
        return proof.strip()
    return str(
        proof.get("url") or proof.get("display_url") or proof.get("storage_url") or ""
    ).strip()


def proof_gallery_payload(
    proofs: Sequence[str | dict[str, Any]], *, page: int = 0
) -> ComponentsV2Payload:
    urls = [
        url
        for proof in proofs
        if (url := _proof_url(proof)).startswith(("https://", "http://"))
    ]
    total_pages = max(1, ceil(len(urls) / PROOFS_PER_PAGE))
    current_page = min(max(page, 0), total_pages - 1)
    start = current_page * PROOFS_PER_PAGE
    visible = urls[start : start + PROOFS_PER_PAGE]
    components: list[dict[str, Any]] = [
        text_display(uk.heading("Comprovantes", emoji="🖼️")),
        text_display(uk.subtext(f"Página {current_page + 1} de {total_pages}")),
    ]
    if visible:
        components.extend((separator(), media_gallery(visible)))
    else:
        components.append(
            text_display(
                uk.empty_state(
                    "Nenhum comprovante disponível",
                    "Os comprovantes aparecem aqui assim que um lançamento for enviado.",
                )
            )
        )
    if total_pages > 1:
        components.append(
            action_row(
                _action_button(
                    "ticket",
                    "proofs_previous",
                    "Anterior",
                    "⬅️",
                    2,
                    disabled=current_page == 0,
                ),
                _action_button(
                    "ticket",
                    "proofs_next",
                    "Próxima",
                    "➡️",
                    2,
                    disabled=current_page == total_pages - 1,
                ),
            )
        )
    return ComponentsV2Payload(
        payload(container(*components, accent_color=ACCENT_COLOR))
    )


def component_count(value: Any) -> int:
    if isinstance(value, list):
        return sum(component_count(item) for item in value)
    if not isinstance(value, dict):
        return 0
    own = 1 if "type" in value else 0
    return (
        own
        + component_count(value.get("components", []))
        + component_count(value.get("accessory"))
    )


class LabelledRoutedModal(RoutedModal):
    """discord.py 2.4 modal with Discord's Label component payload."""

    def __init__(self, *, title: str, action_key: str, panel: dict[str, Any]) -> None:
        super().__init__(
            title=title,
            module_key=MODULE_KEY,
            surface="ticket",
            action_key=action_key,
            panel=panel,
        )
        self.custom_id = ticket_custom_id("ticket", action_key)
        self._descriptions: dict[str, str] = {}

    def add_labelled_input(
        self,
        *,
        label: str,
        custom_id: str,
        description: str = "",
        placeholder: str | None = None,
        value: str | None = None,
        required: bool = True,
        style: discord.TextStyle = discord.TextStyle.short,
        max_length: int = 20,
    ) -> None:
        if len(self.children) >= ITEMS_PER_MODAL:
            raise ValueError("Cada etapa aceita no máximo cinco campos.")
        field = discord.ui.TextInput(
            label=label[:45],
            custom_id=custom_id,
            placeholder=placeholder,
            default=value,
            required=required,
            style=style,
            max_length=max_length,
        )
        self.add_item(field)
        if description:
            self._descriptions[custom_id] = description

    def to_dict(self) -> dict[str, Any]:
        labels = []
        for child in self.children:
            component = child.to_component_dict()
            display_label = str(
                component.pop("label", getattr(child, "label", "Campo"))
            )
            custom_id = str(component.get("custom_id") or "")
            labels.append(
                modal_label(
                    label=display_label,
                    description=self._descriptions.get(custom_id),
                    component=component,
                )
            )
        return modal_payload(title=self.title, custom_id=self.custom_id, labels=labels)

    def _refresh(
        self, interaction: discord.Interaction, components: Sequence[dict[str, Any]]
    ) -> None:
        normalized: list[dict[str, Any]] = []
        for component in components:
            if component.get("type") == 18 and isinstance(
                component.get("component"), dict
            ):
                normalized.append(component["component"])
            elif component.get("type") == 1:
                normalized.extend(component.get("components") or [])
            else:
                normalized.append(component)
        super()._refresh(interaction, normalized)


class TicketItemsModal(LabelledRoutedModal):
    def __init__(
        self,
        *,
        panel: dict[str, Any],
        action_key: str,
        items: Sequence[dict[str, Any]],
        page: int = 0,
        title: str = "Registrar entrega",
    ) -> None:
        if not items:
            raise ValueError("A etapa precisa de ao menos um objetivo.")
        total_pages = max(1, ceil(len(items) / ITEMS_PER_MODAL))
        current_page = min(max(page, 0), total_pages - 1)
        start = current_page * ITEMS_PER_MODAL
        visible = list(items[start : start + ITEMS_PER_MODAL])
        panel_context = {
            **panel,
            "ui_page": current_page,
            "ui_item_keys": [
                str(item.get("objective_id") or item.get("id") or start + index)
                for index, item in enumerate(visible)
            ],
        }
        modal_title = (
            f"{title} · {current_page + 1}/{total_pages}" if total_pages > 1 else title
        )
        super().__init__(title=modal_title, action_key=action_key, panel=panel_context)
        for index, item in enumerate(visible):
            name = _safe_text(
                item.get("name"), fallback=f"Objetivo {start + index + 1}"
            )
            unit = _safe_text(item.get("unit"), fallback="unidades")
            available = item.get("available")
            description = f"Unidade: {unit}"
            if available is not None:
                description += f" · disponível: {available}"
            self.add_labelled_input(
                label=name,
                custom_id=f"farm_ticket_value_{index}",
                description=description,
                placeholder="Informe a quantidade",
                value=str(item["value"]) if item.get("value") is not None else None,
            )


class TicketReasonModal(LabelledRoutedModal):
    def __init__(self, *, panel: dict[str, Any], action_key: str, title: str) -> None:
        super().__init__(title=title, action_key=action_key, panel=panel)
        self.add_labelled_input(
            label="Motivo",
            custom_id="farm_ticket_reason",
            description="Explique a decisão para o histórico do ticket.",
            placeholder="Descreva o motivo",
            style=discord.TextStyle.paragraph,
            max_length=500,
        )


def _modal_values(data: Any) -> dict[str, str]:
    values: dict[str, str] = {}
    if isinstance(data, list):
        for item in data:
            values.update(_modal_values(item))
    elif isinstance(data, dict):
        custom_id = data.get("custom_id")
        if custom_id is not None and "value" in data:
            values[str(custom_id)] = str(data.get("value") or "")
        values.update(_modal_values(data.get("components")))
        values.update(_modal_values(data.get("component")))
    return values


async def _runtime_action(
    context: RoutedContext, action_key: str, payload_data: dict[str, Any] | None = None
) -> InteractionResult:
    dispatcher = getattr(module_api(context.api), "farm_tickets_action", None)
    if dispatcher is None:
        return InteractionResult(
            content="Esta ação será habilitada quando a API de Tickets de Farm estiver disponível."
        )
    result = await dispatcher(
        context.actor.guild_id,
        action_key,
        resource_id=str(context.panel.get("resource_id") or ""),
        actor=context.actor.as_payload(),
        payload=payload_data or {},
    )
    return InteractionResult(
        content=str((result or {}).get("message") or "Ação concluída.")
    )


def _form_modal(
    *,
    panel: dict[str, Any],
    action_key: str,
    form: dict[str, Any],
    ticket_revision: int,
    title: str,
) -> TicketItemsModal:
    return TicketItemsModal(
        panel={
            **panel,
            "form_draft_id": form["id"],
            "form_revision": form["revision"],
            "ticket_revision": ticket_revision,
        },
        action_key=action_key,
        items=form["objectives"],
        page=int(form["step"]),
        title=title,
    )


async def _items_action(
    context: RoutedContext, action_key: str, title: str
) -> InteractionResult:
    dispatcher = getattr(module_api(context.api), "farm_tickets_action", None)
    if dispatcher is None:
        return InteractionResult(
            content="A API de Tickets de Farm não está disponível."
        )
    values = _modal_values((context.interaction.data or {}).get("components"))
    if values:
        item_keys = list(context.panel.get("ui_item_keys") or [])
        result = await dispatcher(
            context.actor.guild_id,
            action_key,
            resource_id=str(context.panel.get("resource_id") or ""),
            actor=context.actor.as_payload(),
            payload={
                "phase": "save_step",
                "draft_id": context.panel["form_draft_id"],
                "draft_revision": context.panel["form_revision"],
                "ticket_revision": context.panel["ticket_revision"],
                "step": int(context.panel.get("ui_page") or 0),
                "values": [
                    {
                        "objective_id": objective_id,
                        "amount": values.get(f"farm_ticket_value_{index}", "0"),
                    }
                    for index, objective_id in enumerate(item_keys)
                ],
                "interaction_id": str(context.interaction.id),
                "idempotency_key": f"interaction:{context.interaction.id}",
            },
        )
        if result.get("form"):
            return InteractionResult(
                modal=_form_modal(
                    panel=context.panel,
                    action_key=action_key,
                    form=result["form"],
                    ticket_revision=int(context.panel["ticket_revision"]),
                    title=title,
                )
            )
        return InteractionResult(
            content=str(result.get("message") or "Operação concluída.")
        )
    result = await dispatcher(
        context.actor.guild_id,
        action_key,
        resource_id=str(context.panel.get("resource_id") or ""),
        actor=context.actor.as_payload(),
        payload={
            "phase": "open_form",
            "target_entry_id": context.panel.get("selected_entry_id"),
            "idempotency_key": f"interaction:{context.interaction.id}:form",
        },
    )
    form = result.get("form")
    if not form:
        return InteractionResult(
            content=str(result.get("message") or "Formulário indisponível.")
        )
    return InteractionResult(
        modal=_form_modal(
            panel=context.panel,
            action_key=action_key,
            form=form,
            ticket_revision=int(result["ticket"]["revision"]),
            title=title,
        )
    )


class MemberTicketView(discord.ui.View):
    """Seletor paginado dos humanos em cache na guild, sem bots."""

    def __init__(
        self, context: RoutedContext, *, action_key: str, page: int = 0
    ) -> None:
        super().__init__(timeout=300)
        self.context = context
        self.action_key = action_key
        guild = context.interaction.guild
        humans = (
            []
            if guild is None
            else [member for member in guild.members if not member.bot]
        )
        self.members = sorted(
            humans, key=lambda member: (member.display_name.casefold(), member.id)
        )
        last_page = max(0, (len(self.members) - 1) // 25)
        self.page = min(max(page, 0), last_page)
        visible = self.members[self.page * 25 : self.page * 25 + 25]
        options = [
            discord.SelectOption(
                label=member.display_name[:100],
                value=str(member.id),
                description=f"Discord ID {member.id}"[:100],
            )
            for member in visible
        ]
        select = discord.ui.Select(
            placeholder="Selecione um membro",
            options=options
            or [discord.SelectOption(label="Nenhum membro humano", value="none")],
            disabled=not options,
        )
        select.callback = self._selected  # type: ignore[method-assign]
        self.select = select
        self.add_item(select)
        if len(self.members) > 25:
            previous = discord.ui.Button(
                label="Anterior",
                style=discord.ButtonStyle.secondary,
                disabled=self.page == 0,
            )
            following = discord.ui.Button(
                label="Próxima",
                style=discord.ButtonStyle.secondary,
                disabled=self.page == last_page,
            )
            previous.callback = self._previous  # type: ignore[method-assign]
            following.callback = self._following  # type: ignore[method-assign]
            self.add_item(previous)
            self.add_item(following)

    async def _selected(self, interaction: discord.Interaction) -> None:
        result = await module_api(self.context.api).farm_tickets_action(
            self.context.actor.guild_id,
            self.action_key,
            resource_id="",
            actor=self.context.actor.as_payload(),
            payload={
                "member_id": self.select.values[0],
                "idempotency_key": f"interaction:{interaction.id}:{self.action_key}",
            },
        )
        await interaction.response.edit_message(
            content=str(result.get("message") or "Ação concluída."), view=None
        )

    async def _previous(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            view=MemberTicketView(
                self.context, action_key=self.action_key, page=self.page - 1
            )
        )

    async def _following(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            view=MemberTicketView(
                self.context, action_key=self.action_key, page=self.page + 1
            )
        )


class EntrySelectView(discord.ui.View):
    def __init__(
        self, context: RoutedContext, entries: list[dict[str, Any]], *, page: int = 0
    ) -> None:
        super().__init__(timeout=300)
        self.context = context
        self.entries = entries
        last_page = max(0, (len(entries) - 1) // 25)
        self.page = min(max(page, 0), last_page)
        options = []
        for entry in entries[self.page * 25 : self.page * 25 + 25]:
            summary = ", ".join(
                f"{item['name']}: {item['amount']}" for item in entry.get("items") or []
            )
            options.append(
                discord.SelectOption(
                    label=f"Lançamento #{entry['number']}",
                    value=entry["id"],
                    description=(summary or "Sem itens")[:100],
                )
            )
        select = discord.ui.Select(
            placeholder="Selecione o lançamento", options=options
        )
        select.callback = self._selected  # type: ignore[method-assign]
        self.select = select
        self.add_item(select)
        if len(entries) > 25:
            previous = discord.ui.Button(
                label="Anterior",
                style=discord.ButtonStyle.secondary,
                disabled=self.page == 0,
            )
            following = discord.ui.Button(
                label="Próxima",
                style=discord.ButtonStyle.secondary,
                disabled=self.page == last_page,
            )
            previous.callback = self._previous  # type: ignore[method-assign]
            following.callback = self._following  # type: ignore[method-assign]
            self.add_item(previous)
            self.add_item(following)

    async def _previous(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            view=EntrySelectView(self.context, self.entries, page=self.page - 1)
        )

    async def _following(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            view=EntrySelectView(self.context, self.entries, page=self.page + 1)
        )

    async def _selected(self, interaction: discord.Interaction) -> None:
        result = await module_api(self.context.api).farm_tickets_action(
            self.context.actor.guild_id,
            "edit_entry",
            resource_id=str(self.context.panel.get("resource_id") or ""),
            actor=self.context.actor.as_payload(),
            payload={
                "phase": "open_form",
                "target_entry_id": self.select.values[0],
                "idempotency_key": f"interaction:{interaction.id}:edit-form",
            },
        )
        await interaction.response.send_modal(
            _form_modal(
                panel={
                    **self.context.panel,
                    "selected_entry_id": self.select.values[0],
                },
                action_key="edit_entry",
                form=result["form"],
                ticket_revision=int(result["ticket"]["revision"]),
                title="Editar lançamento",
            )
        )


async def open_ticket(context: RoutedContext) -> InteractionResult:
    return await _runtime_action(context, "open_ticket")


async def open_for_member(context: RoutedContext) -> InteractionResult:
    return InteractionResult(
        content="Selecione o membro.",
        view=MemberTicketView(context, action_key="open_for_member"),
    )


async def delete_ticket_global(context: RoutedContext) -> InteractionResult:
    return InteractionResult(
        content="Selecione o membro do ticket.",
        view=MemberTicketView(context, action_key="delete_ticket_global"),
    )


async def create_entry(context: RoutedContext) -> InteractionResult:
    return await _items_action(context, "create_entry", "Lancar Farm")


async def edit_entry(context: RoutedContext) -> InteractionResult:
    if (context.interaction.data or {}).get("components"):
        return await _items_action(context, "edit_entry", "Editar lançamento")
    entries = await module_api(context.api).farm_tickets_entries(
        context.actor.guild_id,
        str(context.panel.get("resource_id") or ""),
        editable_only=True,
    )
    if not entries:
        return InteractionResult(content="Não existem lançamentos editáveis.")
    return InteractionResult(
        content="Selecione o lançamento.", view=EntrySelectView(context, entries)
    )


async def list_proofs(context: RoutedContext) -> InteractionResult:
    dispatcher = getattr(module_api(context.api), "farm_tickets_action", None)
    if dispatcher is None:
        return InteractionResult(
            content="A API de Tickets de Farm não está disponível."
        )
    result = await dispatcher(
        context.actor.guild_id,
        "list_proofs",
        resource_id=str(context.panel.get("resource_id") or ""),
        actor=context.actor.as_payload(),
        payload={},
    )
    key = (
        context.actor.guild_id,
        context.actor.user_id,
        str(context.panel.get("resource_id") or ""),
    )
    _PROOF_PAGES[key] = 0
    return InteractionResult(
        components_v2=proof_gallery_payload(result.get("proofs") or [], page=0)
    )


async def proofs_previous(context: RoutedContext) -> InteractionResult:
    return await _proof_page(context, -1)


async def proofs_next(context: RoutedContext) -> InteractionResult:
    return await _proof_page(context, 1)


async def _proof_page(context: RoutedContext, direction: int) -> InteractionResult:
    dispatcher = getattr(module_api(context.api), "farm_tickets_action", None)
    if dispatcher is None:
        return InteractionResult(
            content="A API de Tickets de Farm não está disponível."
        )
    result = await dispatcher(
        context.actor.guild_id,
        "list_proofs",
        resource_id=str(context.panel.get("resource_id") or ""),
        actor=context.actor.as_payload(),
        payload={},
    )
    proofs = result.get("proofs") or []
    key = (
        context.actor.guild_id,
        context.actor.user_id,
        str(context.panel.get("resource_id") or ""),
    )
    last_page = max(0, ceil(len(proofs) / 10) - 1)
    page = min(max(_PROOF_PAGES.get(key, 0) + direction, 0), last_page)
    _PROOF_PAGES[key] = page
    return InteractionResult(components_v2=proof_gallery_payload(proofs, page=page))


async def withdraw(context: RoutedContext) -> InteractionResult:
    return await _items_action(context, "withdraw", "Registrar recolhimento")


async def assign(context: RoutedContext) -> InteractionResult:
    return await _runtime_action(context, "assign")


async def approve(context: RoutedContext) -> InteractionResult:
    return await _runtime_action(context, "approve")


async def finalize(context: RoutedContext) -> InteractionResult:
    values = _modal_values((context.interaction.data or {}).get("components"))
    if values:
        return await _runtime_action(context, "finalize", values)
    return InteractionResult(
        modal=TicketReasonModal(
            panel=context.panel,
            action_key="finalize",
            title="Finalizar ticket",
        )
    )


async def ticket_owner(
    _interaction: discord.Interaction, panel: dict[str, Any], api: Any
) -> str | None:
    owner_id = panel.get("owner_id") or panel.get("member_id")
    if owner_id:
        return str(owner_id)
    reader = getattr(module_api(api), "farm_tickets_owner", None)
    if reader is None:
        return None
    return await reader(int(panel["guild_id"]), str(panel.get("resource_id") or ""))
