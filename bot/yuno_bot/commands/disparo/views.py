import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.disparo.modals import DisparoModal
from yuno_bot.commands.shared import get_guild_config
from yuno_bot.guards import requires_module


class DeleteDisparoConfirmView(discord.ui.View):
    def __init__(self, api: YunoAPI, *, batch_record_id: int, requester_id: int) -> None:
        super().__init__(timeout=60)
        self.api = api
        self.batch_record_id = batch_record_id
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Apenas quem iniciou a exclusão pode confirmar esta ação.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirmar Exclusão", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def confirmar(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild:
            return
        try:
            record = await self.api.get_record(module="disparo", record_id=self.batch_record_id)
        except httpx.HTTPError:
            await interaction.response.send_message("Não consegui carregar este disparo.", ephemeral=True)
            return
        if record["status"] != "open":
            await interaction.response.send_message("Este disparo já foi apagado.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        deletados = 0
        falhas = 0
        for item in record["payload"].get("enviados") or []:
            canal = interaction.guild.get_channel(int(item["channel_id"]))
            if canal is None:
                falhas += 1
                continue
            try:
                mensagem = await canal.fetch_message(int(item["message_id"]))
                await mensagem.delete()
                deletados += 1
            except discord.NotFound:
                continue
            except discord.HTTPException:
                falhas += 1

        try:
            await self.api.patch_record(module="disparo", record_id=self.batch_record_id, status="cancelled", reviewer_id=interaction.user.id)
        except httpx.HTTPError:
            pass
        await interaction.followup.send(f"Mensagens apagadas: {deletados}. Falhas: {falhas}.", ephemeral=True)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Exclusão cancelada.", view=None)


class DisparoPanelView(discord.ui.View):
    def __init__(self, api: YunoAPI) -> None:
        super().__init__(timeout=None)
        self.api = api

    @discord.ui.button(label="Enviar Mensagem", emoji="📨", style=discord.ButtonStyle.primary, custom_id="yuno:disparo:panel:enviar")
    @requires_module("disparo", "enviar")
    async def enviar(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(DisparoModal(self.api))

    @discord.ui.button(label="Apagar Último Disparo", emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="yuno:disparo:panel:apagar")
    @requires_module("disparo", "enviar")
    async def apagar(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Use este painel dentro de um servidor.", ephemeral=True)
            return
        config = await get_guild_config(self.api, interaction.guild.id)
        batch_id = ((config.get("settings") or {}).get("disparo") or {}).get("last_batch_record_id")
        if not batch_id:
            await interaction.response.send_message("Nenhum disparo registrado para apagar.", ephemeral=True)
            return
        try:
            record = await self.api.get_record(module="disparo", record_id=int(batch_id))
        except httpx.HTTPError:
            await interaction.response.send_message("Não consegui carregar o último disparo.", ephemeral=True)
            return
        if record["status"] != "open":
            await interaction.response.send_message("O último disparo já foi apagado.", ephemeral=True)
            return

        count = len(record["payload"].get("enviados") or [])
        await interaction.response.send_message(
            f"Você está prestes a apagar {count} mensagem(ns) do último disparo. Somente mensagens registradas pelo painel serão removidas.",
            view=DeleteDisparoConfirmView(self.api, batch_record_id=int(batch_id), requester_id=interaction.user.id),
            ephemeral=True,
        )
