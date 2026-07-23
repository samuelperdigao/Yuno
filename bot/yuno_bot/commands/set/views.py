import discord

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.set.actions import approve_set_record
from yuno_bot.commands.set.embeds import approved_public_embed
from yuno_bot.guards import ensure_allowed


class SetPanelView(discord.ui.View):
    def __init__(self, api: YunoAPI):
        super().__init__(timeout=None)
        self.api = api

    @discord.ui.button(label="Pedir Set", emoji="📝", style=discord.ButtonStyle.primary, custom_id="yuno:set:panel:request")
    async def pedir_set(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        allowed, reason = await ensure_allowed(interaction, self.api, "set", "solicitar")
        if not allowed:
            await interaction.response.send_message(f"Yuno nao pode executar isso agora: {reason}", ephemeral=True)
            return

        from yuno_bot.commands.set.modals import SetSolicitarModal

        await interaction.response.send_modal(SetSolicitarModal(self.api))


class SetApprovalView(discord.ui.View):
    def __init__(self, api: YunoAPI, protocolo: int):
        super().__init__(timeout=None)
        self.api = api
        self.protocolo = protocolo
        self._processing = False

    @discord.ui.button(label="Aprovar", style=discord.ButtonStyle.success)
    async def aprovar(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        allowed, reason = await ensure_allowed(interaction, self.api, "set", "aprovar")
        if not allowed:
            await interaction.response.send_message(f"Yuno nao pode executar isso agora: {reason}", ephemeral=True)
            return
        if self._processing:
            await interaction.response.send_message("Esta solicitacao ja esta sendo processada.", ephemeral=True)
            return
        self._processing = True
        await interaction.response.defer(ephemeral=True)
        record, message = await approve_set_record(self.api, interaction, self.protocolo)
        if not record:
            await interaction.followup.send(message, ephemeral=True)
            self._processing = False
            return
        if interaction.message:
            try:
                await interaction.message.edit(view=None)
            except discord.HTTPException:
                pass
        if interaction.channel:
            try:
                await interaction.channel.send(
                    embed=approved_public_embed(interaction, record, message),
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
            except discord.HTTPException:
                pass
        await interaction.followup.send(f"Set #{self.protocolo} aprovado. {message}", ephemeral=True)

    @discord.ui.button(label="Reprovar", style=discord.ButtonStyle.danger)
    async def reprovar(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        allowed, reason = await ensure_allowed(interaction, self.api, "set", "reprovar")
        if not allowed:
            await interaction.response.send_message(f"Yuno nao pode executar isso agora: {reason}", ephemeral=True)
            return
        from yuno_bot.commands.set.modals import SetReprovarModal

        await interaction.response.send_modal(SetReprovarModal(self.api, protocolo=self.protocolo, source_message=interaction.message))
