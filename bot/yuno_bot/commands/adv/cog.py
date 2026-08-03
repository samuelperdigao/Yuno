import discord
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.adv.modals import AdvModal
from yuno_bot.commands.adv.embeds import adv_panel_embed
from yuno_bot.commands.adv.views import AdvPanelView
from yuno_bot.commands.panels import publish_panel_command
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

    @adv.command(name="painel", description="Publica ou atualiza o painel fixo de advertências")
    @app_commands.default_permissions(manage_guild=True)
    async def painel(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel | None = None,
        cargo_responsavel: discord.Role | None = None,
    ) -> None:
        await publish_panel_command(
            interaction,
            self.bot.api,
            module_key="adv",
            setup_channel_key="adv",
            embed=adv_panel_embed(),
            view=AdvPanelView(self.bot.api),
            channel=canal,
            command_names=("aplicar",),
            role_ids=(cargo_responsavel.id,) if cargo_responsavel else (),
            label="Painel de advertências",
        )
