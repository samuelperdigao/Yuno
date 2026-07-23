import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.producao.embeds import build_producao_payload, producao_log_embed, producao_post_embed
from yuno_bot.commands.shared import create_record, parse_positive_int, send_module_log, send_to_setup_channel


class ProducaoRegistrarModal(discord.ui.Modal, title="Registrar Producao"):
    produto = discord.ui.TextInput(label="Produto", placeholder="Ex: Colete", max_length=100)
    quantidade = discord.ui.TextInput(label="Quantidade", placeholder="Ex: 25", max_length=12)
    observacao = discord.ui.TextInput(label="Observacao", style=discord.TextStyle.paragraph, required=False, max_length=500)

    def __init__(self, api: YunoAPI):
        super().__init__()
        self.api = api

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            quantidade = parse_positive_int(self.quantidade.value, "Quantidade")
        except ValueError as exc:
            await interaction.response.send_message(f"Erro: {exc}", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        payload = build_producao_payload(self.produto.value, quantidade, self.observacao.value)
        try:
            record = await create_record(self.api, interaction, module="producao", title=f"Producao: {payload['produto']}", payload=payload)
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui registrar a producao agora.", ephemeral=True)
            return
        await send_to_setup_channel(self.api, interaction, "producao", embed=producao_post_embed(interaction, record, payload))
        await send_module_log(self.api, interaction, "producao", producao_log_embed(interaction, record, payload))
        await interaction.followup.send(f"Producao registrada com sucesso. Protocolo #{record['id']}.", ephemeral=True)
