import discord
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.radio.modals import RadioAlterarModal
from yuno_bot.guards import deny, ensure_allowed


class RadioCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    radio = app_commands.Group(name="radio", description="Sistema de alteracao de radio")

    @radio.command(name="alterar", description="Abre o formulario de alteracao de radio")
    async def alterar(self, interaction: discord.Interaction) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "radio", "alterar")
        if not allowed:
            await deny(interaction, reason)
            return
        await interaction.response.send_modal(RadioAlterarModal(self.bot.api))
