import discord

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.ticket.modals import TicketAbrirModal
from yuno_bot.guards import requires_module


class TicketPanelView(discord.ui.View):
    def __init__(self, api: YunoAPI) -> None:
        super().__init__(timeout=None)
        self.api = api

    @discord.ui.button(
        label="Abrir Ticket",
        emoji="📨",
        style=discord.ButtonStyle.primary,
        custom_id="yuno:ticket:panel:abrir",
    )
    @requires_module("ticket", "abrir")
    async def abrir(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(TicketAbrirModal(self.api))
