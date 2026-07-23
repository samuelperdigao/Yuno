import discord
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.encomenda.modals import EncomendaCriarModal
from yuno_bot.guards import deny, ensure_allowed


class EncomendaCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    encomenda = app_commands.Group(name="encomenda", description="Sistema de encomendas")

    @encomenda.command(name="criar", description="Abre o formulario de encomenda")
    async def criar(self, interaction: discord.Interaction) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "encomenda", "criar")
        if not allowed:
            await deny(interaction, reason)
            return
        await interaction.response.send_modal(EncomendaCriarModal(self.bot.api))
