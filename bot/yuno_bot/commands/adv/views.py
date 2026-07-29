import discord

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.adv.modals import AdvModal
from yuno_bot.guards import requires_module


class AdvMemberSelectView(discord.ui.View):
    """View efêmera para selecionar o membro a ser advertido."""

    def __init__(self, api: YunoAPI) -> None:
        super().__init__(timeout=120)
        self.api = api

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Selecione o membro a advertir...", min_values=1, max_values=1)
    async def selecionar_membro(self, interaction: discord.Interaction, select: discord.ui.UserSelect) -> None:
        membro = select.values[0]
        if not isinstance(membro, discord.Member):
            await interaction.response.send_message("Membro não encontrado neste servidor.", ephemeral=True)
            return
        await interaction.response.send_modal(AdvModal(self.api, membro))


class AdvPanelView(discord.ui.View):
    def __init__(self, api: YunoAPI) -> None:
        super().__init__(timeout=None)
        self.api = api

    @discord.ui.button(label="Aplicar Advertência", style=discord.ButtonStyle.danger, custom_id="yuno:adv:panel:aplicar")
    @requires_module("adv", "aplicar")
    async def aplicar(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "Selecione o membro a ser advertido:", view=AdvMemberSelectView(self.api), ephemeral=True
        )
