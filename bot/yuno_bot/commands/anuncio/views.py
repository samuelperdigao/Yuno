import discord

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.anuncio.modals import AnuncioModal
from yuno_bot.guards import requires_module


class AnuncioPanelView(discord.ui.View):
    """`command_permissions["anuncio.publicar"].channel_ids` ja restringe este
    botao ao canal configurado -- por isso `interaction.channel` pode ser usado
    direto como destino do anuncio, sem precisar resolver de novo via settings."""

    def __init__(self, api: YunoAPI) -> None:
        super().__init__(timeout=None)
        self.api = api

    @discord.ui.button(label="Novo Anúncio", style=discord.ButtonStyle.primary, custom_id="yuno:anuncio:panel:novo")
    @requires_module("anuncio", "publicar")
    async def novo(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Use este painel dentro de um canal de texto.", ephemeral=True)
            return
        await interaction.response.send_modal(AnuncioModal(self.api, interaction.channel))
