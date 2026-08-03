import discord
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.ticket.modals import TicketAbrirModal
from yuno_bot.commands.panels import publish_panel_command
from yuno_bot.commands.ticket.embeds import ticket_panel_embed
from yuno_bot.commands.ticket.views import TicketPanelView
from yuno_bot.guards import deny, ensure_allowed


class TicketCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    ticket = app_commands.Group(name="ticket", description="Sistema de tickets")

    @ticket.command(name="abrir", description="Abre o formulario de ticket")
    async def abrir(self, interaction: discord.Interaction) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "ticket", "abrir")
        if not allowed:
            await deny(interaction, reason)
            return
        await interaction.response.send_modal(TicketAbrirModal(self.bot.api))

    @ticket.command(name="painel", description="Publica ou atualiza o painel fixo de tickets")
    @app_commands.default_permissions(manage_guild=True)
    async def painel(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel | None = None,
        cargo_autorizado: discord.Role | None = None,
    ) -> None:
        await publish_panel_command(
            interaction,
            self.bot.api,
            module_key="ticket",
            setup_channel_key="tickets",
            embed=ticket_panel_embed(interaction.guild.name if interaction.guild else None),
            view=TicketPanelView(self.bot.api),
            channel=canal,
            command_names=("abrir",),
            role_ids=(cargo_autorizado.id,) if cargo_autorizado else (),
            label="Painel de tickets",
        )
