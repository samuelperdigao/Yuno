import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.parceria.embeds import build_parceria_payload, parceria_log_embed, parceria_post_embed
from yuno_bot.commands.shared import create_record, send_module_log, send_to_setup_channel


class ParceriaCadastrarModal(discord.ui.Modal, title="Cadastrar Parceria"):
    nome = discord.ui.TextInput(label="Nome", placeholder="Ex: Familia Silva", max_length=100)
    produto_servico = discord.ui.TextInput(label="Produto/servico", placeholder="Ex: Municao, veiculos, apoio", max_length=100)
    contato_principal = discord.ui.TextInput(label="Contato principal", required=False, max_length=150)
    contato_secundario = discord.ui.TextInput(label="Contato secundario", required=False, max_length=150)
    observacao = discord.ui.TextInput(label="Observacao", style=discord.TextStyle.paragraph, required=False, max_length=500)

    def __init__(self, api: YunoAPI):
        super().__init__()
        self.api = api

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        payload = build_parceria_payload(
            self.nome.value,
            self.produto_servico.value,
            self.contato_principal.value,
            self.contato_secundario.value,
            self.observacao.value,
        )
        try:
            record = await create_record(self.api, interaction, module="parceria", title=f"Parceria: {payload['nome']}", payload=payload)
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui cadastrar a parceria agora.", ephemeral=True)
            return
        await send_to_setup_channel(self.api, interaction, "parcerias", embed=parceria_post_embed(interaction, record, payload))
        await send_module_log(self.api, interaction, "parceria", parceria_log_embed(interaction, record, payload))
        await interaction.followup.send(f"Parceria cadastrada com sucesso. Protocolo #{record['id']}.", ephemeral=True)
