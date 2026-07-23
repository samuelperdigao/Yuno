import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.ausencia.embeds import ausencia_log_embed, ausencia_post_embed, build_ausencia_payload
from yuno_bot.commands.shared import create_record, send_module_log, send_to_setup_channel


class AusenciaAvisarModal(discord.ui.Modal, title="Registrar Ausencia"):
    inicio = discord.ui.TextInput(label="Inicio", placeholder="Ex: 23/07/2026", max_length=40)
    fim = discord.ui.TextInput(label="Fim", placeholder="Ex: 30/07/2026", max_length=40)
    motivo = discord.ui.TextInput(label="Motivo", style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, api: YunoAPI):
        super().__init__()
        self.api = api

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        payload = build_ausencia_payload(self.inicio.value, self.fim.value, self.motivo.value)
        try:
            record = await create_record(self.api, interaction, module="ausencia", title=f"Ausencia: {payload['inicio']} ate {payload['fim']}", payload=payload)
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui registrar a ausencia agora.", ephemeral=True)
            return
        await send_to_setup_channel(self.api, interaction, "ausencias", embed=ausencia_post_embed(interaction, record, payload))
        await send_module_log(self.api, interaction, "ausencia", ausencia_log_embed(interaction, record, payload))
        await interaction.followup.send(f"Ausencia registrada com sucesso. Protocolo #{record['id']}.", ephemeral=True)
