import discord
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.ausencia.modals import AusenciaAvisarModal
from yuno_bot.guards import deny, ensure_allowed


class AusenciaCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    ausencia = app_commands.Group(name="ausencia", description="Sistema de ausencia")

    @ausencia.command(name="avisar", description="Abre o formulario de ausencia")
    async def avisar(self, interaction: discord.Interaction) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "ausencia", "avisar")
        if not allowed:
            await deny(interaction, reason)
            return
        await interaction.response.send_modal(AusenciaAvisarModal(self.bot.api))
