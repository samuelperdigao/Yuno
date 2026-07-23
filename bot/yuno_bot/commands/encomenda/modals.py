import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.encomenda.embeds import build_encomenda_payload, encomenda_log_embed, encomenda_post_embed
from yuno_bot.commands.shared import create_record, parse_positive_int, send_module_log, send_to_setup_channel


class EncomendaCriarModal(discord.ui.Modal, title="Criar Encomenda"):
    item = discord.ui.TextInput(label="Item", placeholder="Ex: Pistola, colete, kit", max_length=100)
    quantidade = discord.ui.TextInput(label="Quantidade", placeholder="Ex: 10", max_length=12)
    prazo = discord.ui.TextInput(label="Prazo", placeholder="Ex: 25/07 ou hoje 22h", max_length=80)
    cliente_familia = discord.ui.TextInput(label="Cliente/Familia", placeholder="Ex: Familia Silva", max_length=100)
    valor_observacao = discord.ui.TextInput(label="Valor/observacao", required=False, style=discord.TextStyle.paragraph, max_length=500)

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
        payload = build_encomenda_payload(self.item.value, quantidade, self.prazo.value, self.cliente_familia.value, self.valor_observacao.value)
        try:
            record = await create_record(self.api, interaction, module="encomenda", title=f"Encomenda: {payload['item']}", payload=payload)
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui criar a encomenda agora.", ephemeral=True)
            return
        await send_to_setup_channel(self.api, interaction, "encomendas", embed=encomenda_post_embed(interaction, record, payload))
        await send_module_log(self.api, interaction, "encomenda", encomenda_log_embed(interaction, record, payload))
        await interaction.followup.send(f"Encomenda criada com sucesso. Protocolo #{record['id']}.", ephemeral=True)
