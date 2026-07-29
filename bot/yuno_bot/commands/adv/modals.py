import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.adv.embeds import adv_log_embed, adv_post_embed, build_adv_payload
from yuno_bot.commands.shared import create_record, parse_positive_int, send_module_log, send_to_setup_channel


class AdvModal(discord.ui.Modal, title="Registrar Advertência"):
    descricao = discord.ui.TextInput(
        label="Descrição da Advertência",
        placeholder="Descreva o motivo da advertência",
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )
    dias = discord.ui.TextInput(label="Dias de Advertência", placeholder="Ex: 7", max_length=3)

    def __init__(self, api: YunoAPI, membro: discord.Member):
        super().__init__()
        self.api = api
        self.membro = membro

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            dias_val = parse_positive_int(self.dias.value, "Dias")
        except ValueError as exc:
            await interaction.response.send_message(f"Erro: {exc}", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        payload = build_adv_payload(self.membro.id, self.descricao.value, dias_val)
        try:
            record = await create_record(
                self.api,
                interaction,
                module="adv",
                title=f"Advertência: {self.membro.display_name}",
                payload=payload,
            )
        except httpx.HTTPError:
            await interaction.followup.send("Não consegui registrar a advertência agora.", ephemeral=True)
            return

        await send_to_setup_channel(self.api, interaction, "adv", embed=adv_post_embed(interaction, record, self.membro, payload))
        await send_module_log(self.api, interaction, "adv", adv_log_embed(interaction, record, self.membro, payload))
        await interaction.followup.send(f"Advertência registrada com sucesso. Protocolo #{record['id']}.", ephemeral=True)
