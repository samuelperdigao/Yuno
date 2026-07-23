import discord
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.producao.modals import ProducaoRegistrarModal
from yuno_bot.guards import deny, ensure_allowed


class ProducaoCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    producao = app_commands.Group(name="producao", description="Sistema de producao")

    @producao.command(name="registrar", description="Abre o formulario de producao")
    async def registrar(self, interaction: discord.Interaction) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "producao", "registrar")
        if not allowed:
            await deny(interaction, reason)
            return
        await interaction.response.send_modal(ProducaoRegistrarModal(self.bot.api))
