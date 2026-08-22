from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import logging
from typing import Any
from zoneinfo import ZoneInfo

import discord
import httpx

from yuno_bot import dashboard
from yuno_bot.platform.components_v2 import (
    action_row,
    button,
    channel_select,
    container,
    edit_interaction_message,
    edit_message,
    edit_webhook_message,
    meta_notice_payload,
    payload,
    role_select,
    send_meta_notice,
    separator,
    string_select,
    text_display,
)
from yuno_bot.platform.contracts import ActorContext, RetryableJobError


COLOR = 0xFFC72C
log = logging.getLogger("yuno.meta")
_goal_pages: dict[tuple[int, int], int] = {}
_selected_goals: dict[tuple[int, int], int] = {}
_product_pages: dict[tuple[int, int], int] = {}
_objective_pages: dict[tuple[int, int], int] = {}
_selected_objectives: dict[tuple[int, int], int] = {}


def actor_from(interaction: discord.Interaction) -> ActorContext:
    member = interaction.user if isinstance(interaction.user, discord.Member) else None
    permissions = tuple(
        name for name, enabled in (member.guild_permissions if member else []) if enabled
    )
    return ActorContext(
        guild_id=int(interaction.guild_id or 0),
        user_id=interaction.user.id,
        role_ids=tuple(role.id for role in member.roles) if member else (),
        discord_permissions=permissions,
        channel_id=interaction.channel_id,
        category_id=getattr(getattr(interaction.channel, "category", None), "id", None),
        actor_type="user",
        is_guild_owner=bool(interaction.guild and interaction.guild.owner_id == interaction.user.id),
        correlation_id=str(interaction.id),
    )


def _error_text(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            detail = exc.response.json().get("detail")
            if isinstance(detail, dict):
                return str(detail.get("detail") or detail)
            if detail:
                return str(detail)
        except Exception:
            pass
    return "Nao foi possivel concluir a acao de Metas. Tente novamente."


async def _reply(interaction: discord.Interaction, message: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


async def _replace_public(interaction: discord.Interaction, data: dict[str, Any]) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer()
    if interaction.channel_id is None or interaction.message is None:
        raise RuntimeError("Referencia da Central indisponivel.")
    await edit_message(interaction.client, interaction.channel_id, interaction.message.id, data)


def _public_status(goal: dict[str, Any]) -> str:
    if goal["state"] == "active":
        return "Ativa"
    return "Agendada"


def _main_payload(goals: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    page = int(goals["page"])
    total = int(goals["total"])
    page_size = int(goals["page_size"])
    options = [
        {
            "label": str(item["name"])[:100],
            "value": f"goal:{item['id']}",
            "description": f"{_public_status(item)} · {item['recurrence']}",
            "emoji": {"name": "🎯"},
        }
        for item in goals["items"]
    ]
    if page > 0:
        options.insert(0, {"label": "Pagina anterior", "value": "page:prev", "emoji": {"name": "⬅️"}})
    if (page + 1) * page_size < total:
        options.append({"label": "Proxima pagina", "value": "page:next", "emoji": {"name": "➡️"}})
    if not options:
        options.append({"label": "Nenhuma Meta ativa ou agendada", "value": "none"})
    return payload(
        container(
            dashboard.module_navigation("meta"),
            separator(),
            text_display("# 🎯 Sistema de Metas"),
            action_row(
                button(
                    custom_id=dashboard.central_custom_id("meta", "create_goal"),
                    label="Criar Meta",
                    emoji="➕",
                    style=1,
                ),
                button(
                    custom_id=dashboard.central_custom_id("meta", "settings"),
                    label="Configuracoes",
                    emoji="⚙️",
                    style=2,
                ),
            ),
            action_row(
                string_select(
                    custom_id=dashboard.central_custom_id("meta", "select_goal"),
                    options=options,
                    placeholder=f"Metas ativas e agendadas · pagina {page + 1}",
                )
            ),
            accent_color=COLOR,
        )
    )


async def render_admin(interaction: discord.Interaction, api: Any) -> None:
    key = (int(interaction.guild_id or 0), interaction.user.id)
    page = max(0, _goal_pages.get(key, 0))
    try:
        goals = await api.meta_goals(interaction.guild_id, page=page)
        settings_data = await api.meta_settings(interaction.guild_id)
        if page and not goals["items"]:
            page = 0
            _goal_pages[key] = 0
            goals = await api.meta_goals(interaction.guild_id, page=0)
        await _replace_public(interaction, _main_payload(goals, settings_data))
    except Exception as exc:
        await _reply(interaction, _error_text(exc))


def _schedule_summary(data: dict[str, Any]) -> str:
    recurrence = data.get("recurrence")
    if recurrence == "daily":
        return f"Diaria as {data.get('daily_time') or '—'}"
    if recurrence == "weekly":
        return f"Semanal no dia {data.get('weekday', '—')} as 00:00"
    if recurrence == "monthly":
        return f"Mensal no dia {data.get('month_day', '—')} as 00:00"
    if recurrence == "custom":
        return f"Personalizada: {data.get('scheduled_start_at', '—')} ate {data.get('scheduled_end_at', '—')}"
    return "Nao definida"


def _format_decimal_br(value: Any, *, places: int, fixed: bool = False) -> str:
    amount = Decimal(str(value))
    rendered = f"{amount:.{places}f}"
    integer, _, fraction = rendered.partition(".")
    grouped = f"{int(integer):,}".replace(",", ".")
    if not fixed:
        fraction = fraction.rstrip("0")
    return f"{grouped},{fraction}" if fraction else grouped


def _decimal_input(value: Any, *, places: int) -> str:
    if value in (None, ""):
        return ""
    amount = Decimal(str(value))
    rendered = f"{amount:.{places}f}"
    integer, _, fraction = rendered.partition(".")
    fraction = fraction.rstrip("0")
    return f"{integer},{fraction}" if fraction else integer


def _parse_decimal_br(value: str, *, places: int, allow_currency: bool = False) -> str:
    raw = value.strip().replace("\u00a0", " ")
    if allow_currency:
        raw = raw.replace("R$", "").replace("r$", "")
    raw = raw.replace(" ", "")
    if not raw or raw.startswith(("+", "-")):
        raise ValueError("Informe um valor positivo.")

    if "," in raw:
        if raw.count(",") != 1:
            raise ValueError("Use apenas uma virgula decimal.")
        integer, fraction = raw.split(",", 1)
        groups = integer.split(".")
        if len(groups) > 1 and not (
            1 <= len(groups[0]) <= 3
            and all(len(group) == 3 and group.isdigit() for group in groups[1:])
        ):
            raise ValueError("Separadores de milhar invalidos.")
        if not groups[0].isdigit() or not fraction.isdigit() or len(fraction) > places:
            raise ValueError(f"Use no maximo {places} casas decimais.")
        normalized = "".join(groups) + "." + fraction
    elif "." in raw:
        groups = raw.split(".")
        thousands = (
            len(groups) > 1
            and 1 <= len(groups[0]) <= 3
            and groups[0].isdigit()
            and all(len(group) == 3 and group.isdigit() for group in groups[1:])
        )
        if thousands:
            normalized = "".join(groups)
        elif (
            len(groups) == 2
            and groups[0].isdigit()
            and groups[1].isdigit()
            and 1 <= len(groups[1]) <= places
        ):
            normalized = raw
        else:
            raise ValueError("Valor numerico invalido.")
    elif raw.isdigit():
        normalized = raw
    else:
        raise ValueError("Valor numerico invalido.")

    amount = Decimal(normalized)
    if (
        not amount.is_finite()
        or amount <= 0
        or amount.as_tuple().exponent < -places
        or len(amount.as_tuple().digits) > 20
    ):
        raise ValueError("Valor fora do limite permitido.")
    return format(amount, "f")


def _display_unit(unit: Any, quantity: Any) -> str:
    value = str(unit or "unidade").strip()
    if Decimal(str(quantity)) == 1 or value.casefold().endswith("s"):
        return value
    plurals = {
        "unidade": "unidades",
        "caixa": "caixas",
        "pacote": "pacotes",
        "kit": "kits",
        "item": "itens",
    }
    return plurals.get(value.casefold(), value)


def _objective_line(item: dict[str, Any]) -> str:
    if item.get("kind") == "money":
        return (
            f"💰 {item.get('name') or 'Dinheiro'} — "
            f"R$ {_format_decimal_br(item.get('money_amount'), places=2, fixed=True)}"
        )
    quantity = item.get("item_quantity")
    return (
        f"📦 {item.get('name')} — {_format_decimal_br(quantity, places=3)} "
        f"{_display_unit(item.get('unit'), quantity)}"
    )


def _objective_lines(data: dict[str, Any]) -> str:
    lines = [f"• {_objective_line(item)}" for item in data.get("objectives") or []]
    return "\n".join(lines) or "_Nenhum objetivo definido._"


def _objectives_match_mode(data: dict[str, Any]) -> bool:
    objectives = list(data.get("objectives") or [])
    kinds = {str(item.get("kind")) for item in objectives}
    mode = str(data.get("objective_mode") or "mixed")
    if not objectives:
        return False
    if mode == "items":
        return kinds == {"item"}
    if mode == "money":
        return kinds == {"money"}
    return kinds.issubset({"item", "money"})


def _editor_payload(
    draft: dict[str, Any],
    *,
    banner: str = "",
    products: dict[str, Any] | None = None,
    objective_page: int = 0,
) -> dict[str, Any]:
    step = draft["step"]
    data = draft["data"]
    title = "Editar Meta" if draft.get("goal_id") else "Criar Meta"
    content = [
        text_display(
            f"# 🎯 {title}\n\nUma unica mensagem acompanha todo o fluxo. "
            f"Rascunho salvo · revisao **{draft['revision']}**."
            + (f"\n\n⚠️ {banner}" if banner else "")
        ),
        separator(),
    ]
    if step == "name":
        content.extend(
            [
                text_display(f"### 1. Nome\n**{data.get('name') or 'Ainda nao informado'}**"),
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id("meta", "edit_name"),
                        label="Informar nome",
                        style=1,
                    )
                ),
            ]
        )
    elif step == "periodicity":
        content.extend(
            [
                text_display("### 2. Periodicidade\nEscolha como os ciclos serao renovados."),
                action_row(
                    string_select(
                        custom_id=dashboard.central_custom_id("meta", "set_recurrence"),
                        placeholder="Escolha a periodicidade",
                        options=[
                            {"label": "Diaria", "value": "daily", "emoji": {"name": "☀️"}},
                            {"label": "Semanal", "value": "weekly", "emoji": {"name": "📅"}},
                            {"label": "Mensal", "value": "monthly", "emoji": {"name": "🗓️"}},
                            {"label": "Personalizada", "value": "custom", "emoji": {"name": "⏱️"}},
                        ],
                    )
                ),
            ]
        )
    elif step == "schedule":
        content.extend(
            [
                text_display(f"### 2. Periodicidade\n**{_schedule_summary(data)}**"),
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id("meta", "edit_schedule"),
                        label="Definir agenda",
                        style=1,
                    )
                ),
            ]
        )
    elif step == "participants":
        content.extend(
            [
                text_display("### 3. Participantes\nO snapshot sera congelado quando o ciclo iniciar."),
                action_row(
                    string_select(
                        custom_id=dashboard.central_custom_id("meta", "set_participation"),
                        placeholder="Todos os membros ou cargos",
                        options=[
                            {"label": "Todos os membros", "value": "all_members", "emoji": {"name": "👥"}},
                            {"label": "Cargos selecionados", "value": "roles", "emoji": {"name": "🎭"}},
                        ],
                    )
                ),
            ]
        )
    elif step == "participant_roles":
        roles = data.get("role_ids") or []
        content.extend(
            [
                text_display(
                    f"### 3. Participantes por cargo\n**{len(roles)} cargo(s)** selecionado(s). "
                    "Adicione em lotes se precisar de mais de 25."
                ),
                action_row(
                    role_select(
                        custom_id=dashboard.central_custom_id("meta", "add_roles"),
                        placeholder="Adicionar cargos participantes",
                        min_values=1,
                        max_values=25,
                    )
                ),
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id("meta", "confirm_roles"),
                        label="Continuar",
                        style=3,
                        disabled=not bool(roles),
                    )
                ),
            ]
        )
    elif step == "type":
        content.extend(
            [
                text_display("### 4. Tipo\nEscolha itens, dinheiro ou uma Meta mista."),
                action_row(
                    string_select(
                        custom_id=dashboard.central_custom_id("meta", "set_type"),
                        placeholder="Escolha o tipo de Meta",
                        options=[
                            {"label": "Itens", "value": "items", "emoji": {"name": "📦"}},
                            {"label": "Dinheiro", "value": "money", "emoji": {"name": "💵"}},
                            {"label": "Mista", "value": "mixed", "emoji": {"name": "🎯"}},
                        ],
                    )
                ),
            ]
        )
    elif step == "objectives":
        mode = str(data.get("objective_mode") or "mixed")
        objectives = list(data.get("objectives") or [])
        content.append(
            text_display(
                "### 5. Objetivos\nAdicione cada objetivo em campos separados. "
                "Os valores abaixo ja estao no formato que sera publicado.\n\n"
                + _objective_lines(data)
            )
        )
        catalog = products or {"items": [], "page": 0, "page_size": 23, "total": 0}
        catalog_options = [
            {
                "label": str(item["name"])[:100],
                "value": f"product:{item['id']}",
                "description": (
                    f"Sugestao: {_format_decimal_br(item['last_suggested_quantity'], places=3)} "
                    f"{item['unit']}"
                    if item.get("last_suggested_quantity")
                    else f"Unidade: {item['unit']}"
                )[:100],
                "emoji": {"name": "📦"},
            }
            for item in catalog.get("items") or []
        ]
        product_page = int(catalog.get("page") or 0)
        if product_page > 0:
            catalog_options.insert(0, {"label": "Pagina anterior", "value": "page:prev", "emoji": {"name": "⬅️"}})
        if (product_page + 1) * int(catalog.get("page_size") or 23) < int(catalog.get("total") or 0):
            catalog_options.append({"label": "Proxima pagina", "value": "page:next", "emoji": {"name": "➡️"}})
        if mode in {"items", "mixed"} and catalog_options:
            content.append(
                action_row(
                    string_select(
                        custom_id=dashboard.central_custom_id("meta", "select_product"),
                        options=catalog_options,
                        placeholder=f"Usar item cadastrado · pagina {product_page + 1}",
                    )
                )
            )

        start = max(0, objective_page) * 23
        visible = objectives[start : start + 23]
        objective_options = [
            {
                "label": str(item.get("name") or "Objetivo")[:100],
                "value": f"objective:{start + index}",
                "description": _objective_line(item)[:100],
                "emoji": {"name": "💰" if item.get("kind") == "money" else "📦"},
            }
            for index, item in enumerate(visible)
        ]
        if objective_page > 0:
            objective_options.insert(0, {"label": "Pagina anterior", "value": "page:prev", "emoji": {"name": "⬅️"}})
        if start + 23 < len(objectives):
            objective_options.append({"label": "Proxima pagina", "value": "page:next", "emoji": {"name": "➡️"}})
        if objective_options:
            content.append(
                action_row(
                    string_select(
                        custom_id=dashboard.central_custom_id("meta", "select_objective"),
                        options=objective_options,
                        placeholder=f"Editar ou remover objetivo · pagina {objective_page + 1}",
                    )
                )
            )

        add_buttons = []
        if mode in {"items", "mixed"}:
            add_buttons.append(
                button(
                    custom_id=dashboard.central_custom_id("meta", "add_item_objective"),
                    label="Novo item",
                    emoji="📦",
                    style=1,
                )
            )
        if mode in {"money", "mixed"}:
            add_buttons.append(
                button(
                    custom_id=dashboard.central_custom_id("meta", "add_money_objective"),
                    label="Dinheiro",
                    emoji="💰",
                    style=1,
                )
            )
        content.append(action_row(*add_buttons))
        content.append(
            action_row(
                button(
                    custom_id=dashboard.central_custom_id("meta", "objectives_continue"),
                    label="Continuar",
                    emoji="✅",
                    style=3,
                    disabled=not _objectives_match_mode(data),
                )
            )
        )
    elif step == "notice":
        content.extend(
            [
                text_display(
                    f"### 6. Texto do aviso\n{data.get('notice_text') or '_Ainda nao informado._'}"
                ),
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id("meta", "edit_notice"),
                        label="Informar aviso",
                        style=1,
                    )
                ),
            ]
        )
    elif step == "review":
        participant_text = (
            "Todos os membros"
            if data.get("participation") == "all_members"
            else f"{len(data.get('role_ids') or [])} cargo(s)"
        )
        content.extend(
            [
                text_display(
                    "### 7. Revisao\n"
                    f"**Nome:** {data.get('name')}\n"
                    f"**Periodicidade:** {_schedule_summary(data)}\n"
                    f"**Participantes:** {participant_text}\n"
                    f"**Objetivos:**\n{_objective_lines(data)}\n"
                    f"**Aviso:** {data.get('notice_text')}"
                ),
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id("meta", "submit_goal"),
                        label="Criar Meta" if not draft.get("goal_id") else "Salvar proxima Meta",
                        emoji="✅",
                        style=3,
                    )
                ),
            ]
        )
    else:
        content.append(
            text_display(
                "### Meta salva\nO lancamento foi agendado. O ciclo so ficara ativo depois que o aviso publico for confirmado."
            )
        )
    return payload(container(*content, accent_color=COLOR))


async def _editor_products(
    api: Any, interaction: discord.Interaction, draft: dict[str, Any]
) -> dict[str, Any] | None:
    if draft.get("step") != "objectives" or not hasattr(api, "meta_products"):
        return None
    key = (int(interaction.guild_id or 0), interaction.user.id)
    page = max(0, _product_pages.get(key, 0))
    try:
        result = await api.meta_products(interaction.guild_id, page=page)
        if page and not result.get("items"):
            page = 0
            _product_pages[key] = 0
            result = await api.meta_products(interaction.guild_id, page=0)
        return result
    except Exception:
        log.exception(
            "Falha ao carregar catalogo da Meta guild=%s admin=%s",
            interaction.guild_id,
            interaction.user.id,
        )
        return None


async def _show_editor(
    interaction: discord.Interaction, draft: dict[str, Any], *, banner: str = ""
) -> None:
    key = (int(interaction.guild_id or 0), interaction.user.id)
    products = await _editor_products(
        getattr(interaction.client, "platform_api", None), interaction, draft
    )
    await edit_interaction_message(
        interaction,
        _editor_payload(
            draft,
            banner=banner,
            products=products,
            objective_page=max(0, _objective_pages.get(key, 0)),
        ),
        ephemeral=True,
    )


class EditorModal(discord.ui.Modal):
    def __init__(self, title: str, api: Any, editor_interaction: discord.Interaction) -> None:
        super().__init__(title=title, timeout=600)
        self.api = api
        self.editor_application_id = int(editor_interaction.application_id)
        self.editor_token = editor_interaction.token

    async def _refresh_after_submit(
        self,
        interaction: discord.Interaction,
        saved: dict[str, Any],
        *,
        banner: str = "",
    ) -> None:
        key = (int(interaction.guild_id or 0), interaction.user.id)
        products = await _editor_products(self.api, interaction, saved)
        data = _editor_payload(
            saved,
            banner=banner,
            products=products,
            objective_page=max(0, _objective_pages.get(key, 0)),
        )
        try:
            await edit_webhook_message(
                interaction.client,
                application_id=self.editor_application_id,
                interaction_token=self.editor_token,
                data=data,
            )
        except Exception:
            log.warning(
                "Editor efemero anterior expirou; rotacionando token guild=%s admin=%s",
                interaction.guild_id,
                interaction.user.id,
                exc_info=True,
            )
            await edit_webhook_message(
                interaction.client,
                application_id=int(interaction.application_id),
                interaction_token=interaction.token,
                data=data,
            )
            return
        try:
            await interaction.delete_original_response()
        except discord.HTTPException:
            pass

    async def save_patch(
        self, interaction: discord.Interaction, *, patch: dict[str, Any], step: str
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            actor = actor_from(interaction)
            current = await self.api.meta_draft(interaction.guild_id, actor=actor)
            saved = await self.api.meta_patch_draft(
                interaction.guild_id,
                {"expected_revision": current["revision"], "step": step, "patch": patch},
                actor=actor,
            )
            await self._refresh_after_submit(interaction, saved)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                current = await self.api.meta_draft(
                    interaction.guild_id, actor=actor_from(interaction)
                )
                await self._refresh_after_submit(
                    interaction,
                    current,
                    banner="O rascunho mudou durante a edicao. A versao atual foi recarregada.",
                )
                return
            await interaction.followup.send(_error_text(exc), ephemeral=True)
        except Exception as exc:
            log.exception(
                "Falha ao salvar rascunho da Meta guild=%s admin=%s interaction=%s",
                interaction.guild_id,
                interaction.user.id,
                interaction.id,
            )
            await interaction.followup.send(_error_text(exc), ephemeral=True)

    async def save_objective(
        self,
        interaction: discord.Interaction,
        *,
        objective: dict[str, Any],
        index: int | None,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            actor = actor_from(interaction)
            current = await self.api.meta_draft(interaction.guild_id, actor=actor)
            objectives = list(current["data"].get("objectives") or [])
            if index is None:
                objectives.append(objective)
            elif 0 <= index < len(objectives):
                objectives[index] = objective
            else:
                raise ValueError("O objetivo selecionado nao existe mais.")
            saved = await self.api.meta_patch_draft(
                interaction.guild_id,
                {
                    "expected_revision": current["revision"],
                    "step": "objectives",
                    "patch": {"objectives": objectives},
                },
                actor=actor,
            )
            await self._refresh_after_submit(interaction, saved)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                current = await self.api.meta_draft(
                    interaction.guild_id, actor=actor_from(interaction)
                )
                await self._refresh_after_submit(
                    interaction,
                    current,
                    banner="O rascunho mudou durante a edicao. Selecione o objetivo novamente.",
                )
                return
            await interaction.followup.send(_error_text(exc), ephemeral=True)
        except Exception as exc:
            log.exception(
                "Falha ao salvar objetivo da Meta guild=%s admin=%s interaction=%s",
                interaction.guild_id,
                interaction.user.id,
                interaction.id,
            )
            await interaction.followup.send(_error_text(exc), ephemeral=True)


class NameModal(EditorModal):
    def __init__(self, api: Any, interaction: discord.Interaction, current: str = "") -> None:
        super().__init__("Nome da Meta", api, interaction)
        self.name_input = discord.ui.TextInput(
            label="Nome", default=current or None, min_length=1, max_length=120
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.save_patch(
            interaction, patch={"name": str(self.name_input.value)}, step="periodicity"
        )


class ScheduleModal(EditorModal):
    def __init__(self, api: Any, interaction: discord.Interaction, draft: dict[str, Any]) -> None:
        recurrence = str(draft["data"].get("recurrence") or "")
        super().__init__("Agenda da Meta", api, interaction)
        self.recurrence = recurrence
        if recurrence == "daily":
            self.primary = discord.ui.TextInput(
                label="Horario diario (HH:MM)", placeholder="23:55", max_length=5
            )
            self.add_item(self.primary)
            self.secondary = None
        elif recurrence == "weekly":
            self.primary = discord.ui.TextInput(
                label="Dia da semana (0=segunda, 6=domingo)", placeholder="0", max_length=1
            )
            self.add_item(self.primary)
            self.secondary = None
        elif recurrence == "monthly":
            self.primary = discord.ui.TextInput(
                label="Dia do mes (1 a 31)", placeholder="31", max_length=2
            )
            self.add_item(self.primary)
            self.secondary = None
        else:
            self.primary = discord.ui.TextInput(
                label="Inicio local (DD/MM/AAAA HH:MM)", placeholder="23/08/2026 20:00", max_length=16
            )
            self.secondary = discord.ui.TextInput(
                label="Fim local (DD/MM/AAAA HH:MM)", placeholder="24/08/2026 20:00", max_length=16
            )
            self.add_item(self.primary)
            self.add_item(self.secondary)
        self.timezone_name = str(draft["data"].get("timezone") or "America/Sao_Paulo")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            value = str(self.primary.value).strip()
            if self.recurrence == "daily":
                datetime.strptime(value, "%H:%M")
                patch = {"daily_time": value, "weekday": None, "month_day": None}
            elif self.recurrence == "weekly":
                weekday = int(value)
                if weekday < 0 or weekday > 6:
                    raise ValueError
                patch = {"weekday": weekday, "daily_time": None, "month_day": None}
            elif self.recurrence == "monthly":
                month_day = int(value)
                if month_day < 1 or month_day > 31:
                    raise ValueError
                patch = {"month_day": month_day, "daily_time": None, "weekday": None}
            else:
                zone = ZoneInfo(self.timezone_name)
                start = datetime.strptime(value, "%d/%m/%Y %H:%M").replace(tzinfo=zone)
                end = datetime.strptime(str(self.secondary.value).strip(), "%d/%m/%Y %H:%M").replace(tzinfo=zone)
                if end <= start:
                    raise ValueError
                patch = {
                    "scheduled_start_at": start.isoformat(),
                    "scheduled_end_at": end.isoformat(),
                    "daily_time": None,
                    "weekday": None,
                    "month_day": None,
                }
        except (ValueError, TypeError):
            await interaction.response.send_message("Agenda invalida. Revise o formato e o intervalo.", ephemeral=True)
            return
        await self.save_patch(interaction, patch=patch, step="participants")


class ItemObjectiveModal(EditorModal):
    def __init__(
        self,
        api: Any,
        interaction: discord.Interaction,
        *,
        objective: dict[str, Any] | None = None,
        index: int | None = None,
    ) -> None:
        super().__init__("Editar item" if objective else "Novo item", api, interaction)
        self.index = index
        current = objective or {}
        self.name_input = discord.ui.TextInput(
            label="Item",
            placeholder="Ex.: Arma",
            default=str(current.get("name") or "") or None,
            min_length=1,
            max_length=100,
        )
        self.quantity_input = discord.ui.TextInput(
            label="Quantidade",
            placeholder="Ex.: 10.500 ou 10.500,250",
            default=(
                _decimal_input(current.get("item_quantity"), places=3)
                if current.get("item_quantity") is not None
                else None
            ),
            min_length=1,
            max_length=30,
        )
        self.unit_input = discord.ui.TextInput(
            label="Unidade",
            placeholder="Ex.: unidade, caixa, pacote",
            default=str(current.get("unit") or "") or None,
            min_length=1,
            max_length=30,
        )
        self.add_item(self.name_input)
        self.add_item(self.quantity_input)
        self.add_item(self.unit_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            quantity = _parse_decimal_br(
                str(self.quantity_input.value), places=3
            )
        except (ValueError, InvalidOperation) as exc:
            await interaction.response.send_message(
                f"Quantidade invalida: {exc} Use virgula para decimais, por exemplo `10.500,250`.",
                ephemeral=True,
            )
            return
        await self.save_objective(
            interaction,
            index=self.index,
            objective={
                "kind": "item",
                "name": str(self.name_input.value).strip(),
                "unit": str(self.unit_input.value).strip(),
                "item_quantity": quantity,
                "money_amount": None,
            },
        )


class MoneyObjectiveModal(EditorModal):
    def __init__(
        self,
        api: Any,
        interaction: discord.Interaction,
        *,
        objective: dict[str, Any] | None = None,
        index: int | None = None,
    ) -> None:
        super().__init__("Editar dinheiro" if objective else "Objetivo em dinheiro", api, interaction)
        self.index = index
        current = objective or {}
        self.name_input = discord.ui.TextInput(
            label="Descricao",
            placeholder="Ex.: Dinheiro",
            default=str(current.get("name") or "Dinheiro"),
            min_length=1,
            max_length=100,
        )
        self.amount_input = discord.ui.TextInput(
            label="Valor",
            placeholder="Ex.: R$ 1.500,00",
            default=(
                _decimal_input(current.get("money_amount"), places=2)
                if current.get("money_amount") is not None
                else None
            ),
            min_length=1,
            max_length=30,
        )
        self.add_item(self.name_input)
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            amount = _parse_decimal_br(
                str(self.amount_input.value), places=2, allow_currency=True
            )
        except (ValueError, InvalidOperation) as exc:
            await interaction.response.send_message(
                f"Valor invalido: {exc} Exemplo aceito: `R$ 1.500,00`.",
                ephemeral=True,
            )
            return
        await self.save_objective(
            interaction,
            index=self.index,
            objective={
                "kind": "money",
                "name": str(self.name_input.value).strip(),
                "unit": None,
                "item_quantity": None,
                "money_amount": amount,
            },
        )


class NoticeModal(EditorModal):
    def __init__(self, api: Any, interaction: discord.Interaction, current: str = "") -> None:
        super().__init__("Aviso da Meta", api, interaction)
        self.notice = discord.ui.TextInput(
            label="Texto do aviso",
            default=current or None,
            style=discord.TextStyle.paragraph,
            min_length=1,
            max_length=2000,
        )
        self.add_item(self.notice)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.save_patch(
            interaction, patch={"notice_text": str(self.notice.value)}, step="review"
        )


async def create_goal(interaction: discord.Interaction, api: Any) -> None:
    try:
        draft = await api.meta_open_draft(interaction.guild_id, None, actor=actor_from(interaction))
        await _show_editor(interaction, draft)
    except Exception as exc:
        await _reply(interaction, _error_text(exc))


async def settings(interaction: discord.Interaction, api: Any) -> None:
    try:
        current = await api.meta_settings(interaction.guild_id)
        await edit_interaction_message(
            interaction,
            payload(
                container(
                    text_display(
                        "# ⚙️ Configuracoes de Metas\n\nSelecione o canal usado para o aviso de cada novo ciclo."
                        f"\nCanal atual: <#{current['notice_channel_id']}>" if current.get("notice_channel_id") else
                        "# ⚙️ Configuracoes de Metas\n\nSelecione o canal usado para o aviso de cada novo ciclo."
                    ),
                    action_row(
                        channel_select(
                            custom_id=dashboard.central_custom_id("meta", "save_settings"),
                            placeholder="Canal dos avisos de Meta",
                            channel_types=[0, 5],
                        )
                    ),
                    accent_color=COLOR,
                )
            ),
            ephemeral=True,
        )
    except Exception as exc:
        await _reply(interaction, _error_text(exc))


async def save_settings(interaction: discord.Interaction, api: Any) -> None:
    values = list((interaction.data or {}).get("values") or [])
    channel = interaction.guild.get_channel(int(values[0])) if values and interaction.guild else None
    if not isinstance(channel, discord.TextChannel):
        await _reply(interaction, "Selecione um canal de texto valido.")
        return
    bot_member = interaction.guild.me
    permissions = channel.permissions_for(bot_member) if bot_member else None
    required = ("view_channel", "send_messages", "read_message_history", "mention_everyone")
    missing = [name for name in required if not permissions or not getattr(permissions, name, False)]
    if missing:
        await _reply(interaction, "Permissoes ausentes no canal: " + ", ".join(missing))
        return
    try:
        current = await api.meta_settings(interaction.guild_id)
        saved = await api.meta_save_settings(
            interaction.guild_id,
            {"notice_channel_id": str(channel.id), "expected_revision": current["revision"] or None},
            actor=actor_from(interaction),
        )
        await edit_interaction_message(
            interaction,
            payload(container(text_display(f"# ✅ Configuracoes salvas\n\nAvisos serao publicados em {channel.mention}."), accent_color=COLOR)),
        )
    except Exception as exc:
        await _reply(interaction, _error_text(exc))


async def select_goal(interaction: discord.Interaction, api: Any) -> None:
    values = list((interaction.data or {}).get("values") or [])
    if not values or values[0] == "none":
        await _reply(interaction, "Nenhuma Meta ativa ou agendada.")
        return
    key = (interaction.guild_id, interaction.user.id)
    if values[0].startswith("page:"):
        delta = -1 if values[0] == "page:prev" else 1
        _goal_pages[key] = max(0, _goal_pages.get(key, 0) + delta)
        await render_admin(interaction, api)
        return
    goal_id = int(values[0].split(":", 1)[1])
    _selected_goals[key] = goal_id
    try:
        goal = await api.meta_goal(interaction.guild_id, goal_id)
        config = goal.get("future_configuration") or goal.get("current_configuration") or {}
        components = [
            text_display(
                f"# 🎯 {goal['name']}\n\n**Status:** {_public_status(goal)}\n"
                f"**Periodicidade:** {_schedule_summary(config)}\n"
                f"**Objetivos:**\n{_objective_lines(config)}"
            )
        ]
        if goal["state"] == "active" and goal["recurrence"] != "custom":
            components.append(
                action_row(button(custom_id=dashboard.central_custom_id("meta", "edit_goal"), label="Editar proxima Meta", style=2))
            )
        elif goal["state"] == "scheduled" and goal["recurrence"] == "custom":
            components.append(
                action_row(button(custom_id=dashboard.central_custom_id("meta", "edit_goal"), label="Editar Meta agendada", style=2))
            )
        await edit_interaction_message(
            interaction, payload(container(*components, accent_color=COLOR)), ephemeral=True
        )
    except Exception as exc:
        await _reply(interaction, _error_text(exc))


async def edit_goal(interaction: discord.Interaction, api: Any) -> None:
    goal_id = _selected_goals.get((interaction.guild_id, interaction.user.id))
    if goal_id is None:
        await _reply(interaction, "Selecione a Meta novamente.")
        return
    try:
        draft = await api.meta_open_draft(interaction.guild_id, goal_id, actor=actor_from(interaction))
        await _show_editor(interaction, draft)
    except Exception as exc:
        await _reply(interaction, _error_text(exc))


async def edit_name(interaction: discord.Interaction, api: Any) -> None:
    draft = await api.meta_draft(interaction.guild_id, actor=actor_from(interaction))
    await interaction.response.send_modal(NameModal(api, interaction, str(draft["data"].get("name") or "")))


async def set_recurrence(interaction: discord.Interaction, api: Any) -> None:
    values = list((interaction.data or {}).get("values") or [])
    if not values:
        return
    actor = actor_from(interaction)
    current = await api.meta_draft(interaction.guild_id, actor=actor)
    saved = await api.meta_patch_draft(
        interaction.guild_id,
        {
            "expected_revision": current["revision"],
            "step": "schedule",
            "patch": {"recurrence": values[0]},
        },
        actor=actor,
    )
    await _show_editor(interaction, saved)


async def edit_schedule(interaction: discord.Interaction, api: Any) -> None:
    draft = await api.meta_draft(interaction.guild_id, actor=actor_from(interaction))
    await interaction.response.send_modal(ScheduleModal(api, interaction, draft))


async def set_participation(interaction: discord.Interaction, api: Any) -> None:
    values = list((interaction.data or {}).get("values") or [])
    if not values:
        return
    actor = actor_from(interaction)
    current = await api.meta_draft(interaction.guild_id, actor=actor)
    selected = values[0]
    saved = await api.meta_patch_draft(
        interaction.guild_id,
        {
            "expected_revision": current["revision"],
            "step": "type" if selected == "all_members" else "participant_roles",
            "patch": {"participation": selected, "role_ids": []},
        },
        actor=actor,
    )
    await _show_editor(interaction, saved)


async def add_roles(interaction: discord.Interaction, api: Any) -> None:
    values = [str(item) for item in ((interaction.data or {}).get("values") or [])]
    actor = actor_from(interaction)
    current = await api.meta_draft(interaction.guild_id, actor=actor)
    merged = list(dict.fromkeys([*(current["data"].get("role_ids") or []), *values]))
    saved = await api.meta_patch_draft(
        interaction.guild_id,
        {"expected_revision": current["revision"], "step": "participant_roles", "patch": {"role_ids": merged}},
        actor=actor,
    )
    await _show_editor(interaction, saved)


async def confirm_roles(interaction: discord.Interaction, api: Any) -> None:
    actor = actor_from(interaction)
    current = await api.meta_draft(interaction.guild_id, actor=actor)
    saved = await api.meta_patch_draft(
        interaction.guild_id,
        {"expected_revision": current["revision"], "step": "type", "patch": {}},
        actor=actor,
    )
    await _show_editor(interaction, saved)


async def set_type(interaction: discord.Interaction, api: Any) -> None:
    values = list((interaction.data or {}).get("values") or [])
    if not values:
        return
    actor = actor_from(interaction)
    current = await api.meta_draft(interaction.guild_id, actor=actor)
    selected = str(values[0])
    objectives = list(current["data"].get("objectives") or [])
    if selected == "items":
        compatible = [item for item in objectives if item.get("kind") == "item"]
    elif selected == "money":
        compatible = [item for item in objectives if item.get("kind") == "money"]
    else:
        compatible = objectives
    saved = await api.meta_patch_draft(
        interaction.guild_id,
        {
            "expected_revision": current["revision"],
            "step": "objectives",
            "patch": {"objective_mode": selected, "objectives": compatible},
        },
        actor=actor,
    )
    removed = len(objectives) - len(compatible)
    await _show_editor(
        interaction,
        saved,
        banner=(
            f"{removed} objetivo(s) de outro tipo foram removidos desta configuracao."
            if removed
            else ""
        ),
    )


async def edit_objectives(interaction: discord.Interaction, api: Any) -> None:
    """Compatibilidade com mensagens efemeras abertas antes do editor guiado."""

    draft = await api.meta_draft(interaction.guild_id, actor=actor_from(interaction))
    await _show_editor(interaction, draft)


async def add_item_objective(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.send_modal(ItemObjectiveModal(api, interaction))


async def add_money_objective(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.send_modal(MoneyObjectiveModal(api, interaction))


async def select_product(interaction: discord.Interaction, api: Any) -> None:
    values = list((interaction.data or {}).get("values") or [])
    if not values:
        return
    key = (int(interaction.guild_id or 0), interaction.user.id)
    selected = str(values[0])
    if selected.startswith("page:"):
        delta = -1 if selected == "page:prev" else 1
        _product_pages[key] = max(0, _product_pages.get(key, 0) + delta)
        draft = await api.meta_draft(interaction.guild_id, actor=actor_from(interaction))
        await _show_editor(interaction, draft)
        return
    product_id = int(selected.split(":", 1)[1])
    catalog = await api.meta_products(
        interaction.guild_id, page=max(0, _product_pages.get(key, 0))
    )
    product = next(
        (item for item in catalog.get("items") or [] if int(item["id"]) == product_id),
        None,
    )
    if product is None:
        await _reply(interaction, "O item cadastrado nao esta mais disponivel. Atualize a lista.")
        return
    await interaction.response.send_modal(
        ItemObjectiveModal(
            api,
            interaction,
            objective={
                "kind": "item",
                "name": product["name"],
                "unit": product["unit"],
                "item_quantity": product.get("last_suggested_quantity"),
                "money_amount": None,
            },
        )
    )


def _objective_action_payload(draft: dict[str, Any], index: int) -> dict[str, Any]:
    objectives = list(draft["data"].get("objectives") or [])
    if index < 0 or index >= len(objectives):
        raise ValueError("O objetivo selecionado nao existe mais.")
    item = objectives[index]
    return payload(
        container(
            text_display(
                f"# 🎯 Objetivo selecionado\n\n{_objective_line(item)}\n\n"
                "Escolha o que deseja fazer."
            ),
            action_row(
                button(
                    custom_id=dashboard.central_custom_id("meta", "edit_selected_objective"),
                    label="Editar",
                    emoji="✏️",
                    style=1,
                ),
                button(
                    custom_id=dashboard.central_custom_id("meta", "remove_selected_objective"),
                    label="Remover",
                    emoji="🗑️",
                    style=4,
                ),
                button(
                    custom_id=dashboard.central_custom_id("meta", "back_to_objectives"),
                    label="Voltar",
                    style=2,
                ),
            ),
            accent_color=COLOR,
        )
    )


async def select_objective(interaction: discord.Interaction, api: Any) -> None:
    values = list((interaction.data or {}).get("values") or [])
    if not values:
        return
    key = (int(interaction.guild_id or 0), interaction.user.id)
    selected = str(values[0])
    if selected.startswith("page:"):
        delta = -1 if selected == "page:prev" else 1
        _objective_pages[key] = max(0, _objective_pages.get(key, 0) + delta)
        draft = await api.meta_draft(interaction.guild_id, actor=actor_from(interaction))
        await _show_editor(interaction, draft)
        return
    index = int(selected.split(":", 1)[1])
    draft = await api.meta_draft(interaction.guild_id, actor=actor_from(interaction))
    _selected_objectives[key] = index
    try:
        data = _objective_action_payload(draft, index)
    except ValueError as exc:
        await _reply(interaction, str(exc))
        return
    await edit_interaction_message(interaction, data, ephemeral=True)


async def edit_selected_objective(interaction: discord.Interaction, api: Any) -> None:
    key = (int(interaction.guild_id or 0), interaction.user.id)
    index = _selected_objectives.get(key)
    draft = await api.meta_draft(interaction.guild_id, actor=actor_from(interaction))
    objectives = list(draft["data"].get("objectives") or [])
    if index is None or index < 0 or index >= len(objectives):
        await _show_editor(interaction, draft, banner="Selecione o objetivo novamente.")
        return
    item = objectives[index]
    modal: EditorModal
    if item.get("kind") == "money":
        modal = MoneyObjectiveModal(api, interaction, objective=item, index=index)
    else:
        modal = ItemObjectiveModal(api, interaction, objective=item, index=index)
    await interaction.response.send_modal(modal)


async def remove_selected_objective(interaction: discord.Interaction, api: Any) -> None:
    key = (int(interaction.guild_id or 0), interaction.user.id)
    index = _selected_objectives.get(key)
    actor = actor_from(interaction)
    current = await api.meta_draft(interaction.guild_id, actor=actor)
    objectives = list(current["data"].get("objectives") or [])
    if index is None or index < 0 or index >= len(objectives):
        await _show_editor(interaction, current, banner="Selecione o objetivo novamente.")
        return
    removed = objectives.pop(index)
    saved = await api.meta_patch_draft(
        interaction.guild_id,
        {
            "expected_revision": current["revision"],
            "step": "objectives",
            "patch": {"objectives": objectives},
        },
        actor=actor,
    )
    _selected_objectives.pop(key, None)
    await _show_editor(
        interaction, saved, banner=f"{removed.get('name') or 'Objetivo'} removido."
    )


async def back_to_objectives(interaction: discord.Interaction, api: Any) -> None:
    draft = await api.meta_draft(interaction.guild_id, actor=actor_from(interaction))
    await _show_editor(interaction, draft)


async def objectives_continue(interaction: discord.Interaction, api: Any) -> None:
    actor = actor_from(interaction)
    current = await api.meta_draft(interaction.guild_id, actor=actor)
    if not _objectives_match_mode(current["data"]):
        await _show_editor(
            interaction,
            current,
            banner="Adicione ao menos um objetivo compativel com o tipo da Meta.",
        )
        return
    saved = await api.meta_patch_draft(
        interaction.guild_id,
        {"expected_revision": current["revision"], "step": "notice", "patch": {}},
        actor=actor,
    )
    await _show_editor(interaction, saved)


async def edit_notice(interaction: discord.Interaction, api: Any) -> None:
    draft = await api.meta_draft(interaction.guild_id, actor=actor_from(interaction))
    await interaction.response.send_modal(
        NoticeModal(api, interaction, str(draft["data"].get("notice_text") or ""))
    )


async def submit_goal(interaction: discord.Interaction, api: Any) -> None:
    actor = actor_from(interaction)
    try:
        current = await api.meta_draft(interaction.guild_id, actor=actor)
        await api.meta_submit_draft(interaction.guild_id, current["revision"], actor=actor)
        saved = await api.meta_draft(interaction.guild_id, actor=actor)
        await _show_editor(interaction, saved)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409:
            current = await api.meta_draft(interaction.guild_id, actor=actor)
            await _show_editor(
                interaction,
                current,
                banner="Outro administrador alterou esta Meta. A versao atual foi recarregada; revise novamente.",
            )
            return
        await _reply(interaction, _error_text(exc))
    except Exception as exc:
        await _reply(interaction, _error_text(exc))


def _member_snapshots(guild: discord.Guild) -> list[dict[str, Any]]:
    return [
        {
            "member_id": str(member.id),
            "display_name": member.display_name[:120],
            "role_ids": [str(role.id) for role in member.roles if not role.is_default()],
        }
        for member in guild.members
        if not member.bot
    ]


def _cycle_period(cycle: dict[str, Any]) -> str:
    zone = ZoneInfo(str(cycle.get("timezone") or "UTC"))

    def local(value: Any) -> datetime:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result.astimezone(zone)

    starts_at = local(cycle["starts_at"])
    ends_at = local(cycle["ends_at"])
    return (
        f"{starts_at:%d/%m/%Y %H:%M} → {ends_at:%d/%m/%Y %H:%M}\n"
        f"Encerra <t:{int(ends_at.timestamp())}:R>"
    )


def _notice_component_id(cycle: dict[str, Any]) -> int:
    value = int(cycle["id"]) & 0xFFFFFFFF
    return value or 1


def _notice_nonce(cycle: dict[str, Any]) -> str:
    digest = hashlib.blake2s(
        str(cycle["notice_reference"]).encode("utf-8"), digest_size=8
    ).hexdigest()
    return f"meta-{digest}"


def _notice_payload(goal: dict[str, Any], cycle: dict[str, Any], *, ended: bool) -> dict[str, Any]:
    objectives = _objective_lines({"objectives": cycle.get("objectives") or []})
    name = str(cycle.get("name") or goal["name"])
    heading = f"🏁 Meta Encerrada — {name}" if ended else f"🎯 {name}"
    prefix = "" if ended else "@everyone\n\n"
    data = container(
        text_display(f"{prefix}# {heading}"),
        text_display(str(cycle.get("notice_text") or "")),
        separator(),
        text_display(f"### 📅 Período\n{_cycle_period(cycle)}"),
        separator(),
        text_display(f"### 📦 Objetivos\n{objectives}"),
        accent_color=COLOR,
        component_id=_notice_component_id(cycle),
    )
    return payload(data) if ended else meta_notice_payload(data)


async def _channel_for_launch(guild: discord.Guild, channel_id: int) -> discord.TextChannel:
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        raise RetryableJobError("Canal de avisos de Meta nao encontrado.")
    member = guild.me
    permissions = channel.permissions_for(member) if member else None
    required = ("view_channel", "send_messages", "read_message_history", "mention_everyone")
    if not permissions or any(not getattr(permissions, value, False) for value in required):
        raise RetryableJobError("Permissoes insuficientes no canal de avisos de Meta.")
    return channel


def _component_contains_id(value: Any, expected: int) -> bool:
    if isinstance(value, dict):
        if value.get("id") == expected:
            return True
        return any(
            _component_contains_id(child, expected)
            for child in value.get("components") or []
        )
    if isinstance(value, (list, tuple)):
        return any(_component_contains_id(child, expected) for child in value)
    if getattr(value, "id", None) == expected:
        return True
    children = getattr(value, "children", None) or getattr(value, "components", None) or []
    return any(_component_contains_id(child, expected) for child in children)


async def _find_notice(channel: discord.TextChannel, cycle: dict[str, Any]) -> discord.Message | None:
    message_id = cycle.get("notice_message_id")
    if message_id:
        try:
            return await channel.fetch_message(int(message_id))
        except discord.HTTPException:
            pass
    component_id = _notice_component_id(cycle)
    nonce = _notice_nonce(cycle)
    legacy_reference = str(cycle["notice_reference"])
    started_at = datetime.fromisoformat(str(cycle["starts_at"]).replace("Z", "+00:00"))
    try:
        async for message in channel.history(limit=None, after=started_at):
            bot_member = channel.guild.me
            if bot_member is None or message.author.id != bot_member.id:
                continue
            if str(getattr(message, "nonce", "")) == nonce or _component_contains_id(
                message.components, component_id
            ) or (
                legacy_reference in message.content
                or legacy_reference in str(message.components)
            ):
                return message
    except discord.HTTPException:
        return None
    return None


async def _end_notice(bot: discord.Client, api: Any, guild_id: int, goal_id: int, channel_id: int, message_id: int) -> None:
    goal = await api.meta_goal(guild_id, goal_id)
    cycle = goal.get("latest_cycle")
    if not cycle:
        return
    await edit_message(bot, channel_id, message_id, _notice_payload(goal, cycle, ended=True))


async def run_job(bot: discord.Client, api: Any, item: dict[str, Any]) -> dict[str, Any]:
    guild_id = int(item["guild_id"])
    guild = bot.get_guild(guild_id)
    if guild is None:
        raise RetryableJobError("Guild da Meta nao esta disponivel no bot.")
    causation_id = str(item.get("correlation_id") or item["id"])
    if item["key"] == "meta.recovery":
        return await api.meta_recovery(guild_id, causation_id)
    payload_data = item.get("payload") or {}
    if item["key"] == "meta.notice.reconcile":
        goal = await api.meta_goal(guild_id, int(payload_data["goal_id"]))
        cycle = goal.get("latest_cycle")
        if cycle is None or int(cycle["id"]) != int(payload_data["cycle_id"]):
            raise RetryableJobError("Ciclo do aviso encerrado nao foi encontrado.")
        await edit_message(
            bot,
            int(payload_data["channel_id"]),
            int(payload_data["message_id"]),
            _notice_payload(goal, cycle, ended=True),
        )
        return {"reconciled": True, "cycle_id": cycle["id"]}
    if item["key"] == "meta.cycle.transition":
        goal_id = int(payload_data["goal_id"])
        cycle_id = int(payload_data["cycle_id"])
        goal = await api.meta_goal(guild_id, goal_id)
        cycle = goal.get("latest_cycle")
        if cycle and cycle.get("notice_message_id"):
            await edit_message(
                bot,
                int(cycle["notice_channel_id"]),
                int(cycle["notice_message_id"]),
                _notice_payload(goal, cycle, ended=True),
            )
        return await api.meta_transition_cycle(guild_id, cycle_id, causation_id)
    goal_id = int(payload_data["goal_id"])
    settings_data = await api.meta_settings(guild_id)
    if not settings_data.get("notice_channel_id"):
        raise RetryableJobError("Canal de avisos de Meta ainda nao foi configurado.")
    channel = await _channel_for_launch(guild, int(settings_data["notice_channel_id"]))
    if not guild.chunked:
        await guild.chunk(cache=True)
    members = _member_snapshots(guild)
    prepared = await api.meta_prepare_launch(
        guild_id,
        goal_id,
        {
            "members": members,
            "notice_channel_id": str(channel.id),
            "causation_id": causation_id,
        },
    )
    if prepared.get("status") != "prepared":
        return prepared
    cycle = prepared["cycle"]
    goal = await api.meta_goal(guild_id, goal_id)
    notice = await _find_notice(channel, cycle)
    if notice is None:
        message_id = await send_meta_notice(
            bot,
            channel.id,
            _notice_payload(goal, cycle, ended=False),
            nonce=_notice_nonce(cycle),
        )
        try:
            notice = await channel.fetch_message(message_id)
        except discord.HTTPException:
            notice = None
        await api.meta_record_notice(guild_id, cycle["id"], channel.id, message_id)
    else:
        message_id = notice.id
        await api.meta_record_notice(guild_id, cycle["id"], channel.id, message_id)
    try:
        activated = await api.meta_activate_cycle(
            guild_id,
            cycle["id"],
            {
                "members": _member_snapshots(guild),
                "notice_channel_id": str(channel.id),
                "notice_message_id": str(message_id),
                "causation_id": causation_id,
            },
        )
    except Exception:
        try:
            if notice is not None:
                await notice.delete()
            else:
                message = await channel.fetch_message(message_id)
                await message.delete()
        except discord.HTTPException:
            pass
        raise
    if activated.get("status") != "active":
        await edit_message(bot, channel.id, message_id, _notice_payload(goal, cycle, ended=True))
    for old in activated.get("ended_notices") or []:
        if old.get("message_id"):
            try:
                await _end_notice(
                    bot,
                    api,
                    guild_id,
                    int(old["goal_id"]),
                    int(old["channel_id"]),
                    int(old["message_id"]),
                )
            except discord.HTTPException:
                log.exception("Falha ao encerrar aviso substituido da Meta %s", old["goal_id"])
    return activated
