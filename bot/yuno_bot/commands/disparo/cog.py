import discord
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.disparo.embeds import painel_disparo_embed
from yuno_bot.commands.disparo.views import DisparoPanelView
from yuno_bot.commands.panels import publish_panel_command


class DisparoCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    disparo = app_commands.Group(name="disparo", description="Disparo de mensagens para as pastas de membro")

    @disparo.command(name="painel", description="Publica o painel de disparo de mensagens neste canal")
    @app_commands.default_permissions(manage_guild=True)
    async def painel(self, interaction: discord.Interaction, canal: discord.TextChannel) -> None:
        await publish_panel_command(
            interaction,
            self.bot.api,
            module_key="disparo",
            setup_channel_key="disparo",
            embed=painel_disparo_embed(),
            view=DisparoPanelView(self.bot.api),
            channel=canal,
            command_names=("enviar",),
            label="Painel de disparo",
        )
