import discord
import httpx
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.disparo.embeds import painel_disparo_embed
from yuno_bot.commands.disparo.views import DisparoPanelView
from yuno_bot.guards import deny


class DisparoCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    disparo = app_commands.Group(name="disparo", description="Disparo de mensagens para as pastas de membro")

    @disparo.command(name="painel", description="Publica o painel de disparo de mensagens neste canal")
    @app_commands.default_permissions(manage_guild=True)
    async def painel(self, interaction: discord.Interaction, canal: discord.TextChannel) -> None:
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

        try:
            await canal.send(embed=painel_disparo_embed(), view=DisparoPanelView(self.bot.api))
        except discord.HTTPException:
            await interaction.followup.send("Nao consegui publicar o painel no canal informado.", ephemeral=True)
            return

        command_permissions = dict(current_config.get("command_permissions") or {})
        rule = dict(command_permissions.get("disparo.enviar") or {})
        rule["channel_ids"] = [str(canal.id)]
        command_permissions["disparo.enviar"] = rule

        settings = dict(current_config.get("settings") or {})
        disparo_settings = dict(settings.get("disparo") or {})
        disparo_settings["panel_channel_id"] = str(canal.id)
        settings["disparo"] = disparo_settings

        updated_config = {
            "guild_name": current_config.get("guild_name"),
            "admin_role_ids": current_config.get("admin_role_ids") or [],
            "log_channel_id": current_config.get("log_channel_id"),
            "modules": current_config.get("modules") or {},
            "command_permissions": command_permissions,
            "messages": current_config.get("messages") or {},
            "settings": settings,
        }
        try:
            await self.bot.api.save_guild_config(interaction.guild.id, updated_config)
        except httpx.HTTPError:
            await interaction.followup.send("Painel publicado, mas nao consegui salvar a configuracao.", ephemeral=True)
            return

        await interaction.followup.send(f"Painel de disparo publicado em {canal.mention}.", ephemeral=True)
