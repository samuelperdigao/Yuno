import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.guards import ensure_allowed


class MetaPanelView(discord.ui.View):
    def __init__(self, api: YunoAPI):
        super().__init__(timeout=None)
        self.api = api

    @discord.ui.button(label="Definir Meta", style=discord.ButtonStyle.primary, custom_id="yuno:meta:panel:define")
    async def definir_meta(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        allowed, reason = await ensure_allowed(interaction, self.api, "meta", "definir")
        if not allowed:
            await interaction.response.send_message(f"Yuno nao pode executar isso agora: {reason}", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.response.send_message("Use este painel dentro de um servidor.", ephemeral=True)
            return

        try:
            config = await self.api.get_guild_config(interaction.guild.id)
        except httpx.HTTPError:
            await interaction.response.send_message("Nao consegui carregar a configuracao de metas agora.", ephemeral=True)
            return

        from yuno_bot.commands.meta.modals import DefinirMetaModal

        await interaction.response.send_modal(DefinirMetaModal(self.api, config))
