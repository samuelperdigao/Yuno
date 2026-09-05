from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import discord
import httpx

from yuno_bot import dashboard
from yuno_bot.domain_modules.bau.renderers import BauLogData, BauRenderer
from yuno_bot.platform.components_v2 import (
    action_row,
    button,
    channel_select,
    edit_message,
    payload,
    role_select,
    string_select,
)
from yuno_bot.platform.contracts import (
    ActorContext,
    ComponentsV2Payload,
    InteractionResult,
    RoutedContext,
)
from yuno_bot.platform import ui_kit as uk
from yuno_bot.platform.panels import PanelPublisher
from yuno_bot.platform.router import RoutedModal, custom_id

COLOR = uk.BRAND
PAGE_SIZE = 5


def actor_from(interaction: discord.Interaction) -> ActorContext:
    member = interaction.user if isinstance(interaction.user, discord.Member) else None
    permissions = tuple(name for name, enabled in member.guild_permissions if enabled) if member else ()
    role_ids = tuple(role.id for role in member.roles) if member else ()
    return ActorContext(
        guild_id=interaction.guild_id or 0,
        user_id=interaction.user.id if interaction.user else None,
        role_ids=role_ids,
        discord_permissions=permissions,
        channel_id=interaction.channel_id,
        category_id=getattr(interaction.channel, "category_id", None),
        actor_type="user",
        is_guild_owner=bool(
            interaction.guild
            and interaction.user
            and interaction.guild.owner_id == interaction.user.id
        ),
        correlation_id=str(interaction.id),
    )


def system_actor(bot: discord.Client, guild_id: int, correlation_id: str) -> ActorContext:
    if bot.user is None:
        raise RuntimeError("Bot ainda não está pronto.")
    return ActorContext(
        guild_id=guild_id,
        user_id=bot.user.id,
        role_ids=(),
        discord_permissions=(),
        channel_id=None,
        category_id=None,
        actor_type="system",
        is_guild_owner=False,
        correlation_id=correlation_id,
    )


def error_text(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            detail = exc.response.json().get("detail", "Operação recusada.")
            if isinstance(detail, dict):
                return str(detail.get("message") or detail.get("detail") or detail)
            return str(detail)
        except Exception:
            return f"A API recusou a operação ({exc.response.status_code})."
    if isinstance(exc, (RuntimeError, ValueError)):
        return str(exc)
    return "Não consegui concluir a operação."


def _modal_values(interaction: discord.Interaction) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in (interaction.data or {}).get("components") or []:
        for component in row.get("components") or []:
            if component.get("custom_id"):
                result[str(component["custom_id"])] = str(component.get("value") or "")
    return result


def _selected_ids(interaction: discord.Interaction) -> list[str]:
    return [str(value) for value in (interaction.data or {}).get("values") or []]


def _discord_ref(value: Any, *, kind: str) -> str:
    text = str(value or "").strip()
    if not (text.isascii() and text.isdigit()):
        return "⚪ Não configurado"
    return f"<#{text}>" if kind == "channel" else f"<@&{text}>"


def _role_refs(role_ids: list[str]) -> str:
    if not role_ids:
        return "⚪ Nenhum cargo (somente administradores podem movimentar)"
    return ", ".join(f"<@&{role_id}>" for role_id in role_ids)


async def _defer_if_needed(interaction: discord.Interaction) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer()


async def _send_interaction_error(interaction: discord.Interaction, message: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


async def _replace_central(
    interaction: discord.Interaction,
    data: dict[str, Any],
    *,
    channel_id: int | None = None,
    message_id: int | None = None,
) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer()
    target_channel = channel_id or interaction.channel_id
    target_message = message_id or getattr(interaction.message, "id", None)
    if target_channel is None or target_message is None:
        raise RuntimeError("Referência da Central indisponível.")
    await edit_message(interaction.client, target_channel, target_message, data)


# --------------------------------------------------------------------------- #
# Painel público
# --------------------------------------------------------------------------- #


async def render_stock(context: dict) -> ComponentsV2Payload:
    config = context.get("config")
    summary = context.get("summary")
    if config is None:
        config = (await context["api"].bau_config(context["guild"].id))["data"]
    if summary is None:
        summary = await context["api"].bau_summary(context["guild"].id)
    if summary:
        lines = "\n".join(
            f"**{item['name']}** — {item['item_count']} itens · {item['total_quantity']} unidades"
            for item in summary
        )
    else:
        lines = uk.empty_state(
            "Catálogo vazio", "Publique a configuração para popular o catálogo padrão."
        )
    actions = []
    if summary:
        options = [
            {
                "label": item["name"][:100],
                "value": item["id"],
                "description": f"{item['item_count']} item(ns)"[:100],
            }
            for item in summary
        ]
        actions.append(
            action_row(
                string_select(
                    custom_id=custom_id("bau", "stock", "select_category"),
                    options=options,
                    placeholder="Selecione uma categoria para movimentar…",
                )
            )
        )
    return ComponentsV2Payload(
        payload(
            uk.panel(
                header=uk.heading(config["panel_title"], emoji="📦")
                + "\n\n"
                + config["panel_description"],
                blocks=[f"### Estoque atual\n{lines}"],
                actions=actions,
                footer=config.get("panel_footer") or "Yuno",
                accent_color=COLOR,
            )
        )
    )


class BauCategoryBrowseView(discord.ui.View):
    """Navegação efêmera de itens de uma categoria. Vive só durante a
    interação (não é persistida entre restarts), como o restante das
    sub-telas administrativas do Yuno."""

    def __init__(
        self,
        *,
        api: Any,
        panel: dict[str, Any],
        category_name: str,
        items: list[dict[str, Any]],
        page: int = 0,
        timeout: float | None = 600,
    ) -> None:
        super().__init__(timeout=timeout)
        self.api = api
        self.panel = panel
        self.category_name = category_name
        self.items = items
        self.page = page
        self._sync_buttons()

    @property
    def total_pages(self) -> int:
        return max(1, (len(self.items) + PAGE_SIZE - 1) // PAGE_SIZE)

    def page_items(self) -> list[dict[str, Any]]:
        start = self.page * PAGE_SIZE
        return self.items[start : start + PAGE_SIZE]

    def render_text(self) -> str:
        lines = "\n".join(
            f"**{item['name']}** — {item['quantity']} unidades" for item in self.page_items()
        )
        return f"### {self.category_name} (página {self.page + 1}/{self.total_pages})\n{lines}"

    def _sync_buttons(self) -> None:
        self.previous_page.disabled = self.page <= 0
        self.next_page.disabled = self.page >= self.total_pages - 1

    @discord.ui.button(label="◀ Anterior", style=discord.ButtonStyle.secondary)
    async def previous_page(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        self.page = max(0, self.page - 1)
        self._sync_buttons()
        await interaction.response.edit_message(content=self.render_text(), view=self)

    @discord.ui.button(label="▶ Próxima", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.page = min(self.total_pages - 1, self.page + 1)
        self._sync_buttons()
        await interaction.response.edit_message(content=self.render_text(), view=self)

    @discord.ui.button(label="✏️ Registrar movimentação", style=discord.ButtonStyle.primary)
    async def open_modal(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            BauMovementModal(panel=self.panel, items=self.page_items())
        )


class BauMovementModal(RoutedModal):
    def __init__(self, *, panel: dict[str, Any], items: list[dict[str, Any]]) -> None:
        super().__init__(
            title="Baú · Movimentar estoque",
            module_key="bau",
            surface="stock",
            action_key="submit_movement",
            panel=panel,
        )
        for item in items:
            self.add_item(
                discord.ui.TextInput(
                    label=f"{item['name']} (atual: {item['quantity']})"[:45],
                    custom_id=f"bau_item_{item['id']}",
                    required=False,
                    max_length=10,
                    placeholder="+10 ou -5 (vazio = sem alteração)",
                )
            )


async def select_category(context: RoutedContext) -> InteractionResult:
    values = _selected_ids(context.interaction)
    if not values:
        return InteractionResult(content="Selecione uma categoria.")
    category_id = values[0]
    catalog = await context.api.bau_catalog(context.actor.guild_id)
    category = next((item for item in catalog if item["id"] == category_id), None)
    if category is None:
        return InteractionResult(content="Categoria não encontrada.")
    items = category["items"]
    if not items:
        return InteractionResult(
            content=f"A categoria **{category['name']}** ainda não tem itens cadastrados."
        )
    view = BauCategoryBrowseView(
        api=context.api, panel=context.panel, category_name=category["name"], items=items, page=0
    )
    return InteractionResult(content=view.render_text(), view=view, ephemeral=True)


async def _reconcile_stock_panel(
    api: Any, client: discord.Client, guild: discord.Guild, actor: ActorContext
) -> None:
    config_ref = await api.bau_config(guild.id)
    config = config_ref["data"]
    if not config.get("panel_channel_id"):
        return
    summary = await api.bau_summary(guild.id)
    try:
        await PanelPublisher(client, api).reconcile(
            guild=guild,
            module_key="bau",
            panel_key="stock",
            channel_id=int(config["panel_channel_id"]),
            actor=actor,
            render_context={
                "config": config,
                "summary": summary,
                "config_version": config_ref["version"],
            },
        )
    except Exception:
        try:
            await api.schedule_task(
                guild.id,
                "bau",
                {
                    "job_key": "bau.panel.reconcile",
                    "resource_type": "panel",
                    "resource_id": "stock",
                    "payload": {"panel_key": "stock"},
                    "due_at": datetime.now(timezone.utc).isoformat(),
                    "idempotency_key": f"stock:{actor.correlation_id}",
                    "correlation_id": actor.correlation_id,
                    "max_attempts": 5,
                },
            )
        except Exception:
            pass


async def submit_movement(context: RoutedContext) -> InteractionResult:
    values = _modal_values(context.interaction)
    items = [
        {"item_id": key[len("bau_item_") :], "raw": value}
        for key, value in values.items()
        if key.startswith("bau_item_") and value.strip()
    ]
    if not items:
        return InteractionResult(content="Nenhuma alteração informada.")
    try:
        result = await context.api.bau_movements(context.actor.guild_id, items, actor=context.actor)
    except Exception as exc:
        return InteractionResult(content=error_text(exc))
    lines = "\n".join(
        f"**{change['item_name']}** — {'+' if change['delta'] > 0 else ''}{change['delta']} "
        f"({change['before']} → {change['after']})"
        for change in result["changes"]
    )
    guild = context.interaction.guild
    if guild is not None:
        await _reconcile_stock_panel(context.api, context.interaction.client, guild, context.actor)
    return InteractionResult(content=f"Movimentação registrada.\n{lines}", ephemeral=True)


async def deliver_log(bot: discord.Client, item: dict[str, Any]) -> str | None:
    channel = bot.get_channel(int(item["destination_id"]))
    if channel is None:
        channel = await bot.fetch_channel(int(item["destination_id"]))
    data = item.get("payload") or {}
    resolved = BauLogData.from_payload(data)
    embed = BauRenderer().render_log(resolved)
    message = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    return str(message.id)


async def run_job(bot: discord.Client, api: Any, item: dict[str, Any]) -> dict:
    guild = bot.get_guild(int(item["guild_id"]))
    if guild is None:
        raise RuntimeError("Guild indisponível para recuperação.")
    actor = system_actor(bot, guild.id, item["correlation_id"])
    if item["key"] != "bau.panel.reconcile":
        return {"changed": False, "reason": "job desconhecido"}
    await _reconcile_stock_panel(api, bot, guild, actor)
    instance = await api.module_instance(guild.id, "bau")
    activated = False
    if instance["lifecycle"] != "active":
        await api.update_lifecycle(
            guild.id,
            "bau",
            lifecycle="active",
            expected_lifecycle=instance["lifecycle"],
            actor=actor,
            reason="Painel público recuperado após publicação.",
        )
        activated = True
    return {"changed": True, "panel_key": "stock", "activated": activated}


# --------------------------------------------------------------------------- #
# Central administrativa
# --------------------------------------------------------------------------- #


async def _admin_state(api: Any, guild_id: int) -> tuple[dict, dict]:
    return (
        await api.module_instance(guild_id, "bau"),
        await api.configuration_draft(guild_id, "bau"),
    )


async def _catalog_stats(api: Any, guild_id: int) -> tuple[int, int, int]:
    try:
        catalog = await api.bau_catalog(guild_id)
    except Exception:
        return 0, 0, 0
    categories = len(catalog)
    total_items = sum(len(category["items"]) for category in catalog)
    total_quantity = sum(
        item["quantity"] for category in catalog for item in category["items"]
    )
    return categories, total_items, total_quantity


def build_admin_payload(
    instance: dict, draft: dict, catalog_stats: tuple[int, int, int]
) -> dict[str, Any]:
    published = int(draft["base_published_version"] or 0)
    config = draft["data"]
    is_active = published > 0 and instance["lifecycle"] == "active"
    if is_active:
        status = f"🟢 **Ativo** · versão `{published}`"
    elif published:
        status = f"🟠 **Desativado** · versão `{published}`"
    else:
        status = "⚪ **Ainda não publicado**"
    categories, total_items, total_quantity = catalog_stats
    return payload(
        uk.panel(
            header=[dashboard.module_navigation("bau"), uk.heading("Baú da Gerência", emoji="📦")],
            blocks=[
                f"### Status\n{status}",
                (
                    "### Configuração\n"
                    f"**Painel** — {_discord_ref(config.get('panel_channel_id'), kind='channel')}\n"
                    f"**Logs** — {_discord_ref(config.get('log_channel_id'), kind='channel')}\n"
                    f"**Cargos de movimentação** — {_role_refs(config.get('staff_role_ids') or [])}"
                ),
                (
                    "### Catálogo\n"
                    f"{categories} categoria(s) · {total_items} item(ns) · "
                    f"{total_quantity} unidade(s) no total"
                ),
            ],
            actions=[
                action_row(
                    channel_select(
                        custom_id=dashboard.central_custom_id("bau", "set_panel_channel"),
                        placeholder="Publicar o painel de estoque em…",
                        channel_types=[0],
                    )
                ),
                action_row(
                    channel_select(
                        custom_id=dashboard.central_custom_id("bau", "set_log_channel"),
                        placeholder="Enviar logs de movimentação em…",
                        channel_types=[0],
                    )
                ),
                action_row(
                    role_select(
                        custom_id=dashboard.central_custom_id("bau", "set_staff_roles"),
                        placeholder="Cargos que podem movimentar estoque…",
                        min_values=0,
                        max_values=5,
                    )
                ),
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id("bau", "add_category"),
                        label="Nova categoria",
                        emoji="➕",
                        style=2,
                    ),
                    button(
                        custom_id=dashboard.central_custom_id("bau", "edit_category"),
                        label="Editar categoria",
                        emoji="✏️",
                        style=2,
                    ),
                ),
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id("bau", "add_item"),
                        label="Novo item",
                        emoji="➕",
                        style=2,
                    ),
                    button(
                        custom_id=dashboard.central_custom_id("bau", "edit_item"),
                        label="Editar item",
                        emoji="✏️",
                        style=2,
                    ),
                ),
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id("bau", "clear_stock_confirm"),
                        label="Limpar estoque",
                        emoji="🧹",
                        style=4,
                    ),
                    button(
                        custom_id=dashboard.central_custom_id("bau", "review_publish"),
                        label="Revisar e publicar",
                        emoji="👁️",
                        style=1,
                    ),
                ),
            ],
            accent_color=COLOR,
        )
    )


async def render_admin(interaction: discord.Interaction, api: Any) -> None:
    try:
        instance, draft = await _admin_state(api, interaction.guild_id)
        stats = await _catalog_stats(api, interaction.guild_id)
        await _replace_central(interaction, build_admin_payload(instance, draft, stats))
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))


async def open_system(interaction: discord.Interaction, api: Any) -> None:
    await render_admin(interaction, api)


async def _refresh_admin(
    interaction: discord.Interaction, api: Any, channel_id: int, message_id: int
) -> None:
    instance, draft = await _admin_state(api, interaction.guild_id)
    stats = await _catalog_stats(api, interaction.guild_id)
    await _replace_central(
        interaction,
        build_admin_payload(instance, draft, stats),
        channel_id=channel_id,
        message_id=message_id,
    )


async def _save_patch(interaction: discord.Interaction, api: Any, patch: dict[str, Any]) -> dict:
    draft = await api.configuration_draft(interaction.guild_id, "bau")
    actor = actor_from(interaction)
    return await api.save_configuration_draft(
        interaction.guild_id,
        "bau",
        {
            "expected_revision": draft["revision"],
            "expected_published_version": draft["base_published_version"],
            "schema_version": draft["schema_version"],
            "data": {**draft["data"], **patch},
        },
        actor=actor,
    )


async def set_panel_channel(interaction: discord.Interaction, api: Any) -> None:
    await _set_selected_channel(interaction, api, "panel_channel_id")


async def set_log_channel(interaction: discord.Interaction, api: Any) -> None:
    await _set_selected_channel(interaction, api, "log_channel_id")


async def _set_selected_channel(interaction: discord.Interaction, api: Any, field: str) -> None:
    values = _selected_ids(interaction)
    if not values:
        await _send_interaction_error(interaction, "Selecione um canal.")
        return
    await _defer_if_needed(interaction)
    await _save_patch(interaction, api, {field: values[0]})
    await render_admin(interaction, api)


async def set_staff_roles(interaction: discord.Interaction, api: Any) -> None:
    values = _selected_ids(interaction)
    await _defer_if_needed(interaction)
    await _save_patch(interaction, api, {"staff_role_ids": values})
    await render_admin(interaction, api)


class BauCategoryAddModal(discord.ui.Modal):
    def __init__(self, api: Any, channel_id: int, message_id: int) -> None:
        super().__init__(title="Baú · Nova categoria")
        self.api = api
        self.central_channel_id = channel_id
        self.central_message_id = message_id
        self.add_item(discord.ui.TextInput(label="Nome da categoria", custom_id="name", max_length=60))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        values = _modal_values(interaction)
        actor = actor_from(interaction)
        try:
            await interaction.response.defer()
            await self.api.bau_category_create(
                interaction.guild_id, values.get("name", "").strip(), actor=actor
            )
            await _refresh_admin(
                interaction, self.api, self.central_channel_id, self.central_message_id
            )
        except Exception as exc:
            await _send_interaction_error(interaction, error_text(exc))


async def add_category(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.send_modal(
        BauCategoryAddModal(api, interaction.channel_id, interaction.message.id)
    )


class BauCategoryEditModal(discord.ui.Modal):
    def __init__(self, api: Any, channel_id: int, message_id: int) -> None:
        super().__init__(title="Baú · Editar categoria")
        self.api = api
        self.central_channel_id = channel_id
        self.central_message_id = message_id
        self.add_item(
            discord.ui.TextInput(label="Categoria atual (nome exato)", custom_id="name", max_length=60)
        )
        self.add_item(
            discord.ui.TextInput(
                label="Novo nome (ou digite REMOVER)", custom_id="new_name", max_length=60
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        values = _modal_values(interaction)
        name = values.get("name", "").strip()
        new_name = values.get("new_name", "").strip()
        actor = actor_from(interaction)
        try:
            await interaction.response.defer()
            if new_name.upper() == "REMOVER":
                await self.api.bau_category_remove(interaction.guild_id, name, actor=actor)
            else:
                await self.api.bau_category_rename(interaction.guild_id, name, new_name, actor=actor)
            await _refresh_admin(
                interaction, self.api, self.central_channel_id, self.central_message_id
            )
        except Exception as exc:
            await _send_interaction_error(interaction, error_text(exc))


async def edit_category(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.send_modal(
        BauCategoryEditModal(api, interaction.channel_id, interaction.message.id)
    )


class BauItemAddModal(discord.ui.Modal):
    def __init__(self, api: Any, channel_id: int, message_id: int) -> None:
        super().__init__(title="Baú · Novo item")
        self.api = api
        self.central_channel_id = channel_id
        self.central_message_id = message_id
        self.add_item(
            discord.ui.TextInput(label="Categoria (nome exato)", custom_id="category_name", max_length=60)
        )
        self.add_item(discord.ui.TextInput(label="Nome do item", custom_id="name", max_length=80))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        values = _modal_values(interaction)
        actor = actor_from(interaction)
        try:
            await interaction.response.defer()
            await self.api.bau_item_create(
                interaction.guild_id,
                values.get("category_name", "").strip(),
                values.get("name", "").strip(),
                actor=actor,
            )
            await _refresh_admin(
                interaction, self.api, self.central_channel_id, self.central_message_id
            )
        except Exception as exc:
            await _send_interaction_error(interaction, error_text(exc))


async def add_item(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.send_modal(
        BauItemAddModal(api, interaction.channel_id, interaction.message.id)
    )


class BauItemEditModal(discord.ui.Modal):
    def __init__(self, api: Any, channel_id: int, message_id: int) -> None:
        super().__init__(title="Baú · Editar item")
        self.api = api
        self.central_channel_id = channel_id
        self.central_message_id = message_id
        self.add_item(
            discord.ui.TextInput(label="Nome atual do item (exato)", custom_id="name", max_length=80)
        )
        self.add_item(
            discord.ui.TextInput(
                label="Novo nome (ou digite REMOVER)", custom_id="new_name", max_length=80
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        values = _modal_values(interaction)
        name = values.get("name", "").strip()
        new_name = values.get("new_name", "").strip()
        actor = actor_from(interaction)
        try:
            await interaction.response.defer()
            if new_name.upper() == "REMOVER":
                await self.api.bau_item_remove(interaction.guild_id, name, actor=actor)
            else:
                await self.api.bau_item_rename(interaction.guild_id, name, new_name, actor=actor)
            await _refresh_admin(
                interaction, self.api, self.central_channel_id, self.central_message_id
            )
        except Exception as exc:
            await _send_interaction_error(interaction, error_text(exc))


async def edit_item(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.send_modal(
        BauItemEditModal(api, interaction.channel_id, interaction.message.id)
    )


async def clear_stock_confirm(interaction: discord.Interaction, api: Any) -> None:
    await _defer_if_needed(interaction)
    await _replace_central(
        interaction,
        payload(
            uk.panel(
                header=[dashboard.module_navigation("bau"), uk.heading("Baú da Gerência", emoji="📦")],
                blocks=[
                    "# 🧹 Confirmar limpeza do estoque\n\n"
                    "Esta ação zera a quantidade de **todos os itens** do Baú. "
                    "Não pode ser desfeita."
                ],
                actions=[
                    action_row(
                        button(
                            custom_id=dashboard.central_custom_id("bau", "clear_stock_execute"),
                            label="Confirmar limpeza",
                            emoji="🧹",
                            style=4,
                        ),
                        button(
                            custom_id=dashboard.central_custom_id("bau", "open_system"),
                            label="Cancelar",
                            emoji="↩️",
                            style=2,
                        ),
                    )
                ],
                accent_color=uk.DANGER,
            )
        ),
    )


async def clear_stock_execute(interaction: discord.Interaction, api: Any) -> None:
    await _defer_if_needed(interaction)
    actor = actor_from(interaction)
    try:
        result = await api.bau_clear(interaction.guild_id, actor=actor)
        await render_admin(interaction, api)
        await interaction.followup.send(
            f"Estoque zerado: {result['items_reset']} item(ns).", ephemeral=True
        )
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))


async def _preflight(guild: discord.Guild, config: dict) -> list[str]:
    errors: list[str] = []
    bot_member = guild.me
    if not config.get("panel_channel_id"):
        errors.append("Campo obrigatório ausente: panel_channel_id.")
    for key in ("panel_channel_id", "log_channel_id"):
        value = config.get(key)
        if not value:
            continue
        channel = guild.get_channel(int(value))
        if not isinstance(channel, discord.TextChannel):
            errors.append(f"{key} não aponta para canal de texto.")
            continue
        if bot_member:
            perms = channel.permissions_for(bot_member)
            if not perms.view_channel or not perms.send_messages:
                errors.append(f"Bot sem acesso de envio em {channel.mention}.")
    return errors


async def review_publish(interaction: discord.Interaction, api: Any) -> None:
    await _defer_if_needed(interaction)
    _, draft = await _admin_state(api, interaction.guild_id)
    errors = await _preflight(interaction.guild, draft["data"])
    if errors:
        await _send_interaction_error(interaction, "Publicação bloqueada:\n- " + "\n- ".join(errors))
        return
    config = draft["data"]
    await _replace_central(
        interaction,
        payload(
            uk.panel(
                header=[dashboard.module_navigation("bau"), uk.heading("Baú da Gerência", emoji="📦")],
                blocks=[
                    "# 👁️ Revisar publicação do Baú\n\n"
                    f"Painel: <#{config['panel_channel_id']}>\n"
                    f"Logs: {_discord_ref(config.get('log_channel_id'), kind='channel')}\n"
                    f"Cargos de movimentação: {_role_refs(config.get('staff_role_ids') or [])}\n\n"
                    "A confirmação cria uma versão imutável, popula o catálogo padrão "
                    "(se ainda não existir) e reconcilia o painel público."
                ],
                actions=[
                    action_row(
                        button(
                            custom_id=dashboard.central_custom_id("bau", "confirm_publish"),
                            label="Confirmar publicação",
                            emoji="✅",
                            style=3,
                        ),
                        button(
                            custom_id=dashboard.central_custom_id("bau", "open_system"),
                            label="Voltar",
                            emoji="↩️",
                            style=2,
                        ),
                    )
                ],
                accent_color=COLOR,
            )
        ),
    )


async def confirm_publish(interaction: discord.Interaction, api: Any) -> None:
    await _defer_if_needed(interaction)
    actor = actor_from(interaction)
    _, draft = await _admin_state(api, interaction.guild_id)
    errors = await _preflight(interaction.guild, draft["data"])
    if errors:
        await _send_interaction_error(interaction, "Publicação bloqueada:\n- " + "\n- ".join(errors))
        return
    grants = [
        {
            "capability": "bau.move_stock",
            "subject_type": "role",
            "subject_id": role_id,
            "scope_type": "guild",
            "scope_id": "",
            "constraints": {},
        }
        for role_id in (draft["data"].get("staff_role_ids") or [])
    ]
    try:
        version = await api.publish_configuration(
            interaction.guild_id,
            "bau",
            {
                "expected_revision": draft["revision"],
                "expected_published_version": draft["base_published_version"],
                "grants": grants,
            },
            actor=actor,
        )
        await api.bau_seed_catalog(interaction.guild_id, actor=actor)
        instance = await api.module_instance(interaction.guild_id, "bau")
        try:
            await _reconcile_stock_panel(api, interaction.client, interaction.guild, actor)
        except Exception:
            pass
        if instance["lifecycle"] != "active":
            await api.update_lifecycle(
                interaction.guild_id,
                "bau",
                lifecycle="active",
                expected_lifecycle=instance["lifecycle"],
                actor=actor,
                reason=None,
            )
        await render_admin(interaction, api)
        await interaction.followup.send(
            f"Baú publicado na versão {version['version']}.", ephemeral=True
        )
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))
