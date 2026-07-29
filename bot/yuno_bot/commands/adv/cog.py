import discord
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.adv.modals import AdvModal
from yuno_bot.guards import deny, ensure_allowed


class AdvCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    adv = app_commands.Group(name="adv", description="Sistema de advertências")

    @adv.command(name="aplicar", description="Aplica uma advertência a um membro do servidor")
    async def aplicar(self, interaction: discord.Interaction, membro: discord.Member) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "adv", "aplicar")
        if not allowed:
            await deny(interaction, reason)
            return
        await interaction.response.send_modal(AdvModal(self.bot.api, membro))
