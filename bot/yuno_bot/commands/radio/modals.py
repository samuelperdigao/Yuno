import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.radio.embeds import build_radio_payload, radio_log_embed, radio_post_embed
from yuno_bot.commands.shared import create_record, send_module_log, send_to_setup_channel


class RadioAlterarModal(discord.ui.Modal, title="Alterar Radio"):
    radio_atual = discord.ui.TextInput(label="Radio atual", placeholder="Ex: 1221", max_length=40)
    radio_nova = discord.ui.TextInput(label="Radio nova", placeholder="Ex: 1331", max_length=40)
    motivo = discord.ui.TextInput(label="Motivo", style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, api: YunoAPI):
        super().__init__()
        self.api = api

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        payload = build_radio_payload(self.radio_atual.value, self.radio_nova.value, self.motivo.value)
        try:
            record = await create_record(
                self.api,
                interaction,
                module="radio",
                title=f"Radio: {payload['radio_atual']} para {payload['radio_nova']}",
                payload=payload,
            )
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui registrar a alteracao de radio agora.", ephemeral=True)
            return
        await send_to_setup_channel(self.api, interaction, "radio", embed=radio_post_embed(interaction, record, payload))
        await send_module_log(self.api, interaction, "radio", radio_log_embed(interaction, record, payload))
        await interaction.followup.send(f"Radio alterada registrada com sucesso. Protocolo #{record['id']}.", ephemeral=True)
