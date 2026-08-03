import discord
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.producao.modals import ProducaoRegistrarModal
from yuno_bot.commands.panels import publish_panel_command
from yuno_bot.commands.producao.embeds import producao_panel_embed
from yuno_bot.commands.producao.views import ProducaoPanelView
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

    @producao.command(name="painel", description="Publica ou atualiza o painel fixo de produção")
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
            module_key="producao",
            setup_channel_key="producao",
            embed=producao_panel_embed(interaction.guild.name if interaction.guild else None),
            view=ProducaoPanelView(self.bot.api),
            channel=canal,
            command_names=("registrar",),
            role_ids=(cargo_autorizado.id,) if cargo_autorizado else (),
            label="Painel de produção",
        )
