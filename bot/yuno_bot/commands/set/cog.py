import discord
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.set.modals import SetAprovarModal, SetReprovarModal, SetSolicitarModal
from yuno_bot.guards import deny, ensure_allowed


class SetCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    set_group = app_commands.Group(name="set", description="Sistema de set")

    @set_group.command(name="solicitar", description="Abre o formulario de solicitacao de set")
    async def solicitar(self, interaction: discord.Interaction) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "set", "solicitar")
        if not allowed:
            await deny(interaction, reason)
            return
        await interaction.response.send_modal(SetSolicitarModal(self.bot.api))

    @set_group.command(name="aprovar", description="Abre o formulario de aprovacao de set")
    async def aprovar(self, interaction: discord.Interaction) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "set", "aprovar")
        if not allowed:
            await deny(interaction, reason)
            return
        await interaction.response.send_modal(SetAprovarModal(self.bot.api))

    @set_group.command(name="reprovar", description="Abre o formulario de reprovacao de set")
    async def reprovar(self, interaction: discord.Interaction) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "set", "reprovar")
        if not allowed:
            await deny(interaction, reason)
            return
        await interaction.response.send_modal(SetReprovarModal(self.bot.api))
