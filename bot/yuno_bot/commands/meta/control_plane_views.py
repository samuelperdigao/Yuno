from __future__ import annotations

from typing import Any

import discord
import httpx
from pydantic import ValidationError

from yuno_bot.api_client import ControlPlaneConflict, YunoAPI
from yuno_bot.commands.meta.control_plane import (
    SCHEMA_VERSION,
    build_panel_embed,
    diagnose_state,
    parse_config,
    publish_draft,
    seed_from_legacy,
    validate_discord,
)
from yuno_bot.commands.meta.views import MetaDefinitionBuilderView
from yuno_bot.control_plane import is_control_plane_admin


async def _send(
    interaction: discord.Interaction,
    content: str | None = None,
    *,
    embed: discord.Embed | None = None,
    embeds: list[discord.Embed] | None = None,
    view: discord.ui.View | None = None,
    wait: bool = False,
):
    kwargs: dict[str, Any] = {"ephemeral": True}
    if embed is not None:
        kwargs["embed"] = embed
    if embeds is not None:
        kwargs["embeds"] = embeds
    if view is not None:
        kwargs["view"] = view
    if interaction.response.is_done():
        return await interaction.followup.send(content, wait=wait, **kwargs)
    await interaction.response.send_message(content, **kwargs)
    return await interaction.original_response() if wait else None


async def _seed_if_needed(
    interaction: discord.Interaction,
    api: YunoAPI,
    state: dict[str, Any],
    guild_config: dict[str, Any],
) -> dict[str, Any]:
    if state.get("draft_revision") or state.get("draft_data"):
        return state
    seeded = seed_from_legacy(guild_config)
    return await api.save_module_config_draft(
        interaction.guild.id,
        "meta",
        actor_id=interaction.user.id,
        expected_revision=0,
        schema_version=SCHEMA_VERSION,
        draft_data=seeded,
    )


def _editor_embed(data: dict[str, Any], revision: int) -> discord.Embed:
    config = parse_config(data)
    items = "\n".join(
        f"• **{item.name}** — `{item.quantity}`" for item in config.default_items
    ) or "_Nenhum item definido_"
    embed = discord.Embed(
        title="⚙️ Configuração de Metas",
        description=(
            "Edite os campos abaixo e clique em **Salvar rascunho**. "
            "Salvar não altera o painel público."
        ),
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="Canais",
        value=(
            f"Painel: {f'<#{config.panel_channel_id}>' if config.panel_channel_id else '_não definido_'}\n"
            f"Resultado: {f'<#{config.result_channel_id}>' if config.result_channel_id else '_não definido_'}"
        ),
        inline=False,
    )
    embed.add_field(
        name="Cargo autorizado",
        value=f"<@&{config.allowed_role_id}>" if config.allowed_role_id else "_não definido_",
        inline=False,
    )
    embed.add_field(name=f"Itens padrão ({len(config.default_items)}/20)", value=items[:1024], inline=False)
    embed.add_field(
        name="Painel",
        value=f"**{config.panel.title}**\n{config.panel.description[:500]}\nCor: `{config.panel.color}`",
        inline=False,
    )
    embed.set_footer(text=f"Rascunho atual: revisão {revision}")
    return embed


class MetaConfigEditorView(discord.ui.View):
    def __init__(
        self,
        api: YunoAPI,
        *,
        user_id: int,
        guild_name: str,
        state: dict[str, Any],
    ) -> None:
        super().__init__(timeout=900)
        self.api = api
        self.user_id = user_id
        self.guild_name = guild_name
        self.revision = int(state.get("draft_revision", 0))
        self.data = parse_config(state.get("draft_data") or {}).model_dump(mode="json")
        self.message: discord.WebhookMessage | None = None
        self.add_item(PanelChannelSelect())
        self.add_item(ResultChannelSelect())
        self.add_item(AllowedRoleSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "Esta sessão administrativa pertence a outro usuário.", ephemeral=True
        )
        return False

    def embed(self) -> discord.Embed:
        return _editor_embed(self.data, self.revision)

    async def refresh(self) -> None:
        if self.message:
            await self.message.edit(embed=self.embed(), view=self)

    @discord.ui.button(label="Editar itens", emoji="🧾", style=discord.ButtonStyle.secondary, row=3)
    async def edit_items(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async def receive_items(child_interaction: discord.Interaction, items: list[dict]) -> None:
            self.data["default_items"] = items
            await self.refresh()
            await child_interaction.followup.send(
                "Itens atualizados na sessão. Clique em **Salvar rascunho** para persistir.",
                ephemeral=True,
            )

        builder = MetaDefinitionBuilderView(
            self.api,
            {},
            user_id=self.user_id,
            guild_name=self.guild_name,
            items=list(self.data.get("default_items") or []),
            on_submit=receive_items,
            submit_label="Usar estes itens",
        )
        await interaction.response.send_message(embed=builder.build_embed(), view=builder, ephemeral=True)
        builder.message = await interaction.original_response()

    @discord.ui.button(label="Editar aparência", emoji="🎨", style=discord.ButtonStyle.secondary, row=3)
    async def edit_appearance(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(MetaAppearanceModal(self))

    @discord.ui.button(label="Salvar rascunho", emoji="💾", style=discord.ButtonStyle.success, row=3)
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Servidor indisponível.", ephemeral=True)
            return
        try:
            payload = parse_config(self.data).model_dump(mode="json")
        except ValidationError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            state = await self.api.save_module_config_draft(
                interaction.guild.id,
                "meta",
                actor_id=interaction.user.id,
                expected_revision=self.revision,
                schema_version=SCHEMA_VERSION,
                draft_data=payload,
            )
        except ControlPlaneConflict as exc:
            await interaction.followup.send(
                f"Conflito de edição: a revisão atual é {exc.current_revision}. Reabra o módulo.",
                ephemeral=True,
            )
            return
        except httpx.HTTPError:
            await interaction.followup.send("Não consegui salvar o rascunho.", ephemeral=True)
            return
        self.revision = int(state["draft_revision"])
        self.data = state["draft_data"]
        await self.refresh()
        await interaction.followup.send(
            f"Rascunho salvo na revisão {self.revision}. O Runtime não foi alterado.", ephemeral=True
        )


class PanelChannelSelect(discord.ui.ChannelSelect):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Canal do painel",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, MetaConfigEditorView):
            view.data["panel_channel_id"] = str(self.values[0].id)
            await interaction.response.defer(ephemeral=True)
            await view.refresh()


class ResultChannelSelect(discord.ui.ChannelSelect):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Canal de resultado",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, MetaConfigEditorView):
            view.data["result_channel_id"] = str(self.values[0].id)
            await interaction.response.defer(ephemeral=True)
            await view.refresh()


class AllowedRoleSelect(discord.ui.RoleSelect):
    def __init__(self) -> None:
        super().__init__(placeholder="Cargo autorizado", min_values=1, max_values=1, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, MetaConfigEditorView):
            view.data["allowed_role_id"] = str(self.values[0].id)
            await interaction.response.defer(ephemeral=True)
            await view.refresh()


class MetaAppearanceModal(discord.ui.Modal, title="Aparência do painel"):
    title_input = discord.ui.TextInput(label="Título", max_length=256)
    description_input = discord.ui.TextInput(
        label="Descrição", style=discord.TextStyle.paragraph, max_length=4096
    )
    color_input = discord.ui.TextInput(label="Cor hexadecimal", placeholder="#FFC72C", max_length=7)

    def __init__(self, editor: MetaConfigEditorView) -> None:
        super().__init__()
        self.editor = editor
        panel = editor.data.get("panel") or {}
        self.title_input.default = str(panel.get("title") or "")
        self.description_input.default = str(panel.get("description") or "")
        self.color_input.default = str(panel.get("color") or "#FFC72C")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        candidate = dict(self.editor.data)
        candidate["panel"] = {
            "title": self.title_input.value,
            "description": self.description_input.value,
            "color": self.color_input.value,
        }
        try:
            self.editor.data = parse_config(candidate).model_dump(mode="json")
        except ValidationError as exc:
            await interaction.response.send_message(
                exc.errors()[0]["msg"].removeprefix("Value error, "), ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        await self.editor.refresh()


def _diagnostic_text(errors: list[str], warnings: list[str]) -> str:
    lines = [*(f"❌ {item}" for item in errors), *(f"⚠️ {item}" for item in warnings)]
    return "\n".join(lines) or "✅ Configuração válida para publicação."


async def show_meta_diagnose(
    interaction: discord.Interaction,
    api: YunoAPI,
    state: dict[str, Any],
    guild_config: dict[str, Any],
) -> None:
    if not interaction.guild:
        await _send(interaction, "Servidor indisponível.")
        return
    domain_errors, domain_warnings = diagnose_state(guild_config, state)
    discord_errors: list[str] = []
    discord_warnings: list[str] = []
    if state.get("draft_data"):
        discord_errors, discord_warnings = await validate_discord(
            interaction.guild, state["draft_data"]
        )
    errors = list(dict.fromkeys(domain_errors + discord_errors))
    warnings = list(dict.fromkeys(domain_warnings + discord_warnings))
    await _send(interaction, _diagnostic_text(errors, warnings))


async def show_meta_editor(
    interaction: discord.Interaction,
    api: YunoAPI,
    state: dict[str, Any],
    guild_config: dict[str, Any],
) -> None:
    if not interaction.guild:
        await _send(interaction, "Servidor indisponível.")
        return
    try:
        state = await _seed_if_needed(interaction, api, state, guild_config)
    except httpx.HTTPError:
        await _send(interaction, "Não consegui importar o rascunho legado.")
        return
    view = MetaConfigEditorView(
        api,
        user_id=interaction.user.id,
        guild_name=interaction.guild.name,
        state=state,
    )
    view.message = await _send(interaction, embed=view.embed(), view=view, wait=True)


async def show_meta_preview(
    interaction: discord.Interaction,
    api: YunoAPI,
    state: dict[str, Any],
    guild_config: dict[str, Any],
) -> None:
    if not interaction.guild:
        await _send(interaction, "Servidor indisponível.")
        return
    try:
        state = await _seed_if_needed(interaction, api, state, guild_config)
        data = state.get("draft_data") or {}
        config = parse_config(data)
        errors, warnings = await validate_discord(interaction.guild, data)
    except (ValidationError, httpx.HTTPError) as exc:
        await _send(interaction, f"Rascunho inválido: {exc}")
        return
    details = discord.Embed(
        title="🔎 Prévia da publicação",
        description=_diagnostic_text(errors, warnings),
        color=discord.Color.red() if errors else discord.Color.green(),
    )
    details.add_field(name="Canal do painel", value=f"<#{config.panel_channel_id}>", inline=True)
    details.add_field(name="Canal de resultado", value=f"<#{config.result_channel_id}>", inline=True)
    details.add_field(name="Cargo autorizado", value=f"<@&{config.allowed_role_id}>", inline=True)
    details.add_field(
        name="Itens e quantidades",
        value="\n".join(f"• {item.name}: `{item.quantity}`" for item in config.default_items)[:1024],
        inline=False,
    )
    details.add_field(
        name="Versão seguinte",
        value=str(int(state.get("published_revision", 0)) + 1),
        inline=True,
    )
    details.add_field(
        name="Módulo ativo",
        value="Sim" if (guild_config.get("modules") or {}).get("meta", True) else "Não",
        inline=True,
    )
    await _send(interaction, embeds=[build_panel_embed(data, interaction.guild.name), details])


class MetaPublishConfirmView(discord.ui.View):
    def __init__(self, api: YunoAPI, *, user_id: int) -> None:
        super().__init__(timeout=180)
        self.api = api
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message("Esta confirmação pertence a outro usuário.", ephemeral=True)
        return False

    @discord.ui.button(label="Confirmar publicação", emoji="🚀", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Servidor indisponível.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            config = await self.api.get_guild_config(interaction.guild.id, force=True)
            if not is_control_plane_admin(interaction.guild, interaction.user, config):
                await interaction.followup.send("Sua permissão administrativa não é mais válida.", ephemeral=True)
                return
            state = await self.api.get_module_config_state(
                interaction.guild.id, "meta", actor_id=interaction.user.id
            )
            published = await publish_draft(interaction, self.api, state, config)
        except ControlPlaneConflict as exc:
            await interaction.followup.send(
                f"Conflito: o rascunho avançou para a revisão {exc.current_revision}.", ephemeral=True
            )
            return
        except ValueError as exc:
            await interaction.followup.send(f"Publicação bloqueada:\n{exc}", ephemeral=True)
            return
        except httpx.HTTPError:
            await interaction.followup.send(
                "A API recusou a publicação. O painel anterior foi restaurado.", ephemeral=True
            )
            return
        await interaction.followup.send(
            f"Metas publicadas na versão {published['published_revision']}.", ephemeral=True
        )
        self.stop()


async def show_meta_publish(
    interaction: discord.Interaction,
    api: YunoAPI,
    state: dict[str, Any],
    guild_config: dict[str, Any],
) -> None:
    if not interaction.guild:
        await _send(interaction, "Servidor indisponível.")
        return
    try:
        state = await _seed_if_needed(interaction, api, state, guild_config)
        errors, warnings = await validate_discord(interaction.guild, state.get("draft_data") or {})
    except httpx.HTTPError:
        await _send(interaction, "Não consegui carregar o rascunho.")
        return
    if errors:
        await _send(interaction, "Publicação bloqueada:\n" + _diagnostic_text(errors, warnings))
        return
    await _send(
        interaction,
        "A publicação atualizará o painel operacional e o Runtime. Confirme para continuar.",
        view=MetaPublishConfirmView(api, user_id=interaction.user.id),
    )
