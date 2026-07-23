import discord
from discord import app_commands
from discord.ext import commands

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.ausencia.cog import AusenciaCog
from yuno_bot.commands.encomenda.cog import EncomendaCog
from yuno_bot.commands.meta.cog import MetaCog
from yuno_bot.commands.parceria.cog import ParceriaCog
from yuno_bot.commands.producao.cog import ProducaoCog
from yuno_bot.commands.radio.cog import RadioCog
from yuno_bot.commands.set.cog import SetCog
from yuno_bot.commands.set.views import SetPanelView
from yuno_bot.commands.ticket.cog import TicketCog
from yuno_bot.config import get_settings
from yuno_bot.guards import deny
from yuno_bot.server_setup import SETUP_LOG_CHANNELS, build_setup_config, ensure_setup_channels


INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.members = True
INTENTS.message_content = True


class YunoBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="y!", intents=INTENTS)
        self.api = YunoAPI()

    async def setup_hook(self) -> None:
        self.add_view(SetPanelView(self.api))
        await self.add_cog(YunoAdminCog(self))
        await self.add_cog(SetCog(self))
        await self.add_cog(MetaCog(self))
        await self.add_cog(TicketCog(self))
        await self.add_cog(ParceriaCog(self))
        await self.add_cog(EncomendaCog(self))
        await self.add_cog(AusenciaCog(self))
        await self.add_cog(RadioCog(self))
        await self.add_cog(ProducaoCog(self))

        settings = get_settings()
        if settings.discord_test_guild_id:
            guild = discord.Object(id=settings.discord_test_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            return
        await self.tree.sync()

    async def on_ready(self) -> None:
        guilds = ", ".join(f"{guild.name} ({guild.id})" for guild in self.guilds) or "nenhum servidor"
        print(f"Yuno conectado como {self.user}. Servidores: {guilds}")


class YunoAdminCog(commands.Cog):
    def __init__(self, bot: YunoBot) -> None:
        self.bot = bot

    yuno = app_commands.Group(name="yuno", description="Comandos administrativos do Yuno")

    @yuno.command(name="status", description="Verifica se o servidor possui licenca ativa")
    async def yuno_status(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await deny(interaction, "use dentro de um servidor.")
            return
        data = await self.bot.api.validate_license(interaction.guild.id)
        if data["allowed"]:
            await interaction.response.send_message("Licenca ativa. O Yuno esta pronto para operar neste servidor.", ephemeral=True)
            return
        await interaction.response.send_message("Este servidor ainda nao possui licenca ativa.", ephemeral=True)

    @yuno.command(name="configurar", description="Cria as categorias e canais padrao do Yuno neste servidor")
    @app_commands.default_permissions(manage_guild=True)
    async def yuno_configurar(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await deny(interaction, "use dentro de um servidor.")
            return

        if not (
            interaction.user.guild_permissions.manage_guild
            or interaction.user.guild_permissions.administrator
            or interaction.guild.owner_id == interaction.user.id
        ):
            await deny(interaction, "voce precisa ter permissao de gerenciar servidor.")
            return

        bot_member = interaction.guild.me
        if not bot_member or not bot_member.guild_permissions.manage_channels:
            await deny(interaction, "eu preciso da permissao Gerenciar Canais para criar a estrutura inicial.")
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        license_status = await self.bot.api.validate_license(interaction.guild.id)
        if not license_status["allowed"]:
            await interaction.followup.send("Este servidor ainda nao possui licenca ativa.", ephemeral=True)
            return

        current_config = await self.bot.api.get_guild_config(interaction.guild.id)
        categories, channels, created = await ensure_setup_channels(interaction.guild)
        setup_config = build_setup_config(
            current_config=current_config,
            guild=interaction.guild,
            categories=categories,
            channels=channels,
        )
        await self.bot.api.save_guild_config(interaction.guild.id, setup_config)

        created_text = ", ".join(created) if created else "nenhuma categoria ou canal novo; reutilizei a estrutura existente"
        log_mentions = ", ".join(channels[f"log_{module}"].mention for module in SETUP_LOG_CHANNELS if f"log_{module}" in channels)
        await interaction.followup.send(
            "\n".join(
                [
                    "Setup inicial concluido.",
                    f"Criado/reutilizado: {created_text}.",
                    f"Logs por sistema: {log_mentions}",
                    f"Set: {channels['set_solicitar'].mention} e {channels['set_aprovacao'].mention}",
                    f"Operacao: {channels['metas'].mention}, {channels['tickets'].mention}, {channels['parcerias'].mention}, {channels['encomendas'].mention}, {channels['ausencias'].mention}, {channels['radio'].mention}, {channels['producao'].mention}",
                    "As permissoes, canais dos modais e logs foram salvos no painel/API.",
                ]
            ),
            ephemeral=True,
        )


def main() -> None:
    settings = get_settings()
    bot = YunoBot()
    bot.run(settings.discord_bot_token)


if __name__ == "__main__":
    main()
