import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.shared import create_record, send_module_log, send_to_setup_channel
from yuno_bot.commands.ticket.embeds import build_ticket_payload, ticket_log_embed, ticket_post_embed


class TicketAbrirModal(discord.ui.Modal, title="Abrir Ticket"):
    tipo = discord.ui.TextInput(label="Tipo", placeholder="Ex: suporte, denuncia, duvida", max_length=80)
    assunto = discord.ui.TextInput(label="Assunto", placeholder="Resumo do ticket", max_length=120)
    descricao = discord.ui.TextInput(label="Descricao", style=discord.TextStyle.paragraph, max_length=800)

    def __init__(self, api: YunoAPI):
        super().__init__()
        self.api = api

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        payload = build_ticket_payload(self.tipo.value, self.assunto.value, self.descricao.value)
        try:
            record = await create_record(self.api, interaction, module="ticket", title=f"Ticket: {payload['assunto']}", payload=payload)
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui abrir o ticket agora.", ephemeral=True)
            return
        await send_to_setup_channel(self.api, interaction, "tickets", embed=ticket_post_embed(interaction, record, payload))
        await send_module_log(self.api, interaction, "ticket", ticket_log_embed(interaction, record, payload))
        await interaction.followup.send(f"Ticket aberto com sucesso. Protocolo #{record['id']}.", ephemeral=True)
