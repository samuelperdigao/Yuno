import discord

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.producao.modals import ProducaoRegistrarModal
from yuno_bot.guards import requires_module


class ProducaoPanelView(discord.ui.View):
    def __init__(self, api: YunoAPI) -> None:
        super().__init__(timeout=None)
        self.api = api

    @discord.ui.button(
        label="Registrar Produção",
        emoji="🏭",
        style=discord.ButtonStyle.success,
        custom_id="yuno:producao:panel:registrar",
    )
    @requires_module("producao", "registrar")
    async def registrar(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(ProducaoRegistrarModal(self.api))
