from typing import Any

import discord
import httpx

from yuno_bot.commands.farm_tickets.embeds import farm_ticket_embed, recent_proofs_text
from yuno_bot.commands.farm_tickets.helpers import build_ticket_channel_name, choose_ticket_category, is_farm_admin, member_has_any_role
from yuno_bot.commands.farm_tickets.modals import FarmEntryModal, FarmFinalizeModal, FarmReviewModal


class FarmPanelView(discord.ui.View):
    def __init__(self, controller: Any):
        super().__init__(timeout=None)
        self.controller = controller

    @discord.ui.button(label="Abrir Ticket Semanal", style=discord.ButtonStyle.primary, custom_id="yuno:farm:panel:open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Use este painel dentro de um servidor.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.controller.open_weekly_ticket(interaction)

    @discord.ui.button(label="Ver Meu Farm", style=discord.ButtonStyle.secondary, custom_id="yuno:farm:panel:mine")
    async def my_farm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Use este painel dentro de um servidor.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        ticket = await self.controller.current_user_ticket(interaction)
        if not ticket:
            await interaction.followup.send("Voce ainda nao tem ticket de farm ativo nesta semana.", ephemeral=True)
            return
        channel_id = ticket.get("channel_id")
        channel = interaction.guild.get_channel(int(channel_id)) if channel_id else None
        link = channel.mention if isinstance(channel, discord.TextChannel) else "canal indisponivel"
        await interaction.followup.send(f"Seu ticket atual: {link}\nProgresso: `{(ticket.get('progress') or {}).get('percent', 0)}%`.", ephemeral=True)

    @discord.ui.button(label="Excluir Ticket", style=discord.ButtonStyle.danger, custom_id="yuno:farm:panel:delete")
    async def delete_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Use este painel dentro de um servidor.", ephemeral=True)
            return
        try:
            config = await self.controller.bot.api.get_farm_ticket_config(interaction.guild.id)
        except httpx.HTTPError:
            await interaction.response.send_message("Sistema de farm nao configurado.", ephemeral=True)
            return
        if not is_farm_admin(interaction.user, config):
            await interaction.response.send_message("Sem permissao para excluir tickets.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        ticket = await self.controller.current_user_ticket(interaction)
        if not ticket:
            await interaction.followup.send("Nao encontrei ticket ativo para excluir nesta semana.", ephemeral=True)
            return
        await self.controller.delete_ticket_channel(interaction.guild, ticket, interaction.user.id, manual=True)
        await interaction.followup.send("Ticket excluido.", ephemeral=True)


class FarmTicketControlView(discord.ui.View):
    def __init__(self, controller: Any):
        super().__init__(timeout=None)
        self.controller = controller

    @discord.ui.button(label="Lancar Farm", style=discord.ButtonStyle.primary, custom_id="yuno:farm:ticket:entry")
    async def entry(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        ticket = await self.controller.ticket_from_interaction(interaction)
        if not ticket:
            return
        if str(interaction.user.id) != str(ticket["user_id"]):
            await interaction.response.send_message("Apenas o dono do ticket pode lancar farm aqui.", ephemeral=True)
            return
        await interaction.response.send_modal(FarmEntryModal(self.controller, ticket))

    @discord.ui.button(label="Ver Comprovantes", style=discord.ButtonStyle.secondary, custom_id="yuno:farm:ticket:proofs")
    async def proofs(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        ticket = await self.controller.ticket_from_interaction(interaction)
        if not ticket or not interaction.guild or not isinstance(interaction.user, discord.Member):
            return
        config = await self.controller.bot.api.get_farm_ticket_config(interaction.guild.id)
        if str(interaction.user.id) != str(ticket["user_id"]) and not is_farm_admin(interaction.user, config):
            await interaction.response.send_message("Sem permissao para ver comprovantes deste ticket.", ephemeral=True)
            return
        await interaction.response.send_message(recent_proofs_text(ticket), ephemeral=True)

    @discord.ui.button(label="Assumir Ticket", style=discord.ButtonStyle.secondary, custom_id="yuno:farm:ticket:assign")
    async def assign(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        ticket = await self.controller.ticket_from_interaction(interaction)
        if not ticket or not await self._ensure_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            updated = await self.controller.bot.api.assign_farm_ticket(int(ticket["id"]), interaction.user.id)
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui assumir este ticket.", ephemeral=True)
            return
        await self.controller.refresh_ticket_channel_message(interaction.guild, updated)
        await self.controller.flush_pending_logs()
        await interaction.followup.send("Ticket assumido.", ephemeral=True)

    @discord.ui.button(label="Revisar", style=discord.ButtonStyle.secondary, custom_id="yuno:farm:ticket:review")
    async def review(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        ticket = await self.controller.ticket_from_interaction(interaction)
        if not ticket or not await self._ensure_admin(interaction):
            return
        await interaction.response.send_modal(FarmReviewModal(self.controller, ticket))

    @discord.ui.button(label="Aprovar Meta", style=discord.ButtonStyle.success, custom_id="yuno:farm:ticket:approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        ticket = await self.controller.ticket_from_interaction(interaction)
        if not ticket or not await self._ensure_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            updated = await self.controller.bot.api.approve_farm_ticket(int(ticket["id"]), interaction.user.id)
        except httpx.HTTPStatusError as exc:
            detail = _detail(exc)
            await interaction.followup.send(f"Nao foi possivel aprovar: {detail}", ephemeral=True)
            return
        await self.controller.refresh_ticket_channel_message(interaction.guild, updated)
        await self.controller.flush_pending_logs()
        await interaction.followup.send("Meta aprovada.", ephemeral=True)

    @discord.ui.button(label="Finalizar Ticket", style=discord.ButtonStyle.danger, custom_id="yuno:farm:ticket:finalize")
    async def finalize(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        ticket = await self.controller.ticket_from_interaction(interaction)
        if not ticket or not await self._ensure_admin(interaction):
            return
        await interaction.response.send_modal(FarmFinalizeModal(self.controller, ticket))

    async def _ensure_admin(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Use dentro de um servidor.", ephemeral=True)
            return False
        try:
            config = await self.controller.bot.api.get_farm_ticket_config(interaction.guild.id)
        except httpx.HTTPError:
            await interaction.response.send_message("Sistema de farm nao configurado.", ephemeral=True)
            return False
        if not is_farm_admin(interaction.user, config):
            await interaction.response.send_message("Sem permissao administrativa para este ticket.", ephemeral=True)
            return False
        return True


async def create_private_ticket_channel(interaction: discord.Interaction, config: dict) -> discord.TextChannel | None:
    guild = interaction.guild
    member = interaction.user
    if not guild or not isinstance(member, discord.Member):
        return None
    category = choose_ticket_category(guild, config.get("category_ids") or [])
    if not category:
        return None

    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True),
    }
    if guild.me:
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True,
            manage_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
        )
    for role_id in config.get("admin_role_ids") or []:
        role = guild.get_role(int(role_id))
        if role:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
                attach_files=True,
            )
    return await guild.create_text_channel(
        build_ticket_channel_name(member),
        category=category,
        overwrites=overwrites,
        reason="Yuno farm ticket semanal",
    )


def ticket_id_from_message(message: discord.Message | None) -> int | None:
    if not message or not message.embeds:
        return None
    footer = message.embeds[0].footer.text or ""
    if "#" not in footer:
        return None
    digits = "".join(char for char in footer.rsplit("#", 1)[-1] if char.isdigit())
    return int(digits) if digits else None


def _detail(exc: httpx.HTTPStatusError) -> str:
    try:
        data = exc.response.json()
        return str(data.get("detail") or "erro inesperado")
    except ValueError:
        return "erro inesperado"
