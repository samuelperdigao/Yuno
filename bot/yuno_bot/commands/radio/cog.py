import logging

import discord
import httpx
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.radio.embeds import criar_embed_painel_radio
from yuno_bot.commands.radio.modals import RadioModal
from yuno_bot.commands.radio.permissions import configurar_permissoes_radio, pode_alterar_radio, resolver_canal_radio
from yuno_bot.commands.radio.views import RadioPainelView
from yuno_bot.guards import deny


LOGGER = logging.getLogger(__name__)


class RadioCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._guilds_configuradas: set[int] = set()

    radio = app_commands.Group(name="radio", description="Sistema de alteração de rádio")

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        for guild in self.bot.guilds:
            if guild.id in self._guilds_configuradas:
                continue
            canal = await resolver_canal_radio(self.bot.api, guild)
            if not canal:
                LOGGER.warning("Canal de radio nao configurado guild_id=%s", guild.id)
                self._guilds_configuradas.add(guild.id)
                continue
            try:
                await configurar_permissoes_radio(canal)
            except discord.HTTPException:
                LOGGER.warning("Falha ao configurar permissoes do canal de radio guild_id=%s channel_id=%s", guild.id, canal.id, exc_info=True)
            self._guilds_configuradas.add(guild.id)

    @radio.command(name="alterar", description="Abre o formulário de alteração de rádio")
    async def alterar(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await deny(interaction, "use dentro de um servidor.")
            return
        if not pode_alterar_radio(interaction.user):
            await interaction.response.send_message("❌ Apenas gerentes e administradores podem alterar a rádio.", ephemeral=True)
            return
        await interaction.response.send_modal(RadioModal(self.bot.api))

    @radio.command(name="painel", description="Publica ou atualiza o painel fixo de rádio")
    @app_commands.default_permissions(manage_guild=True)
    async def painel(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await deny(interaction, "use dentro de um servidor.")
            return
        if not (
            interaction.user.guild_permissions.manage_guild
            or interaction.user.guild_permissions.administrator
            or interaction.guild.owner_id == interaction.user.id
        ):
            await deny(interaction, "voce precisa ter permissao de gerenciar servidor.")
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            current_config = await self.bot.api.get_guild_config(interaction.guild.id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                await interaction.followup.send("Este servidor ainda nao possui licenca ativa.", ephemeral=True)
                return
            await interaction.followup.send("Nao consegui carregar a configuracao do servidor.", ephemeral=True)
            return
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui falar com a API do Yuno.", ephemeral=True)
            return

        canal = await resolver_canal_radio(self.bot.api, interaction.guild)
        if not canal:
            await interaction.followup.send("Canal de rádio não encontrado. Execute `/yuno configurar` antes de publicar o painel.", ephemeral=True)
            return

        try:
            await configurar_permissoes_radio(canal)
        except discord.Forbidden:
            await interaction.followup.send("Sem permissão para configurar o canal de rádio.", ephemeral=True)
            return
        except discord.HTTPException:
            LOGGER.exception("Falha ao configurar painel de radio guild_id=%s channel_id=%s", interaction.guild.id, canal.id)
            await interaction.followup.send("Não consegui configurar as permissões do canal de rádio.", ephemeral=True)
            return

        panel_message = await self._publish_or_update_panel(current_config, canal)
        if not panel_message:
            await interaction.followup.send("Não consegui publicar o painel no canal de rádio.", ephemeral=True)
            return

        updated_config = _build_radio_panel_config(current_config, panel_channel_id=canal.id, panel_message_id=panel_message.id)
        try:
            await self.bot.api.save_guild_config(interaction.guild.id, updated_config)
        except httpx.HTTPError:
            await interaction.followup.send("Painel publicado, mas não consegui salvar a configuração.", ephemeral=True)
            return

        await interaction.followup.send(f"✅ Painel de rádio postado em {canal.mention}!", ephemeral=True)

    async def _publish_or_update_panel(self, current_config: dict, canal: discord.TextChannel) -> discord.Message | None:
        radio_settings = (current_config.get("settings") or {}).get("radio") or {}
        previous_channel_id = radio_settings.get("panel_channel_id")
        previous_message_id = radio_settings.get("panel_message_id")
        embed = criar_embed_painel_radio()
        view = RadioPainelView(self.bot.api)

        if str(previous_channel_id) == str(canal.id) and previous_message_id:
            try:
                message = await canal.fetch_message(int(previous_message_id))
                await message.edit(embed=embed, view=view)
                return message
            except (ValueError, discord.HTTPException):
                pass

        try:
            return await canal.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            return None


def _build_radio_panel_config(current_config: dict, *, panel_channel_id: int, panel_message_id: int) -> dict:
    settings = dict(current_config.get("settings") or {})
    radio_settings = dict(settings.get("radio") or {})
    radio_settings["panel_channel_id"] = str(panel_channel_id)
    radio_settings["panel_message_id"] = str(panel_message_id)
    settings["radio"] = radio_settings

    return {
        "guild_name": current_config.get("guild_name"),
        "admin_role_ids": current_config.get("admin_role_ids") or [],
        "log_channel_id": current_config.get("log_channel_id"),
        "modules": current_config.get("modules") or {},
        "command_permissions": current_config.get("command_permissions") or {},
        "messages": current_config.get("messages") or {},
        "settings": settings,
    }
