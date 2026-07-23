import discord
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.meta.modals import MetaRegistrarModal
from yuno_bot.guards import deny, ensure_allowed


class MetaCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    meta = app_commands.Group(name="meta", description="Sistema de metas semanais")

    @meta.command(name="registrar", description="Abre o formulario de registro de meta")
    async def registrar(self, interaction: discord.Interaction) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "meta", "registrar")
        if not allowed:
            await deny(interaction, reason)
            return
        await interaction.response.send_modal(MetaRegistrarModal(self.bot.api))
