from __future__ import annotations

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
                        path=f"MODULES / CHEST / {route.upper()}",
                        subtitle=subtitle,
                    )
                ],
                blocks=blocks,
                actions=[*actions, dashboard.route_navigation(MODULE_KEY, route)],
                footer="NEXUS CORE // CHEST ADMIN",
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
