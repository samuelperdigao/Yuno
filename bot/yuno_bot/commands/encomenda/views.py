import discord

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.encomenda.modals import EncomendaCriarModal
from yuno_bot.guards import requires_module


class EncomendaPanelView(discord.ui.View):
    def __init__(self, api: YunoAPI) -> None:
        super().__init__(timeout=None)
        self.api = api

    @discord.ui.button(
        label="Registrar Encomenda",
        emoji="📦",
        style=discord.ButtonStyle.primary,
        custom_id="yuno:encomenda:panel:criar",
    )
    @requires_module("encomenda", "criar")
    async def criar(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(EncomendaCriarModal(self.api))
