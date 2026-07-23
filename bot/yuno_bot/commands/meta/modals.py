import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.meta.embeds import (
    build_meta_panel_config,
    build_meta_payload,
    meta_definition_embed,
    meta_log_embed,
    parse_meta_definition,
)
from yuno_bot.commands.shared import create_record, parse_positive_int, resolve_text_channel, send_module_log


class MetaRegistrarModal(discord.ui.Modal, title="Registrar Meta"):
    produto = discord.ui.TextInput(label="Produto", placeholder="Ex: Kit Desmanche", max_length=100)
    quantidade = discord.ui.TextInput(label="Quantidade", placeholder="Ex: 50", max_length=12)
    observacao = discord.ui.TextInput(label="Observacao", style=discord.TextStyle.paragraph, required=False, max_length=500)

    def __init__(self, api: YunoAPI):
        super().__init__()
        self.api = api

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            quantidade = parse_positive_int(self.quantidade.value, "Quantidade")
        except ValueError as exc:
            await interaction.response.send_message(f"Erro: {exc}", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        payload = build_meta_payload(self.produto.value, quantidade, self.observacao.value)
        try:
            record = await create_record(self.api, interaction, module="meta", title=f"Meta: {payload['produto']}", payload=payload)
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui registrar a meta agora.", ephemeral=True)
            return
        await send_module_log(self.api, interaction, "meta", meta_log_embed(interaction, record, payload))
        await interaction.followup.send(f"Meta registrada com sucesso. Protocolo #{record['id']}.", ephemeral=True)


class DefinirMetaModal(discord.ui.Modal, title="Definir Metas"):
    def __init__(self, api: YunoAPI, config: dict):
        super().__init__()
        self.api = api
        self.config = config
        meta_settings = (config.get("settings") or {}).get("meta") or {}
        self.itens = discord.ui.TextInput(
            label="Itens da meta",
            style=discord.TextStyle.paragraph,
            placeholder="item, quantidade\nitem, quantidade",
            default=(meta_settings.get("last_definition_text") or "")[:4000],
            max_length=4000,
        )
        self.add_item(self.itens)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw_definition = self.itens.value.strip()
        try:
            items = parse_meta_definition(raw_definition)
        except ValueError as exc:
            await interaction.response.send_message(
                f"Erro: {exc}\nExemplo:\n`item, quantidade`\n`item, quantidade`",
                ephemeral=True,
            )
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
            if not permissions.send_messages or not permissions.embed_links:
                await interaction.followup.send(
                    "Nao tenho permissao para enviar embeds no canal de resultado das metas.",
                    ephemeral=True,
                )
                return

        payload = {
            "items": items,
            "raw_definition": raw_definition,
            "defined_by": str(interaction.user.id),
            "result_channel_id": str(result_channel.id),
        }
        try:
            record = await create_record(
                self.api,
                interaction,
                module="meta",
                title=f"Meta definida por {interaction.user.display_name}"[:160],
                payload=payload,
            )
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui registrar a definicao de meta agora.", ephemeral=True)
            return

        try:
            await result_channel.send(
                embed=meta_definition_embed(interaction, record, items),
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
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
            await interaction.followup.send(
                f"Meta publicada com sucesso. Protocolo #{record['id']}. Nao consegui salvar a ultima definicao.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(f"Meta publicada com sucesso. Protocolo #{record['id']}.", ephemeral=True)


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
