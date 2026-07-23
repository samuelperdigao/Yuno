import discord
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.parceria.modals import ParceriaCadastrarModal
from yuno_bot.guards import deny, ensure_allowed


class ParceriaCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    parceria = app_commands.Group(name="parceria", description="Sistema de parcerias")

    @parceria.command(name="cadastrar", description="Abre o formulario de parceria")
    async def cadastrar(self, interaction: discord.Interaction) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "parceria", "cadastrar")
        if not allowed:
            await deny(interaction, reason)
            return
        await interaction.response.send_modal(ParceriaCadastrarModal(self.bot.api))
