import discord
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.encomenda.modals import EncomendaCriarModal
from yuno_bot.commands.encomenda.embeds import encomenda_panel_embed
from yuno_bot.commands.encomenda.views import EncomendaPanelView
from yuno_bot.commands.panels import publish_panel_command
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

    @encomenda.command(name="painel", description="Publica ou atualiza o painel fixo de encomendas")
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
            module_key="encomenda",
            setup_channel_key="encomendas",
            embed=encomenda_panel_embed(interaction.guild.name if interaction.guild else None),
            view=EncomendaPanelView(self.bot.api),
            channel=canal,
            command_names=("criar",),
            role_ids=(cargo_autorizado.id,) if cargo_autorizado else (),
            label="Painel de encomendas",
        )
