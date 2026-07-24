from typing import Any

import discord
import httpx

from yuno_bot.commands.shared import parse_positive_int
from yuno_bot.commands.farm_tickets.helpers import first_image_url, is_valid_image_message


class FarmEntryModal(discord.ui.Modal, title="Lancar Farm"):
    def __init__(self, controller: Any, ticket: dict):
        super().__init__()
        self.controller = controller
        self.ticket = ticket
        self.item_inputs: list[tuple[str, discord.ui.TextInput]] = []
        self.observacao = discord.ui.TextInput(label="Observacao", style=discord.TextStyle.paragraph, required=False, max_length=400)
        for item in (ticket.get("goal_items") or [])[:5]:
            name = str(item.get("name") or item.get("produto") or "Item")
            text_input = discord.ui.TextInput(label=name[:45], placeholder="Quantidade entregue", required=False, max_length=12)
            self.item_inputs.append((name, text_input))
            self.add_item(text_input)
        self.add_item(self.observacao)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        values: dict[str, int] = {}
        for name, text_input in self.item_inputs:
            raw = text_input.value.strip()
            if not raw:
                continue
            try:
                values[name] = parse_positive_int(raw, name)
            except ValueError as exc:
                await interaction.response.send_message(f"Erro: {exc}", ephemeral=True)
                return
        if not values:
            await interaction.response.send_message("Informe pelo menos um valor positivo.", ephemeral=True)
            return
        if not interaction.channel:
            await interaction.response.send_message("Nao consegui identificar este canal.", ephemeral=True)
            return

        await interaction.response.send_message("Agora envie o print/comprovante neste canal em ate 3 minutos.", ephemeral=True)

        def check(message: discord.Message) -> bool:
            return message.author.id == interaction.user.id and message.channel.id == interaction.channel.id and is_valid_image_message(message)

        try:
            proof_message = await interaction.client.wait_for("message", check=check, timeout=180)
        except TimeoutError:
            await interaction.followup.send("Tempo esgotado. O lancamento nao foi registrado.", ephemeral=True)
            return

        proof_url = first_image_url(proof_message)
        if not proof_url:
            await interaction.followup.send("O comprovante precisa ser uma imagem valida.", ephemeral=True)
            return

        try:
            ticket = await self.controller.bot.api.create_farm_ticket_entry(
                int(self.ticket["id"]),
                {
                    "actor_id": str(interaction.user.id),
                    "values": values,
                    "proof_channel_id": str(proof_message.channel.id),
                    "proof_message_id": str(proof_message.id),
                    "proof_url": proof_url,
                    "observacao": self.observacao.value.strip() or None,
                },
            )
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui registrar o farm agora.", ephemeral=True)
            return

        await self.controller.refresh_ticket_channel_message(interaction.guild, ticket)
        await self.controller.flush_pending_logs()
        await interaction.followup.send("Farm registrado com sucesso.", ephemeral=True)


class FarmReviewModal(discord.ui.Modal, title="Revisar Lancamento"):
    entry_id = discord.ui.TextInput(label="ID do lancamento", placeholder="Ex: 12", max_length=12)
    reason = discord.ui.TextInput(label="Motivo", style=discord.TextStyle.paragraph, max_length=400)

    def __init__(self, controller: Any, ticket: dict):
        super().__init__()
        self.controller = controller
        self.ticket = ticket

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            entry_id = parse_positive_int(self.entry_id.value, "ID do lancamento")
        except ValueError as exc:
            await interaction.response.send_message(f"Erro: {exc}", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            ticket = await self.controller.bot.api.review_farm_ticket_entry(
                int(self.ticket["id"]),
                {"actor_id": str(interaction.user.id), "entry_id": entry_id, "reason": self.reason.value.strip()},
            )
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui marcar esse lancamento em revisao.", ephemeral=True)
            return
        await self.controller.refresh_ticket_channel_message(interaction.guild, ticket)
        await self.controller.flush_pending_logs()
        await interaction.followup.send("Lancamento marcado em revisao.", ephemeral=True)


class FarmFinalizeModal(discord.ui.Modal, title="Finalizar Ticket"):
    reason = discord.ui.TextInput(label="Motivo", default="Finalizado manualmente", max_length=300)

    def __init__(self, controller: Any, ticket: dict):
        super().__init__()
        self.controller = controller
        self.ticket = ticket

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            ticket = await self.controller.bot.api.finalize_farm_ticket(
                int(self.ticket["id"]),
                {"actor_id": str(interaction.user.id), "reason": self.reason.value.strip() or "Finalizado manualmente"},
            )
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui finalizar o ticket agora.", ephemeral=True)
            return
        await self.controller.lock_member_channel_permissions(interaction.guild, ticket)
        await self.controller.refresh_ticket_channel_message(interaction.guild, ticket)
        await self.controller.flush_pending_logs()
        await interaction.followup.send(f"Ticket finalizado como `{ticket['status']}`.", ephemeral=True)
