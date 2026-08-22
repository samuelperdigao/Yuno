from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
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


def _objective_lines(data: dict[str, Any]) -> str:
    lines = []
    for item in data.get("objectives") or []:
        if item.get("kind") == "money":
            lines.append(f"• {item.get('name', 'Dinheiro')}: R$ {item.get('money_amount')}")
        else:
            lines.append(
                f"• {item.get('name')}: {item.get('item_quantity')} {item.get('unit')}"
            )
    return "\n".join(lines) or "_Nenhum objetivo definido._"


def _editor_payload(draft: dict[str, Any], *, banner: str = "") -> dict[str, Any]:
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
        content.extend(
            [
                text_display(f"### 5. Itens/Dinheiro\n{_objective_lines(data)}"),
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id("meta", "edit_objectives"),
                        label="Informar objetivos",
                        style=1,
                    )
                ),
            ]
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


async def _show_editor(interaction: discord.Interaction, draft: dict[str, Any], *, banner: str = "") -> None:
    await edit_interaction_message(interaction, _editor_payload(draft, banner=banner), ephemeral=True)


class EditorModal(discord.ui.Modal):
    def __init__(self, title: str, api: Any, editor_interaction: discord.Interaction) -> None:
        super().__init__(title=title, timeout=600)
        self.api = api
        self.editor_application_id = int(editor_interaction.application_id)
        self.editor_token = editor_interaction.token

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
            await edit_webhook_message(
                interaction.client,
                application_id=self.editor_application_id,
                interaction_token=self.editor_token,
                data=_editor_payload(saved),
            )
            try:
                await interaction.delete_original_response()
            except discord.HTTPException:
                pass
        except Exception as exc:
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


class ObjectivesModal(EditorModal):
    def __init__(self, api: Any, interaction: discord.Interaction, mode: str) -> None:
        super().__init__("Objetivos da Meta", api, interaction)
        self.mode = mode
        placeholder = {
            "items": "Arma | 10.500 | unidade\nMunicao | 100 | caixa",
            "money": "Dinheiro | 1500.00",
            "mixed": "item | Arma | 10.500 | unidade\nmoney | Dinheiro | 1500.00",
        }.get(mode, "item | Produto | 10 | unidade")
        self.objectives = discord.ui.TextInput(
            label="Um objetivo por linha, separado por |",
            placeholder=placeholder,
            style=discord.TextStyle.paragraph,
            min_length=1,
            max_length=2000,
        )
        self.add_item(self.objectives)

    @staticmethod
    def _decimal(value: str, places: int) -> str:
        amount = Decimal(value.strip())
        if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -places:
            raise ValueError
        return format(amount, "f")

    def _parse(self) -> list[dict[str, Any]]:
        result = []
        for raw in str(self.objectives.value).splitlines():
            parts = [part.strip() for part in raw.split("|")]
            if self.mode == "items":
                if len(parts) != 3:
                    raise ValueError
                result.append(
                    {"kind": "item", "name": parts[0], "item_quantity": self._decimal(parts[1], 3), "unit": parts[2], "money_amount": None}
                )
            elif self.mode == "money":
                if len(parts) != 2:
                    raise ValueError
                result.append(
                    {"kind": "money", "name": parts[0], "money_amount": self._decimal(parts[1], 2), "unit": None, "item_quantity": None}
                )
            elif parts and parts[0].casefold() == "item" and len(parts) == 4:
                result.append(
                    {"kind": "item", "name": parts[1], "item_quantity": self._decimal(parts[2], 3), "unit": parts[3], "money_amount": None}
                )
            elif parts and parts[0].casefold() == "money" and len(parts) == 3:
                result.append(
                    {"kind": "money", "name": parts[1], "money_amount": self._decimal(parts[2], 2), "unit": None, "item_quantity": None}
                )
            else:
                raise ValueError
        if not result:
            raise ValueError
        return result

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            parsed = self._parse()
        except (ValueError, InvalidOperation):
            await interaction.response.send_message(
                "Objetivos invalidos. Use o formato mostrado no campo e valores positivos.", ephemeral=True
            )
            return
        await self.save_patch(interaction, patch={"objectives": parsed}, step="notice")


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
    saved = await api.meta_patch_draft(
        interaction.guild_id,
        {"expected_revision": current["revision"], "step": "objectives", "patch": {"objective_mode": values[0], "objectives": []}},
        actor=actor,
    )
    await _show_editor(interaction, saved)


async def edit_objectives(interaction: discord.Interaction, api: Any) -> None:
    draft = await api.meta_draft(interaction.guild_id, actor=actor_from(interaction))
    await interaction.response.send_modal(
        ObjectivesModal(api, interaction, str(draft["data"].get("objective_mode") or "mixed"))
    )


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


def _notice_payload(goal: dict[str, Any], cycle: dict[str, Any], *, ended: bool) -> dict[str, Any]:
    objectives = _objective_lines({"objectives": cycle.get("objectives") or []})
    heading = "Meta Encerrada" if ended else str(cycle.get("name") or goal["name"])
    prefix = "" if ended else "@everyone\n\n"
    data = container(
        text_display(
            f"{prefix}# 🎯 {heading}\n\n{cycle.get('notice_text') or ''}\n\n"
            f"### Objetivos\n{objectives}\n\n"
            f"**Participantes:** {len(cycle.get('participants') or [])}\n"
            f"_Referencia: {cycle['notice_reference']}_"
        ),
        accent_color=COLOR,
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


async def _find_notice(channel: discord.TextChannel, cycle: dict[str, Any]) -> discord.Message | None:
    message_id = cycle.get("notice_message_id")
    if message_id:
        try:
            return await channel.fetch_message(int(message_id))
        except discord.HTTPException:
            pass
    reference = str(cycle["notice_reference"])
    started_at = datetime.fromisoformat(str(cycle["starts_at"]).replace("Z", "+00:00"))
    try:
        async for message in channel.history(limit=None, after=started_at):
            if message.author.id == channel.guild.me.id and (
                reference in message.content or reference in str(message.components)
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
        message_id = await send_meta_notice(bot, channel.id, _notice_payload(goal, cycle, ended=False))
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
