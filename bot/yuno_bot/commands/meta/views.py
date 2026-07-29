import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.meta.embeds import (
    build_meta_definition_text,
    build_meta_panel_config,
    meta_builder_embed,
    meta_definition_embed,
    parse_meta_definition,
)
from yuno_bot.commands.shared import create_record, parse_positive_int, resolve_text_channel
from yuno_bot.guards import requires_module


MAX_META_ITEMS = 20


class MetaPanelView(discord.ui.View):
    def __init__(self, api: YunoAPI):
        super().__init__(timeout=None)
        self.api = api

    @discord.ui.button(label="Definir Meta", style=discord.ButtonStyle.primary, custom_id="yuno:meta:panel:define")
    @requires_module("meta", "definir")
    async def definir_meta(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Use este painel dentro de um servidor.", ephemeral=True)
            return

        try:
            config = await self.api.get_guild_config(interaction.guild.id)
        except httpx.HTTPError:
            await interaction.response.send_message("Nao consegui carregar a configuracao de metas agora.", ephemeral=True)
            return

        meta_settings = (config.get("settings") or {}).get("meta") or {}
        try:
            items = parse_meta_definition(meta_settings.get("last_definition_text") or "")
        except ValueError:
            items = []

        view = MetaDefinitionBuilderView(
            self.api,
            config,
            user_id=interaction.user.id,
            guild_name=interaction.guild.name,
            items=items,
        )
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)
        view.message = await interaction.original_response()


class MetaDefinitionBuilderView(discord.ui.View):
    def __init__(self, api: YunoAPI, config: dict, *, user_id: int, guild_name: str | None, items: list[dict]):
        super().__init__(timeout=900)
        self.api = api
        self.config = config
        self.user_id = user_id
        self.guild_name = guild_name
        self.items = list(items)
        self.message: discord.WebhookMessage | None = None
        self.refresh_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Este painel privado pertence a outro usuario.", ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        return meta_builder_embed(self.guild_name, self.items)

    def refresh_components(self) -> None:
        self.clear_items()
        self.add_item(AddMetaItemButton())
        if self.items:
            self.add_item(EditMetaItemSelect(self.items))
            self.add_item(RemoveLastMetaItemButton())
            self.add_item(ClearMetaItemsButton())
            self.add_item(SubmitMetaDefinitionButton())

    async def update_builder_message(self) -> None:
        self.refresh_components()
        if self.message:
            await self.message.edit(embed=self.build_embed(), view=self)

    async def submit_definition(self, interaction: discord.Interaction) -> None:
        if not self.items:
            await interaction.response.send_message("Adicione pelo menos uma linha antes de enviar.", ephemeral=True)
            return
        if not interaction.guild:
            await interaction.response.send_message("Use este painel dentro de um servidor.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            current_config = await self.api.get_guild_config(interaction.guild.id)
        except httpx.HTTPError:
            current_config = self.config

        meta_settings = (current_config.get("settings") or {}).get("meta") or {}
        panel_channel_id = _int_or_none(meta_settings.get("panel_channel_id")) or interaction.channel_id
        allowed_role_id = _int_or_none(meta_settings.get("allowed_role_id"))
        result_channel_id = _int_or_none(meta_settings.get("result_channel_id"))
        result_channel = await resolve_text_channel(interaction.guild, result_channel_id)
        if not result_channel:
            await interaction.followup.send("Canal de resultado das metas nao configurado ou inacessivel.", ephemeral=True)
            return
        if not panel_channel_id or not allowed_role_id:
            await interaction.followup.send("Painel de metas incompleto. Configure o painel novamente.", ephemeral=True)
            return

        bot_member = interaction.guild.me
        if bot_member:
            permissions = result_channel.permissions_for(bot_member)
            if not permissions.send_messages or not permissions.embed_links or not permissions.mention_everyone:
                await interaction.followup.send(
                    "Preciso de permissao para enviar mensagens, embeds e mencionar @everyone no canal de resultado.",
                    ephemeral=True,
                )
                return

        raw_definition = build_meta_definition_text(self.items)
        payload = {
            "items": self.items,
            "raw_definition": raw_definition,
            "defined_by": str(interaction.user.id),
            "result_channel_id": str(result_channel.id),
        }
        try:
            record = await create_record(
                self.api,
                interaction,
                module="meta",
                title=f"Meta definida em {interaction.guild.name}"[:160],
                payload=payload,
            )
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui registrar a definicao de meta agora.", ephemeral=True)
            return

        try:
            await result_channel.send(
                content="@everyone",
                embed=meta_definition_embed(interaction, record, self.items),
                allowed_mentions=discord.AllowedMentions(everyone=True, users=False, roles=False),
            )
        except discord.HTTPException:
            await interaction.followup.send("Nao consegui publicar a meta no canal configurado.", ephemeral=True)
            return

        updated_config = build_meta_panel_config(
            current_config,
            panel_channel_id=panel_channel_id,
            result_channel_id=result_channel.id,
            allowed_role_id=allowed_role_id,
            panel_message_id=_int_or_none(meta_settings.get("panel_message_id")),
            last_definition_text=raw_definition,
        )
        try:
            await self.api.save_guild_config(interaction.guild.id, updated_config)
        except httpx.HTTPError:
            await interaction.followup.send("Meta publicada, mas nao consegui salvar a ultima definicao.", ephemeral=True)
            return

        self.clear_items()
        if self.message:
            done_embed = discord.Embed(
                title="✅ Meta enviada",
                description=f"A definicao foi publicada em {result_channel.mention}.",
                color=discord.Color.green(),
            )
            await self.message.edit(embed=done_embed, view=None)


class AddMetaItemButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Adicionar linha", emoji="➕", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, MetaDefinitionBuilderView):
            return
        if len(view.items) >= MAX_META_ITEMS:
            await interaction.response.send_message(f"Limite de {MAX_META_ITEMS} itens atingido.", ephemeral=True)
            return
        await interaction.response.send_modal(MetaItemModal(view))


class EditMetaItemSelect(discord.ui.Select):
    def __init__(self, items: list[dict]):
        options = [
            discord.SelectOption(
                label=f"{index}. {item['name']}"[:100],
                description=f"Quantidade: {item['quantity']}"[:100],
                value=str(index - 1),
            )
            for index, item in enumerate(items[:25], start=1)
        ]
        super().__init__(placeholder="Editar uma linha", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, MetaDefinitionBuilderView):
            return
        index = int(self.values[0])
        await interaction.response.send_modal(MetaItemModal(view, item_index=index))


class RemoveLastMetaItemButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Remover ultima", emoji="↩️", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, MetaDefinitionBuilderView):
            return
        if view.items:
            view.items.pop()
        await interaction.response.defer(ephemeral=True)
        await view.update_builder_message()


class ClearMetaItemsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Limpar", emoji="🧹", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, MetaDefinitionBuilderView):
            return
        view.items.clear()
        await interaction.response.defer(ephemeral=True)
        await view.update_builder_message()


class SubmitMetaDefinitionButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Enviar", emoji="📣", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, MetaDefinitionBuilderView):
            await view.submit_definition(interaction)


class MetaItemModal(discord.ui.Modal, title="Linha da Meta"):
    item = discord.ui.TextInput(label="Item", placeholder="item", max_length=80)
    quantidade = discord.ui.TextInput(label="Quantidade", placeholder="quantidade", max_length=12)

    def __init__(self, builder: MetaDefinitionBuilderView, item_index: int | None = None):
        super().__init__()
        self.builder = builder
        self.item_index = item_index
        if item_index is not None and 0 <= item_index < len(builder.items):
            item = builder.items[item_index]
            self.item.default = item["name"]
            self.quantidade.default = str(item["quantity"])

    async def on_submit(self, interaction: discord.Interaction) -> None:
        name = self.item.value.strip()
        if not name:
            await interaction.response.send_message("Informe o item.", ephemeral=True)
            return
        try:
            quantity = parse_positive_int(self.quantidade.value, "Quantidade")
        except ValueError as exc:
            await interaction.response.send_message(f"Erro: {exc}", ephemeral=True)
            return

        item = {"name": name, "quantity": quantity}
        if self.item_index is None:
            self.builder.items.append(item)
        elif 0 <= self.item_index < len(self.builder.items):
            self.builder.items[self.item_index] = item

        await interaction.response.defer(ephemeral=True)
        await self.builder.update_builder_message()


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
