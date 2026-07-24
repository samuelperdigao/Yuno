import discord

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.radio.modals import RadioModal
from yuno_bot.commands.radio.permissions import pode_alterar_radio


class RadioPainelView(discord.ui.View):
    def __init__(self, api: YunoAPI):
        super().__init__(timeout=None)
        self.api = api

    @discord.ui.button(
        label="Alterar rádio",
        emoji="📻",
        style=discord.ButtonStyle.primary,
        custom_id="yuno:radio:panel:definir",
    )
    async def alterar_radio(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ Use este painel dentro de um servidor.", ephemeral=True)
            return
        if not pode_alterar_radio(interaction.user):
            await interaction.response.send_message("❌ Apenas gerentes e administradores podem alterar a rádio.", ephemeral=True)
            return
        await interaction.response.send_modal(RadioModal(self.api))
