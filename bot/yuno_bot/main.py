import logging

import discord
import httpx
from discord import app_commands
from discord.ext import commands

from yuno_bot import diagnostics, server_setup
from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.parceria.repository import ParceriasRepository
from yuno_bot.config import get_settings
from yuno_bot.guards import deny
from yuno_bot.modules import ModuleContext, discover_modules, load_modules

INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.members = True
INTENTS.message_content = True


class YunoBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="y!", intents=INTENTS)
        self.log = logging.getLogger("yuno")
        self.api = YunoAPI()
        self.parcerias_repository = ParceriasRepository()
        self.module_context: ModuleContext | None = None

    async def setup_hook(self) -> None:
        await self.add_cog(YunoAdminCog(self))

        # Cogs e views persistentes vem do registry. Adicionar um modulo novo e
        # criar a pasta com MODULE = ModuleSpec(...); este arquivo nao muda.
        self.module_context = await load_modules(self)
        self.log.info("Modulos carregados: %s", ", ".join(discover_modules()))

        settings = get_settings()
        if settings.discord_test_guild_id:
            guild = discord.Object(id=settings.discord_test_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            return
        await self.tree.sync()

    async def on_ready(self) -> None:
        guilds = ", ".join(f"{guild.name} ({guild.id})" for guild in self.guilds) or "nenhum servidor"
        self.log.info("Yuno conectado como %s. Servidores: %s", self.user, guilds)


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
            await interaction.response.send_message(
                "Licenca ativa. O Yuno esta pronto para operar neste servidor.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "Este servidor ainda nao possui licenca ativa.", ephemeral=True
        )

    @yuno.command(name="configurar", description="Cria ou reconcilia a estrutura do Yuno neste servidor")
    @app_commands.default_permissions(manage_guild=True)
    async def yuno_configurar(self, interaction: discord.Interaction) -> None:
        if not await self._exigir_admin(interaction):
            return

        bot_member = interaction.guild.me
        if not bot_member or not bot_member.guild_permissions.manage_channels:
            await deny(
                interaction,
                "eu preciso da permissao Gerenciar Canais para criar a estrutura inicial. "
                "Use `/yuno diagnostico` para ver tudo que falta.",
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        config = await self._carregar_config(interaction)
        if config is None:
            return

        # A config atual entra como entrada: e dela que saem os IDs ja salvos, o
        # que torna o comando idempotente e seguro de rodar quantas vezes quiser.
        resultado = await server_setup.ensure_setup_channels(interaction.guild, config)
        setup_config = server_setup.build_setup_config(
            current_config=config,
            guild=interaction.guild,
            categories=resultado.categories,
            channels=resultado.channels,
        )
        try:
            await self.bot.api.save_guild_config(interaction.guild.id, setup_config)
        except httpx.HTTPError:
            await interaction.followup.send(
                "Criei os canais, mas nao consegui salvar a configuracao. Rode o comando de novo "
                "em alguns instantes — nada sera duplicado.",
                ephemeral=True,
            )
            return

        linhas = [f"Setup concluido: {resultado.resumo()}."]
        if resultado.created:
            linhas.append(f"Criados: {', '.join(resultado.created)}")
        if resultado.adopted:
            linhas.append(f"Adotei os que ja existiam: {', '.join(resultado.adopted)}")
        linhas.append("Pode rodar este comando quantas vezes quiser: nada e duplicado.")
        linhas.append("Use `/yuno diagnostico` a qualquer momento para conferir o estado.")

        await interaction.followup.send("\n".join(linhas), ephemeral=True)

    @yuno.command(name="diagnostico", description="Mostra o que ja esta configurado e o que falta")
    @app_commands.default_permissions(manage_guild=True)
    async def yuno_diagnostico(self, interaction: discord.Interaction) -> None:
        if not await self._exigir_admin(interaction):
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        licenca = await self.bot.api.validate_license(interaction.guild.id)
        config = await self._carregar_config(interaction, exigir_licenca=False, force=True) or {}

        relatorio = diagnostics.diagnose(
            interaction.guild, config, licenca_ativa=bool(licenca.get("allowed"))
        )
        await interaction.followup.send(
            embed=diagnostics.diagnostic_embed(relatorio, interaction.guild.name), ephemeral=True
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    async def _exigir_admin(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await deny(interaction, "use dentro de um servidor.")
            return False
        if not (
            interaction.user.guild_permissions.manage_guild
            or interaction.user.guild_permissions.administrator
            or interaction.guild.owner_id == interaction.user.id
        ):
            await deny(interaction, "voce precisa ter permissao de gerenciar servidor.")
            return False
        return True

    async def _carregar_config(
        self, interaction: discord.Interaction, *, exigir_licenca: bool = True, force: bool = False
    ) -> dict | None:
        """Busca a guild config traduzindo erro de rede em mensagem util.

        Retorna None quando ja respondeu ao usuario. O 403 e tratado a parte
        porque significa licenca inativa, e o cliente precisa saber que o
        problema e comercial, nao tecnico.
        """
        try:
            return await self.bot.api.get_guild_config(interaction.guild.id, force=force)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                if not exigir_licenca:
                    return {}
                await interaction.followup.send(
                    "Este servidor ainda nao possui licenca ativa.", ephemeral=True
                )
                return None
            await interaction.followup.send(
                "Nao consegui carregar a configuracao do servidor.", ephemeral=True
            )
            return None
        except httpx.HTTPError:
            await interaction.followup.send(
                "Nao consegui falar com a API do Yuno. Tente de novo em alguns instantes.",
                ephemeral=True,
            )
            return None


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    settings = get_settings()
    bot = YunoBot()
    bot.run(settings.discord_bot_token, log_handler=None)


if __name__ == "__main__":
    main()
