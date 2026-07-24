import discord

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.ausencia.modals import AusenciaRegistroModal


class AusenciaPanelView(discord.ui.View):
    def __init__(self, api: YunoAPI):
        super().__init__(timeout=None)
        self.api = api

    @discord.ui.button(label="📋 Registrar Ausência", style=discord.ButtonStyle.primary, custom_id="ausencia_panel:registrar")
    async def registrar(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(AusenciaRegistroModal(self.api))
