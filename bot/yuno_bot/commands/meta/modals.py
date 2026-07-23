import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.meta.embeds import build_meta_payload, meta_log_embed
from yuno_bot.commands.shared import create_record, parse_positive_int, send_module_log


class MetaRegistrarModal(discord.ui.Modal, title="Registrar Meta"):
    produto = discord.ui.TextInput(label="Produto", placeholder="Ex: Kit Desmanche", max_length=100)
    quantidade = discord.ui.TextInput(label="Quantidade", placeholder="Ex: 50", max_length=12)
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
        payload = build_meta_payload(self.produto.value, quantidade, self.observacao.value)
        try:
            record = await create_record(self.api, interaction, module="meta", title=f"Meta: {payload['produto']}", payload=payload)
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui registrar a meta agora.", ephemeral=True)
            return
        await send_module_log(self.api, interaction, "meta", meta_log_embed(interaction, record, payload))
        await interaction.followup.send(f"Meta registrada com sucesso. Protocolo #{record['id']}.", ephemeral=True)
