from __future__ import annotations

from decimal import Decimal
from math import ceil
from typing import Any

import discord

from yuno_bot import dashboard
from yuno_bot.platform import ui_kit as uk
from yuno_bot.platform.components_v2 import (
    action_row,
    button,
    channel_select,
    payload,
    role_select,
    string_select,
    text_display,
)
from yuno_bot.platform.contracts import ActorContext

MODULE_KEY = "chest"
PAGE_SIZE = 23


def actor_from(interaction: discord.Interaction) -> ActorContext:
    member = interaction.user if isinstance(interaction.user, discord.Member) else None
    return ActorContext(
        guild_id=int(interaction.guild_id or 0),
        user_id=interaction.user.id if interaction.user else None,
        role_ids=tuple(role.id for role in member.roles) if member else (),
        discord_permissions=tuple(
            name for name, enabled in member.guild_permissions if enabled
        )
        if member
        else (),
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


def _selected(interaction: discord.Interaction) -> list[str]:
    return [str(value) for value in ((interaction.data or {}).get("values") or [])]


async def _replace(interaction: discord.Interaction, data: dict[str, Any]) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer()
    await dashboard.edit_central_message(
        interaction.client, interaction.channel_id, interaction.message.id, data
    )


def _shell(
    title: str, subtitle: str, blocks: list[Any], actions: list[Any], route: str
) -> dict[str, Any]:
    return dashboard.central_shell(
        payload(
            uk.panel(
                header=[
                    uk.nexus_title(
                        title,
                        path=f"YUNO NEXUS / SISTEMA DE BAU / {route.upper()}",
                        subtitle=subtitle,
                    )
                ],
                blocks=blocks,
                actions=[*actions, dashboard.route_navigation(MODULE_KEY, route)],
                footer="YUNO NEXUS // ADMINISTRACAO DE BAUS",
                accent_color=uk.NEXUS_VIOLET,
            )
        )
    )


async def render_admin(interaction: discord.Interaction, api: Any) -> None:
    actor = actor_from(interaction)
    summary = await api.chest_admin_summary(interaction.guild_id, actor=actor)
    recent = summary.get("recent") or []
    recent_text = (
        "\n".join(
            f"{row['movement_type']} · {row['quantity']} {row['unit']} · {row['chest_name']}"
            for row in recent
        )
        or "Nenhuma movimentacao registrada."
    )
    data = _shell(
        "SISTEMA DE BAU",
        "Inventario versionado e movimentacoes transacionais.",
        [
            text_display(
                uk.nexus_state(
                    "ESTADO",
                    summary["lifecycle"].upper(),
                    state="success" if summary["lifecycle"] == "active" else "warning",
                )
            ),
            text_display(
                uk.nexus_metrics(
                    ("VERSAO", summary["version"] or "DRAFT"),
                    ("BAUS", summary["chests"]),
                    ("ITENS", summary["items"]),
                    ("MOVIMENTACOES", summary["movements"]),
                    ("SAUDE", summary["health"]),
                )
            ),
            text_display("// ATIVIDADE RECENTE\n\n" + recent_text),
        ],
        [
            action_row(
                button(
                    custom_id=dashboard.central_custom_id(MODULE_KEY, "inventory"),
                    label="INVENTARIO",
                    style=1,
                ),
                button(
                    custom_id=dashboard.central_custom_id(MODULE_KEY, "access"),
                    label="ACESSO",
                    style=2,
                ),
                button(
                    custom_id=dashboard.central_custom_id(MODULE_KEY, "configuration"),
                    label="CONFIGURACAO",
                    style=2,
                ),
            ),
            action_row(
                button(
                    custom_id=dashboard.central_custom_id(MODULE_KEY, "diagnose"),
                    label="DIAGNOSTICO",
                    style=2,
                ),
                button(
                    custom_id=dashboard.central_custom_id(MODULE_KEY, "recover"),
                    label="RECUPERAR",
                    style=2,
                ),
            ),
        ],
        "overview",
    )
    await _replace(interaction, data)


async def inventory(interaction: discord.Interaction, api: Any) -> None:
    draft = await api.chest_catalog_draft(
        interaction.guild_id, actor=actor_from(interaction)
    )
    summary = await api.chest_admin_summary(
        interaction.guild_id, actor=actor_from(interaction)
    )
    chests = draft.get("chests") or []
    items = draft.get("items") or []
    links = draft.get("links") or []
    chest_lines = (
        "\n".join(
            f"**{row['name']}** · {'ATIVO' if row['active'] else 'INATIVO'}"
            for row in chests[:8]
        )
        or "Nenhum bau no draft."
    )
    item_lines = (
        "\n".join(
            f"**{row['name']}** · {row['unit']} · {'ATIVO' if row['active'] else 'INATIVO'}"
            for row in items[:8]
        )
        or "Nenhum item no draft."
    )
    chest_names = {row["id"]: row["name"] for row in chests}
    item_names = {row["id"]: row["name"] for row in items}
    stock_lines = (
        "\n".join(
            f"**{chest_names.get(row['chest_id'], row['chest_id'])}** / "
            f"{item_names.get(row['item_id'], row['item_id'])}: {row['quantity']}"
            for row in summary.get("stock", [])[:12]
        )
        or "Nenhum saldo materializado."
    )
    movement_lines = (
        "\n".join(
            f"{row['movement_type']} · {row['quantity']} {row['unit']} · "
            f"{row['chest_name']} / {row['item_name']}"
            for row in summary.get("recent", [])
        )
        or "Nenhuma movimentacao registrada."
    )
    await _replace(
        interaction,
        _shell(
            "INVENTARIO",
            "Baús, catálogo e vínculos permanecem em draft até a publicação.",
            [
                text_display(
                    uk.nexus_metrics(
                        ("REVISAO", draft["revision"]),
                        ("BAUS", len(chests)),
                        ("ITENS", len(items)),
                        ("VINCULOS", len(links)),
                    )
                ),
                text_display("// BAUS\n\n" + chest_lines),
                text_display("// CATALOGO\n\n" + item_lines),
                text_display("// ESTOQUE PUBLICADO\n\n" + stock_lines),
                text_display("// MOVIMENTACOES RECENTES\n\n" + movement_lines),
            ],
            [
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id(MODULE_KEY, "add_chest"),
                        label="NOVO BAU",
                        style=1,
                    ),
                    button(
                        custom_id=dashboard.central_custom_id(MODULE_KEY, "add_item"),
                        label="NOVO ITEM",
                        style=1,
                    ),
                    button(
                        custom_id=dashboard.central_custom_id(MODULE_KEY, "link_items"),
                        label="GERENCIAR VINCULO",
                        style=2,
                    ),
                ),
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id(
                            MODULE_KEY, "manage_chests"
                        ),
                        label="GERENCIAR BAUS",
                        style=2,
                    ),
                    button(
                        custom_id=dashboard.central_custom_id(
                            MODULE_KEY, "manage_items"
                        ),
                        label="GERENCIAR ITENS",
                        style=2,
                    ),
                ),
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id(MODULE_KEY, "publish"),
                        label="REVISAR E PUBLICAR",
                        style=3,
                    )
                ),
            ],
            "inventory",
        ),
    )


class _CatalogModal(discord.ui.Modal):
    def __init__(
        self,
        api: Any,
        interaction: discord.Interaction,
        *,
        kind: str,
        current: dict[str, Any] | None = None,
    ) -> None:
        current = current or {}
        super().__init__(
            title=("Editar" if current else "Novo")
            + (" bau" if kind == "chest" else " item"),
            timeout=600,
        )
        self.api = api
        self.kind = kind
        self.current = current
        self.name = discord.ui.TextInput(
            label="Nome", default=current.get("name"), min_length=1, max_length=100
        )
        self.unit = discord.ui.TextInput(
            label="Unidade",
            default=current.get("unit", "unidade"),
            min_length=1,
            max_length=40,
            required=kind == "item",
        )
        self.add_item(self.name)
        if kind == "item":
            self.add_item(self.unit)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            draft = await self.api.chest_catalog_draft(
                interaction.guild_id, actor=actor_from(interaction)
            )
            common = {
                "expected_revision": draft["revision"],
                "idempotency_key": f"chest:admin:{self.kind}:{interaction.id}",
                "name": str(self.name.value),
                "active": self.current.get("active", True),
                "position": self.current.get("position", 0),
            }
            if self.kind == "chest":
                if self.current:
                    common["chest_id"] = self.current["id"]
                await self.api.chest_upsert(
                    interaction.guild_id, common, actor=actor_from(interaction)
                )
            else:
                if self.current:
                    common["item_id"] = self.current["id"]
                await self.api.chest_item_upsert(
                    interaction.guild_id,
                    {**common, "unit": str(self.unit.value)},
                    actor=actor_from(interaction),
                )
            await interaction.followup.send("Alteracao salva no draft.", ephemeral=True)
        except Exception:
            await interaction.followup.send(
                "Nao foi possivel salvar o draft. Verifique nomes duplicados e tente novamente.",
                ephemeral=True,
            )


async def add_chest(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.send_modal(_CatalogModal(api, interaction, kind="chest"))


async def add_item(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.send_modal(_CatalogModal(api, interaction, kind="item"))


class CatalogEntryActionsView(discord.ui.View):
    def __init__(self, api: Any, *, kind: str, current: dict[str, Any]) -> None:
        super().__init__(timeout=600)
        self.api = api
        self.kind = kind
        self.current = current

    @discord.ui.button(label="Editar", style=discord.ButtonStyle.primary)
    async def edit(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(
            _CatalogModal(self.api, interaction, kind=self.kind, current=self.current)
        )

    @discord.ui.button(label="Ativar/Desativar", style=discord.ButtonStyle.secondary)
    async def toggle(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        draft = await self.api.chest_catalog_draft(
            interaction.guild_id, actor=actor_from(interaction)
        )
        common = {
            "expected_revision": draft["revision"],
            "idempotency_key": f"chest:toggle:{self.kind}:{interaction.id}",
            "name": self.current["name"],
            "active": not self.current["active"],
            "position": self.current.get("position", 0),
        }
        if self.kind == "chest":
            common["chest_id"] = self.current["id"]
            await self.api.chest_upsert(
                interaction.guild_id, common, actor=actor_from(interaction)
            )
        else:
            common.update({"item_id": self.current["id"], "unit": self.current["unit"]})
            await self.api.chest_item_upsert(
                interaction.guild_id, common, actor=actor_from(interaction)
            )
        await interaction.followup.send("Estado alterado no draft.", ephemeral=True)
        self.stop()


class ManageCatalogView(discord.ui.View):
    def __init__(
        self, api: Any, rows: list[dict[str, Any]], *, kind: str, page: int = 0
    ) -> None:
        super().__init__(timeout=600)
        self.api = api
        self.rows = rows
        self.kind = kind
        self.page = max(0, page)
        pages = max(1, ceil(len(rows) / PAGE_SIZE))
        self.page = min(self.page, pages - 1)
        chunk = rows[self.page * PAGE_SIZE : (self.page + 1) * PAGE_SIZE]
        picker = discord.ui.Select(
            placeholder=f"Selecionar para editar - {self.page + 1}/{pages}",
            options=[
                discord.SelectOption(
                    label=row["name"][:100],
                    value=row["id"],
                    description="Ativo" if row["active"] else "Inativo",
                )
                for row in chunk
            ],
        )
        picker.callback = self._selected  # type: ignore[method-assign]
        self.add_item(picker)
        previous = discord.ui.Button(
            label="Voltar", style=discord.ButtonStyle.secondary, disabled=self.page == 0
        )
        following = discord.ui.Button(
            label="Avancar",
            style=discord.ButtonStyle.secondary,
            disabled=self.page + 1 >= pages,
        )
        previous.callback = self._previous  # type: ignore[method-assign]
        following.callback = self._next  # type: ignore[method-assign]
        self.add_item(previous)
        self.add_item(following)

    async def _selected(self, interaction: discord.Interaction) -> None:
        picker = self.children[0]
        selected = str(picker.values[0])  # type: ignore[attr-defined]
        current = next(row for row in self.rows if row["id"] == selected)
        await interaction.response.edit_message(
            content=f"**{current['name']}** - escolha a alteracao.",
            view=CatalogEntryActionsView(self.api, kind=self.kind, current=current),
        )

    async def _previous(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            view=ManageCatalogView(
                self.api, self.rows, kind=self.kind, page=self.page - 1
            )
        )

    async def _next(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            view=ManageCatalogView(
                self.api, self.rows, kind=self.kind, page=self.page + 1
            )
        )


async def _manage_catalog(
    interaction: discord.Interaction, api: Any, *, kind: str
) -> None:
    draft = await api.chest_catalog_draft(
        interaction.guild_id, actor=actor_from(interaction)
    )
    rows = draft["chests" if kind == "chest" else "items"]
    if not rows:
        await interaction.response.send_message(
            "Nenhum registro disponivel no draft.", ephemeral=True
        )
        return
    await interaction.response.send_message(
        "Selecione o registro.",
        view=ManageCatalogView(api, rows, kind=kind),
        ephemeral=True,
    )


async def manage_chests(interaction: discord.Interaction, api: Any) -> None:
    await _manage_catalog(interaction, api, kind="chest")


async def manage_items(interaction: discord.Interaction, api: Any) -> None:
    await _manage_catalog(interaction, api, kind="item")


class LinkCatalogView(discord.ui.View):
    def __init__(
        self,
        api: Any,
        draft: dict[str, Any],
        *,
        page: int = 0,
        chest_id: str | None = None,
    ) -> None:
        super().__init__(timeout=600)
        self.api = api
        self.draft = draft
        self.page = page
        self.chest_id = chest_id
        self._build()

    def _build(self) -> None:
        rows = self.draft["items"] if self.chest_id else self.draft["chests"]
        rows = [row for row in rows if row.get("active")]
        pages = max(1, ceil(len(rows) / PAGE_SIZE))
        self.page = min(max(0, self.page), pages - 1)
        chunk = rows[self.page * PAGE_SIZE : (self.page + 1) * PAGE_SIZE]
        picker = discord.ui.Select(
            placeholder=("Selecione o item" if self.chest_id else "Selecione o bau")
            + f" · {self.page + 1}/{pages}",
            options=[
                discord.SelectOption(label=row["name"][:100], value=row["id"])
                for row in chunk
            ],
        )
        picker.callback = self._selected  # type: ignore[method-assign]
        self.add_item(picker)
        previous = discord.ui.Button(
            label="Voltar", style=discord.ButtonStyle.secondary, disabled=self.page == 0
        )
        following = discord.ui.Button(
            label="Avancar",
            style=discord.ButtonStyle.secondary,
            disabled=self.page + 1 >= pages,
        )
        previous.callback = self._previous  # type: ignore[method-assign]
        following.callback = self._next  # type: ignore[method-assign]
        self.add_item(previous)
        self.add_item(following)

    async def _selected(self, interaction: discord.Interaction) -> None:
        picker = self.children[0]
        value = str(picker.values[0])  # type: ignore[attr-defined]
        if self.chest_id is None:
            await interaction.response.edit_message(
                content="Agora selecione o item.",
                view=LinkCatalogView(self.api, self.draft, chest_id=value),
            )
            return
        await interaction.response.defer(ephemeral=True)
        current = await self.api.chest_catalog_draft(
            interaction.guild_id, actor=actor_from(interaction)
        )
        existing = next(
            (
                row
                for row in current["links"]
                if row["chest_id"] == self.chest_id and row["item_id"] == value
            ),
            None,
        )
        await self.api.chest_link_upsert(
            interaction.guild_id,
            {
                "chest_id": self.chest_id,
                "item_id": value,
                "active": not existing["active"] if existing else True,
                "expected_revision": current["revision"],
                "idempotency_key": f"chest:link:{interaction.id}",
            },
            actor=actor_from(interaction),
        )
        await interaction.followup.send(
            "Vinculo "
            + ("desativado" if existing and existing["active"] else "ativado")
            + " no draft.",
            ephemeral=True,
        )
        self.stop()

    async def _previous(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            view=LinkCatalogView(
                self.api, self.draft, page=self.page - 1, chest_id=self.chest_id
            )
        )

    async def _next(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            view=LinkCatalogView(
                self.api, self.draft, page=self.page + 1, chest_id=self.chest_id
            )
        )


async def link_items(interaction: discord.Interaction, api: Any) -> None:
    draft = await api.chest_catalog_draft(
        interaction.guild_id, actor=actor_from(interaction)
    )
    if not draft.get("chests") or not draft.get("items"):
        await interaction.response.send_message(
            "Cadastre ao menos um bau e um item antes de vincular.", ephemeral=True
        )
        return
    await interaction.response.send_message(
        "Selecione o bau.", view=LinkCatalogView(api, draft), ephemeral=True
    )


async def _save_config(
    interaction: discord.Interaction, api: Any, changes: dict[str, Any]
) -> dict[str, Any]:
    draft = await api.chest_catalog_draft(
        interaction.guild_id, actor=actor_from(interaction)
    )
    config = {**draft.get("configuration", {}), **changes}
    return await api.chest_save_settings(
        interaction.guild_id,
        {
            "expected_revision": draft["revision"],
            "expected_published_version": draft["base_published_version"],
            "schema_version": draft["schema_version"],
            "data": config,
            "idempotency_key": f"chest:config:{interaction.id}",
        },
        actor=actor_from(interaction),
    )


async def open_access(interaction: discord.Interaction, api: Any) -> None:
    draft = await api.chest_catalog_draft(
        interaction.guild_id, actor=actor_from(interaction)
    )
    roles = draft.get("configuration", {}).get("operator_role_ids") or []
    await _replace(
        interaction,
        _shell(
            "ACESSO",
            "Capabilities e grants publicados pelo Control Plane.",
            [
                text_display(
                    uk.nexus_configuration(
                        ("MEMBROS", "view, deposit, history_own"),
                        ("OPERADORES", "view, deposit, withdraw, history"),
                        ("ADMINISTRACAO", "configure, adjust, audit, recover"),
                    )
                ),
                text_display(
                    uk.nexus_notice(
                        "RESOURCE SCOPE",
                        "Grants por bau suportados",
                        "A API valida scope_id contra o catalogo ativo antes de publicar.",
                    )
                ),
                text_display(
                    "Cargos operadores: "
                    + (", ".join(f"<@&{role}>" for role in roles) or "nenhum")
                ),
            ],
            [
                action_row(
                    role_select(
                        custom_id=dashboard.central_custom_id(
                            MODULE_KEY, "set_operator_roles"
                        ),
                        placeholder="Cargos operadores",
                        min_values=0,
                        max_values=25,
                    )
                )
            ],
            "access",
        ),
    )


async def set_operator_roles(interaction: discord.Interaction, api: Any) -> None:
    await _save_config(interaction, api, {"operator_role_ids": _selected(interaction)})
    await open_access(interaction, api)


async def configure(interaction: discord.Interaction, api: Any) -> None:
    draft = await api.chest_catalog_draft(
        interaction.guild_id, actor=actor_from(interaction)
    )
    config = draft.get("configuration") or {}
    ref = lambda value: f"<#{value}>" if value else "Nao definido"
    await _replace(
        interaction,
        _shell(
            "CONFIGURACAO",
            "Canais, privacidade e textos operacionais do painel.",
            [
                text_display(
                    uk.nexus_configuration(
                        ("PAINEL", ref(config.get("panel_channel_id"))),
                        ("LOGS", ref(config.get("log_channel_id"))),
                        (
                            "SALDOS",
                            "VISIVEIS"
                            if config.get("show_balances_to_members", True)
                            else "RESTRITOS",
                        ),
                        (
                            "HISTORICO PESSOAL",
                            "ATIVO"
                            if config.get("allow_personal_history", True)
                            else "INATIVO",
                        ),
                        (
                            "MOTIVO NA RETIRADA",
                            "OBRIGATORIO"
                            if config.get("withdrawal_reason_required", True)
                            else "OPCIONAL",
                        ),
                    )
                ),
            ],
            [
                action_row(
                    channel_select(
                        custom_id=dashboard.central_custom_id(
                            MODULE_KEY, "set_panel_channel"
                        ),
                        placeholder="Canal do painel",
                        channel_types=[0],
                    )
                ),
                action_row(
                    channel_select(
                        custom_id=dashboard.central_custom_id(
                            MODULE_KEY, "set_log_channel"
                        ),
                        placeholder="Canal de logs",
                        channel_types=[0],
                    )
                ),
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id(
                            MODULE_KEY, "toggle_balances"
                        ),
                        label="ALTERNAR SALDOS",
                        style=2,
                    ),
                    button(
                        custom_id=dashboard.central_custom_id(
                            MODULE_KEY, "toggle_history"
                        ),
                        label="ALTERNAR HISTORICO",
                        style=2,
                    ),
                    button(
                        custom_id=dashboard.central_custom_id(
                            MODULE_KEY, "toggle_reason"
                        ),
                        label="ALTERNAR MOTIVO",
                        style=2,
                    ),
                ),
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id(MODULE_KEY, "edit_texts"),
                        label="TEXTOS DO PAINEL",
                        style=2,
                    ),
                    button(
                        custom_id=dashboard.central_custom_id(MODULE_KEY, "publish"),
                        label="PUBLICAR",
                        style=3,
                    ),
                ),
            ],
            "configuration",
        ),
    )


async def set_panel_channel(interaction: discord.Interaction, api: Any) -> None:
    values = _selected(interaction)
    await _save_config(
        interaction, api, {"panel_channel_id": values[0] if values else ""}
    )
    await configure(interaction, api)


async def set_log_channel(interaction: discord.Interaction, api: Any) -> None:
    values = _selected(interaction)
    await _save_config(
        interaction, api, {"log_channel_id": values[0] if values else ""}
    )
    await configure(interaction, api)


async def _toggle(interaction: discord.Interaction, api: Any, key: str) -> None:
    draft = await api.chest_catalog_draft(
        interaction.guild_id, actor=actor_from(interaction)
    )
    current = bool(draft.get("configuration", {}).get(key, True))
    await _save_config(interaction, api, {key: not current})
    await configure(interaction, api)


async def toggle_balances(interaction: discord.Interaction, api: Any) -> None:
    await _toggle(interaction, api, "show_balances_to_members")


async def toggle_history(interaction: discord.Interaction, api: Any) -> None:
    await _toggle(interaction, api, "allow_personal_history")


async def toggle_reason(interaction: discord.Interaction, api: Any) -> None:
    await _toggle(interaction, api, "withdrawal_reason_required")


class TextsModal(discord.ui.Modal):
    def __init__(self, api: Any, config: dict[str, Any]) -> None:
        super().__init__(title="Textos do painel", timeout=600)
        self.api = api
        self.title_input = discord.ui.TextInput(
            label="Titulo",
            default=config.get("panel_title") or "Sistema de Bau",
            max_length=80,
        )
        self.description_input = discord.ui.TextInput(
            label="Descricao",
            default=config.get("panel_description")
            or "Consulte o estoque e registre movimentacoes.",
            max_length=300,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.title_input)
        self.add_item(self.description_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await _save_config(
            interaction,
            self.api,
            {
                "panel_title": str(self.title_input.value),
                "panel_description": str(self.description_input.value),
            },
        )
        await interaction.followup.send("Textos salvos no draft.", ephemeral=True)


async def edit_texts(interaction: discord.Interaction, api: Any) -> None:
    draft = await api.chest_catalog_draft(
        interaction.guild_id, actor=actor_from(interaction)
    )
    await interaction.response.send_modal(
        TextsModal(api, draft.get("configuration") or {})
    )


def _grants(config: dict[str, Any]) -> list[dict[str, Any]]:
    grants = [
        {
            "capability": capability,
            "subject_type": "everyone",
            "subject_id": "",
            "scope_type": "guild",
            "scope_id": "",
            "constraints": {},
        }
        for capability in ("chest.view", "chest.deposit", "chest.history_own")
    ]
    grants.extend(
        {
            "capability": capability,
            "subject_type": "role",
            "subject_id": str(role),
            "scope_type": "guild",
            "scope_id": "",
            "constraints": {},
        }
        for role in config.get("operator_role_ids") or []
        for capability in (
            "chest.view",
            "chest.deposit",
            "chest.withdraw",
            "chest.history",
        )
    )
    return grants


async def publish_catalog(interaction: discord.Interaction, api: Any) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    try:
        draft = await api.chest_catalog_draft(
            interaction.guild_id, actor=actor_from(interaction)
        )
        await api.chest_publish(
            interaction.guild_id,
            {
                "expected_revision": draft["revision"],
                "expected_published_version": draft["base_published_version"],
                "grants": _grants(draft.get("configuration") or {}),
                "idempotency_key": f"chest:publish:{interaction.id}",
            },
            actor=actor_from(interaction),
        )
        instance = await api.module_instance(interaction.guild_id, MODULE_KEY)
        if instance["lifecycle"] != "active":
            await api.update_lifecycle(
                interaction.guild_id,
                MODULE_KEY,
                lifecycle="active",
                expected_lifecycle=instance["lifecycle"],
                actor=actor_from(interaction),
                reason="chest_catalog_published",
            )
        await interaction.followup.send(
            "Catalogo publicado e painel enfileirado.", ephemeral=True
        )
    except Exception:
        await interaction.followup.send(
            "Publicacao bloqueada. Revise canais, catalogo, vinculos e saldos.",
            ephemeral=True,
        )


async def diagnose(interaction: discord.Interaction, api: Any) -> None:
    checks = await api.diagnostics(interaction.guild_id, MODULE_KEY)
    lines = "\n\n".join(
        f"**{row['status']} · {row['code']}**\n{row['summary']}" for row in checks
    )
    await _replace(
        interaction,
        _shell(
            "DIAGNOSTICO",
            "Configuracao, painel, saldos e runtime.",
            [text_display(lines or "Nenhum check retornado.")],
            [
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id(MODULE_KEY, "recover"),
                        label="RECUPERAR",
                        style=2,
                    ),
                    button(
                        custom_id=dashboard.central_custom_id(MODULE_KEY, "audit"),
                        label="AUDITORIA",
                        style=2,
                    ),
                )
            ],
            "diagnostic",
        ),
    )


async def audit_log(interaction: discord.Interaction, api: Any) -> None:
    entries = await api.audit(interaction.guild_id, module_key=MODULE_KEY)
    lines = (
        "\n\n".join(
            f"**{row['action']}**\n{row.get('resource_type') or 'module'} · "
            f"{row.get('resource_id') or '-'} · ator {row.get('actor_id') or 'system'}"
            for row in entries[:12]
        )
        or "Nenhuma entrada de auditoria registrada."
    )
    await _replace(
        interaction,
        _shell(
            "AUDITORIA",
            "Acoes administrativas e operacionais registradas pelo Control Plane.",
            [text_display(lines)],
            [],
            "diagnostic",
        ),
    )


async def recover(interaction: discord.Interaction, api: Any) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    try:
        actor = actor_from(interaction)
        await api.chest_recover(
            interaction.guild_id,
            {
                "action": "create_missing_balances",
                "idempotency_key": f"chest:recover:{interaction.id}:balances",
            },
            actor=actor,
        )
        await api.chest_recover(
            interaction.guild_id,
            {
                "action": "reconcile_panel",
                "idempotency_key": f"chest:recover:{interaction.id}:panel",
            },
            actor=actor,
        )
        await interaction.followup.send(
            "Saldos reconciliados e recuperacao do painel enfileirada.", ephemeral=True
        )
    except Exception:
        await interaction.followup.send(
            "Recuperacao incompleta. Consulte o diagnostico.", ephemeral=True
        )


# ---------------------------------------------------------------------------
# Central administrativa por bau
# ---------------------------------------------------------------------------

_admin_sessions: dict[tuple[int, int, int, int], str] = {}


def _admin_key(interaction: discord.Interaction) -> tuple[int, int, int, int]:
    return (
        int(interaction.guild_id or 0),
        int(getattr(interaction.user, "id", 0) or 0),
        int(interaction.channel_id or 0),
        int(getattr(interaction.message, "id", 0) or 0),
    )


def _mention_roles(values: list[str] | None) -> str:
    roles = list(values or [])
    if not roles:
        return "Ninguem definido"
    return ", ".join("@Membros" if role == "everyone" else f"<@&{role}>" for role in roles)


def _chest(draft: dict[str, Any], chest_id: str | None) -> dict[str, Any] | None:
    if not chest_id:
        return None
    return next((row for row in draft.get("chests") or [] if row["id"] == chest_id), None)


def _stock_for_chest(draft: dict[str, Any], summary: dict[str, Any], chest_id: str) -> tuple[int, str]:
    item_names = {row["id"]: row["name"] for row in draft.get("items") or []}
    rows = [row for row in summary.get("stock") or [] if row.get("chest_id") == chest_id]
    total = sum(Decimal(str(row.get("quantity") or 0)) for row in rows)
    return len(rows), f"{total:f}".rstrip("0").rstrip(".") or "0"


def _chest_detail_payload(draft: dict[str, Any], summary: dict[str, Any], chest_id: str) -> dict[str, Any]:
    row = _chest(draft, chest_id)
    if row is None:
        return _shell("SEUS BAUS", "Escolha um bau para continuar.", [], [], "overview")
    item_count, total = _stock_for_chest(draft, summary, chest_id)
    status = "Ativo" if row.get("active") else "Inativo"
    panel = f"<#{row['panel_channel_id']}>" if row.get("panel_channel_id") else "Nao definido"
    logs = f"<#{row['log_channel_id']}>" if row.get("log_channel_id") else "Nao definido"
    panel_row = next((item for item in summary.get("panels") or [] if item.get("chest_id") == chest_id), None)
    panel_status = "Funcionando" if panel_row and panel_row.get("state") == "published" else "Painel nao encontrado"
    return _shell(
        row["name"].upper(),
        row.get("description") or "Configure este bau e publique o painel operacional.",
        [
            text_display(uk.nexus_state("STATUS", status, state="success" if row.get("active") else "warning")),
            text_display(uk.nexus_configuration(("PAINEL", panel), ("LOGS", logs), ("ITENS", item_count), ("ESTOQUE", f"{total} unidades"))),
            text_display(f"Painel {panel_status}."),
            text_display("Escolha uma area para continuar. As alteracoes ficam pendentes ate a publicacao."),
        ],
        [
            action_row(
                button(custom_id=dashboard.central_custom_id(MODULE_KEY, "chest_items"), label="ITENS", style=1),
                button(custom_id=dashboard.central_custom_id(MODULE_KEY, "chest_stock"), label="ESTOQUE", style=2),
                button(custom_id=dashboard.central_custom_id(MODULE_KEY, "chest_access"), label="ACESSO", style=2),
            ),
            action_row(
                button(custom_id=dashboard.central_custom_id(MODULE_KEY, "chest_settings"), label="CONFIGURACOES", style=2),
                button(custom_id=dashboard.central_custom_id(MODULE_KEY, "edit_chest"), label="EDITAR", style=2),
                button(custom_id=dashboard.central_custom_id(MODULE_KEY, "publish_chest"), label="PUBLICAR BAU", style=3),
            ),
            action_row(button(custom_id=dashboard.central_custom_id(MODULE_KEY, "recover_chest"), label="ATUALIZAR PAINEL", style=2)),
        ],
        "chest",
    )


async def render_admin(interaction: discord.Interaction, api: Any) -> None:
    draft = await api.chest_catalog_draft(interaction.guild_id, actor=actor_from(interaction))
    rows = list(draft.get("chests") or [])
    options = [
        {"label": row["name"][:100], "value": row["id"], "description": "Ativo" if row.get("active") else "Inativo"}
        for row in rows[:PAGE_SIZE]
    ]
    controls = []
    if options:
        controls.append(action_row(string_select(
            custom_id=dashboard.central_custom_id(MODULE_KEY, "select_chest"),
            options=options,
            placeholder="Selecionar bau",
        )))
    controls.append(action_row(button(custom_id=dashboard.central_custom_id(MODULE_KEY, "add_chest"), label="+ CRIAR BAU", style=1)))
    await _replace(
        interaction,
        _shell(
            "SEUS BAUS",
            "Gerencie os estoques da organizacao.",
            [text_display("Escolha um bau para configurar painel, logs, acesso, itens e publicacao."), text_display(f"{len(rows)} bau(s) cadastrado(s)." if rows else "Nenhum bau cadastrado ainda.")],
            controls,
            "overview",
        ),
    )


inventory = render_admin


async def select_chest(interaction: discord.Interaction, api: Any) -> None:
    values = _selected(interaction)
    if not values:
        await _replace(interaction, _shell("SEUS BAUS", "Selecao invalida.", [], [], "overview"))
        return
    _admin_sessions[_admin_key(interaction)] = values[0]
    draft = await api.chest_catalog_draft(interaction.guild_id, actor=actor_from(interaction))
    summary = await api.chest_admin_summary(interaction.guild_id, actor=actor_from(interaction))
    await _replace(interaction, _chest_detail_payload(draft, summary, values[0]))


async def chest_detail(interaction: discord.Interaction, api: Any) -> None:
    chest_id = _admin_sessions.get(_admin_key(interaction))
    if not chest_id:
        return await render_admin(interaction, api)
    draft = await api.chest_catalog_draft(interaction.guild_id, actor=actor_from(interaction))
    summary = await api.chest_admin_summary(interaction.guild_id, actor=actor_from(interaction))
    await _replace(interaction, _chest_detail_payload(draft, summary, chest_id))


async def _selected_chest_data(interaction: discord.Interaction, api: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    chest_id = _admin_sessions.get(_admin_key(interaction))
    if not chest_id:
        return None
    draft = await api.chest_catalog_draft(interaction.guild_id, actor=actor_from(interaction))
    row = _chest(draft, chest_id)
    if row is None:
        return None
    summary = await api.chest_admin_summary(interaction.guild_id, actor=actor_from(interaction))
    return draft, summary, row


async def chest_stock(interaction: discord.Interaction, api: Any) -> None:
    selected = await _selected_chest_data(interaction, api)
    if selected is None:
        return await render_admin(interaction, api)
    draft, summary, row = selected
    item_names = {item["id"]: item["name"] for item in draft.get("items") or []}
    units = {item["id"]: item.get("unit", "unidade") for item in draft.get("items") or []}
    lines = [
        f"**{item_names.get(stock['item_id'], 'Item')}** — {stock['quantity']} {units.get(stock['item_id'], 'unidade')}"
        for stock in summary.get("stock") or []
        if stock.get("chest_id") == row["id"]
    ]
    await _replace(interaction, _shell(f"ESTOQUE · {row['name']}", "Saldo atual deste bau.", [text_display("\n".join(lines) or "Nenhum item com saldo materializado.")], [action_row(button(custom_id=dashboard.central_custom_id(MODULE_KEY, "chest_detail"), label="VOLTAR", style=2))], "overview"))


async def chest_items(interaction: discord.Interaction, api: Any) -> None:
    selected = await _selected_chest_data(interaction, api)
    if selected is None:
        return await render_admin(interaction, api)
    draft, _, row = selected
    active_links = {link["item_id"] for link in draft.get("links") or [] if link["chest_id"] == row["id"] and link.get("active")}
    options = [
        {"label": item["name"][:100], "value": item["id"], "description": "Adicionado" if item["id"] in active_links else "Disponivel"}
        for item in draft.get("items") or []
        if item.get("active")
    ][:PAGE_SIZE]
    actions = [action_row(button(custom_id=dashboard.central_custom_id(MODULE_KEY, "add_item"), label="ADICIONAR ITEM", style=1))]
    if options:
        actions.insert(0, action_row(string_select(custom_id=dashboard.central_custom_id(MODULE_KEY, "toggle_chest_item"), options=options, placeholder="Adicionar ou remover item")))
    actions.append(action_row(button(custom_id=dashboard.central_custom_id(MODULE_KEY, "chest_detail"), label="VOLTAR", style=2)))
    await _replace(interaction, _shell(f"ITENS · {row['name']}", "Escolha quais itens pertencem a este bau.", [text_display("\n".join(f"**{item['name']}** — {'Adicionado' if item['id'] in active_links else 'Disponivel'}" for item in draft.get("items") or [] if item.get("active")) or "Cadastre um item para continuar.")], actions, "overview"))


async def toggle_chest_item(interaction: discord.Interaction, api: Any) -> None:
    selected = await _selected_chest_data(interaction, api)
    item_values = _selected(interaction)
    if selected is None or not item_values:
        return await chest_items(interaction, api)
    draft, _, row = selected
    item_id = item_values[0]
    current = next((link for link in draft.get("links") or [] if link["chest_id"] == row["id"] and link["item_id"] == item_id), None)
    await api.chest_link_upsert(interaction.guild_id, {"chest_id": row["id"], "item_id": item_id, "active": not bool(current and current.get("active")), "expected_revision": draft["revision"], "idempotency_key": f"chest:link:{interaction.id}"}, actor=actor_from(interaction))
    await chest_items(interaction, api)


async def _update_chest(interaction: discord.Interaction, api: Any, changes: dict[str, Any]) -> dict[str, Any]:
    draft = await api.chest_catalog_draft(interaction.guild_id, actor=actor_from(interaction))
    chest_id = _admin_sessions.get(_admin_key(interaction))
    row = _chest(draft, chest_id)
    if row is None:
        raise ValueError("Bau nao selecionado.")
    payload_data = {
        key: row.get(key)
        for key in ("description", "panel_channel_id", "log_channel_id", "show_balances_to_members", "allow_personal_history", "withdrawal_reason_required", "view_role_ids", "deposit_role_ids", "withdraw_role_ids", "admin_role_ids")
    }
    payload_data.update(changes)
    return await api.chest_upsert(interaction.guild_id, {"chest_id": row["id"], "name": row["name"], "active": row.get("active", True), "position": row.get("position", 0), **payload_data, "expected_revision": draft["revision"], "idempotency_key": f"chest:update:{interaction.id}"}, actor=actor_from(interaction))


async def chest_settings(interaction: discord.Interaction, api: Any) -> None:
    selected = await _selected_chest_data(interaction, api)
    if selected is None:
        return await render_admin(interaction, api)
    _, _, row = selected
    ref = lambda value: f"<#{value}>" if value else "Nao definido"
    await _replace(interaction, _shell(f"CONFIGURACOES · {row['name']}", "Escolha onde este bau funciona e como ele se comporta.", [text_display(uk.nexus_configuration(("PAINEL", ref(row.get("panel_channel_id"))), ("LOGS", ref(row.get("log_channel_id"))), ("SALDOS", "Visiveis" if row.get("show_balances_to_members", True) else "Restritos"), ("HISTORICO", "Ativo" if row.get("allow_personal_history", True) else "Inativo"), ("MOTIVO NA RETIRADA", "Obrigatorio" if row.get("withdrawal_reason_required", True) else "Opcional")))], [action_row(channel_select(custom_id=dashboard.central_custom_id(MODULE_KEY, "set_chest_panel_channel"), placeholder="Selecionar canal do painel", channel_types=[0])), action_row(channel_select(custom_id=dashboard.central_custom_id(MODULE_KEY, "set_chest_log_channel"), placeholder="Selecionar canal de logs", channel_types=[0])), action_row(button(custom_id=dashboard.central_custom_id(MODULE_KEY, "toggle_chest_balances"), label="ALTERNAR SALDOS", style=2), button(custom_id=dashboard.central_custom_id(MODULE_KEY, "toggle_chest_history"), label="ALTERNAR HISTORICO", style=2), button(custom_id=dashboard.central_custom_id(MODULE_KEY, "toggle_chest_reason"), label="ALTERNAR MOTIVO", style=2)), action_row(button(custom_id=dashboard.central_custom_id(MODULE_KEY, "chest_detail"), label="VOLTAR", style=2))], "overview"))


async def set_chest_panel_channel(interaction: discord.Interaction, api: Any) -> None:
    values = _selected(interaction)
    await _update_chest(interaction, api, {"panel_channel_id": values[0] if values else None})
    await chest_settings(interaction, api)


async def set_chest_log_channel(interaction: discord.Interaction, api: Any) -> None:
    values = _selected(interaction)
    await _update_chest(interaction, api, {"log_channel_id": values[0] if values else None})
    await chest_settings(interaction, api)


async def _toggle_chest_setting(interaction: discord.Interaction, api: Any, key: str) -> None:
    selected = await _selected_chest_data(interaction, api)
    if selected is None:
        return await render_admin(interaction, api)
    await _update_chest(interaction, api, {key: not bool(selected[2].get(key, True))})
    await chest_settings(interaction, api)


async def toggle_chest_balances(interaction: discord.Interaction, api: Any) -> None:
    await _toggle_chest_setting(interaction, api, "show_balances_to_members")


async def toggle_chest_history(interaction: discord.Interaction, api: Any) -> None:
    await _toggle_chest_setting(interaction, api, "allow_personal_history")


async def toggle_chest_reason(interaction: discord.Interaction, api: Any) -> None:
    await _toggle_chest_setting(interaction, api, "withdrawal_reason_required")


async def chest_access(interaction: discord.Interaction, api: Any) -> None:
    selected = await _selected_chest_data(interaction, api)
    if selected is None:
        return await render_admin(interaction, api)
    _, _, row = selected
    blocks = [text_display(uk.nexus_configuration(("PODE VISUALIZAR", _mention_roles(row.get("view_role_ids"))), ("PODE DEPOSITAR", _mention_roles(row.get("deposit_role_ids"))), ("PODE RETIRAR", _mention_roles(row.get("withdraw_role_ids"))), ("PODE ADMINISTRAR", _mention_roles(row.get("admin_role_ids"))))) ]
    actions = [
        action_row(role_select(custom_id=dashboard.central_custom_id(MODULE_KEY, "set_chest_view_roles"), placeholder="Quem pode visualizar?", min_values=0, max_values=25)),
        action_row(role_select(custom_id=dashboard.central_custom_id(MODULE_KEY, "set_chest_deposit_roles"), placeholder="Quem pode depositar?", min_values=0, max_values=25)),
        action_row(role_select(custom_id=dashboard.central_custom_id(MODULE_KEY, "set_chest_withdraw_roles"), placeholder="Quem pode retirar?", min_values=0, max_values=25)),
        action_row(role_select(custom_id=dashboard.central_custom_id(MODULE_KEY, "set_chest_admin_roles"), placeholder="Quem pode administrar?", min_values=0, max_values=25)),
        action_row(button(custom_id=dashboard.central_custom_id(MODULE_KEY, "chest_detail"), label="VOLTAR", style=2)),
    ]
    await _replace(interaction, _shell(f"ACESSO · {row['name']}", "Defina quem pode usar este bau.", blocks, actions, "overview"))


async def _set_chest_roles(interaction: discord.Interaction, api: Any, key: str) -> None:
    await _update_chest(interaction, api, {key: _selected(interaction)})
    await chest_access(interaction, api)


async def set_chest_view_roles(interaction: discord.Interaction, api: Any) -> None:
    await _set_chest_roles(interaction, api, "view_role_ids")


async def set_chest_deposit_roles(interaction: discord.Interaction, api: Any) -> None:
    await _set_chest_roles(interaction, api, "deposit_role_ids")


async def set_chest_withdraw_roles(interaction: discord.Interaction, api: Any) -> None:
    await _set_chest_roles(interaction, api, "withdraw_role_ids")


async def set_chest_admin_roles(interaction: discord.Interaction, api: Any) -> None:
    await _set_chest_roles(interaction, api, "admin_role_ids")


class _ChestIdentityModal(discord.ui.Modal):
    def __init__(self, api: Any, interaction: discord.Interaction, current: dict[str, Any] | None = None) -> None:
        current = current or {}
        super().__init__(title="Editar bau" if current else "Criar bau", timeout=600)
        self.api = api
        self.current = current
        self.origin_channel_id = interaction.channel_id
        self.origin_message_id = getattr(interaction.message, "id", None)
        self.name = discord.ui.TextInput(label="Nome do bau", default=current.get("name"), min_length=1, max_length=100)
        self.description = discord.ui.TextInput(label="Descricao opcional", default=current.get("description") or "", required=False, max_length=300, style=discord.TextStyle.paragraph)
        self.add_item(self.name)
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        draft = await self.api.chest_catalog_draft(interaction.guild_id, actor=actor_from(interaction))
        payload_data = {
            "name": str(self.name.value),
            "description": str(self.description.value or ""),
            "active": self.current.get("active", True),
            "position": self.current.get("position", 0),
            "expected_revision": draft["revision"],
            "idempotency_key": f"chest:identity:{interaction.id}",
        }
        for key in ("chest_id", "panel_channel_id", "log_channel_id", "show_balances_to_members", "allow_personal_history", "withdrawal_reason_required", "view_role_ids", "deposit_role_ids", "withdraw_role_ids", "admin_role_ids"):
            if key in self.current:
                payload_data[key] = self.current[key]
        result = await self.api.chest_upsert(interaction.guild_id, payload_data, actor=actor_from(interaction))
        if self.origin_message_id:
            key = (int(interaction.guild_id or 0), int(interaction.user.id), int(self.origin_channel_id or 0), int(self.origin_message_id))
            _admin_sessions[key] = result["id"]
            latest = await self.api.chest_catalog_draft(interaction.guild_id, actor=actor_from(interaction))
            summary = await self.api.chest_admin_summary(interaction.guild_id, actor=actor_from(interaction))
            await dashboard.edit_central_message(interaction.client, self.origin_channel_id, self.origin_message_id, _chest_detail_payload(latest, summary, result["id"]))
        await interaction.followup.send("Bau salvo. Agora configure canais, acesso e itens antes de publicar.", ephemeral=True)


async def add_chest(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.send_modal(_ChestIdentityModal(api, interaction))


async def edit_chest(interaction: discord.Interaction, api: Any) -> None:
    selected = await _selected_chest_data(interaction, api)
    if selected is None:
        return await render_admin(interaction, api)
    await interaction.response.send_modal(_ChestIdentityModal(api, interaction, selected[2]))


def _grants_for_draft(draft: dict[str, Any]) -> list[dict[str, Any]]:
    grants: list[dict[str, Any]] = []
    mapping = {
        "view_role_ids": ("chest.view",),
        "deposit_role_ids": ("chest.deposit",),
        "withdraw_role_ids": ("chest.withdraw",),
        "admin_role_ids": ("chest.view", "chest.deposit", "chest.withdraw", "chest.history"),
    }
    for row in draft.get("chests") or []:
        if not row.get("active"):
            continue
        for field, capabilities in mapping.items():
            for role in row.get(field) or []:
                subject_type = "everyone" if role == "everyone" else "role"
                subject_id = "" if role == "everyone" else str(role)
                for capability in capabilities:
                    grants.append({"capability": capability, "subject_type": subject_type, "subject_id": subject_id, "scope_type": "resource", "scope_id": row["id"], "constraints": {}})
    return grants


async def publish_chest(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.defer(ephemeral=True)
    try:
        draft = await api.chest_catalog_draft(interaction.guild_id, actor=actor_from(interaction))
        await api.chest_publish(interaction.guild_id, {"expected_revision": draft["revision"], "expected_published_version": draft["base_published_version"], "grants": _grants_for_draft(draft), "idempotency_key": f"chest:publish:{interaction.id}"}, actor=actor_from(interaction))
        await interaction.followup.send("Bau publicado. O painel fixo sera criado ou atualizado no canal escolhido.", ephemeral=True)
    except Exception:
        await interaction.followup.send("Nao foi possivel publicar. Revise painel, logs, acesso e itens deste bau.", ephemeral=True)


async def recover_chest(interaction: discord.Interaction, api: Any) -> None:
    chest_id = _admin_sessions.get(_admin_key(interaction))
    if not chest_id:
        return await render_admin(interaction, api)
    await interaction.response.defer(ephemeral=True)
    try:
        actor = actor_from(interaction)
        await api.chest_recover(interaction.guild_id, {"action": "create_missing_balances", "chest_id": chest_id, "idempotency_key": f"chest:recover:{interaction.id}:balances"}, actor=actor)
        await api.chest_recover(interaction.guild_id, {"action": "reconcile_panel", "chest_id": chest_id, "idempotency_key": f"chest:recover:{interaction.id}:panel"}, actor=actor)
        await interaction.followup.send("Painel deste bau enviado para recuperacao.", ephemeral=True)
    except Exception:
        await interaction.followup.send("Nao foi possivel recuperar este bau. Revise a configuracao publicada.", ephemeral=True)


class _ChestItemModal(discord.ui.Modal):
    def __init__(self, api: Any, interaction: discord.Interaction) -> None:
        super().__init__(title="Adicionar item ao bau", timeout=600)
        self.api = api
        self.origin_channel_id = interaction.channel_id
        self.origin_message_id = getattr(interaction.message, "id", None)
        self.name = discord.ui.TextInput(label="Nome do item", min_length=1, max_length=100)
        self.unit = discord.ui.TextInput(label="Unidade", default="unidade", min_length=1, max_length=40)
        self.add_item(self.name)
        self.add_item(self.unit)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        origin_key = (
            int(interaction.guild_id or 0),
            int(interaction.user.id),
            int(self.origin_channel_id or 0),
            int(self.origin_message_id or 0),
        )
        chest_id = _admin_sessions.get(origin_key)
        if not chest_id:
            await interaction.followup.send("Selecione um bau antes de adicionar itens.", ephemeral=True)
            return
        actor = actor_from(interaction)
        draft = await self.api.chest_catalog_draft(interaction.guild_id, actor=actor)
        item = await self.api.chest_item_upsert(
            interaction.guild_id,
            {
                "name": str(self.name.value),
                "unit": str(self.unit.value),
                "active": True,
                "position": len(draft.get("items") or []),
                "expected_revision": draft["revision"],
                "idempotency_key": f"chest:item:{interaction.id}",
            },
            actor=actor,
        )
        latest = await self.api.chest_catalog_draft(interaction.guild_id, actor=actor)
        await self.api.chest_link_upsert(
            interaction.guild_id,
            {
                "chest_id": chest_id,
                "item_id": item["id"],
                "active": True,
                "expected_revision": latest["revision"],
                "idempotency_key": f"chest:item-link:{interaction.id}",
            },
            actor=actor,
        )
        summary = await self.api.chest_admin_summary(interaction.guild_id, actor=actor)
        if self.origin_message_id:
            final_draft = await self.api.chest_catalog_draft(interaction.guild_id, actor=actor)
            await dashboard.edit_central_message(
                interaction.client,
                self.origin_channel_id,
                self.origin_message_id,
                _chest_detail_payload(final_draft, summary, chest_id),
            )
        await interaction.followup.send("Item adicionado a este bau. Publique quando terminar a configuracao.", ephemeral=True)


async def add_item(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.send_modal(_ChestItemModal(api, interaction))
