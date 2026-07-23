import discord
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.ticket.modals import TicketAbrirModal
from yuno_bot.guards import deny, ensure_allowed


class TicketCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    ticket = app_commands.Group(name="ticket", description="Sistema de tickets")

    @ticket.command(name="abrir", description="Abre o formulario de ticket")
    async def abrir(self, interaction: discord.Interaction) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "ticket", "abrir")
        if not allowed:
            await deny(interaction, reason)
            return
        await interaction.response.send_modal(TicketAbrirModal(self.bot.api))
