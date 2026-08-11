import logging

import discord
import httpx
from discord import app_commands
from discord.ext import commands

from yuno_bot import dashboard, diagnostics, server_setup
from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.parceria.repository import ParceriasRepository
from yuno_bot.config import get_settings
from yuno_bot.control_plane import is_control_plane_admin
from yuno_bot.guards import deny
from yuno_bot.modules import ModuleContext, discover_modules, load_modules
from yuno_bot.platform.api import PlatformAPIClient
from yuno_bot.platform.coordinator import PlatformCoordinator
from yuno_bot.platform.registry import discover_ui_modules, verify_backend_manifest
from yuno_bot.platform.router import InteractionRouter, RoutedActionButton, RoutedActionSelect

INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.members = True
INTENTS.message_content = True


class YunoBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="y!", intents=INTENTS)
        self.log = logging.getLogger("yuno")
        self.api = YunoAPI()
        self.platform_api = PlatformAPIClient(
            base_url=self.api.base_url,
            headers=self.api.headers,
        )
        self.platform_ui_registry = discover_ui_modules()
        self.platform_interaction_router = InteractionRouter(
            self.platform_api, self.platform_ui_registry
        )
        self.platform_coordinator = PlatformCoordinator(
            self, self.platform_api, self.platform_ui_registry
        )
        self.parcerias_repository = ParceriasRepository()
        self.module_context: ModuleContext | None = None

    async def setup_hook(self) -> None:
        await self.add_cog(YunoAdminCog(self))
        # Nunca renderizada diretamente -- a mensagem do painel usa payload V2
        # cru (yuno_bot.dashboard.build_payload). Precisa ser registrada aqui
        # para os custom_id sobreviverem a um restart do bot.
        self.add_view(dashboard.PainelDispatcherView(self.api))
        # Dispatcher generico somente para modulos domain-first. As views
        # antigas continuam no loader legado e nao alimentam este registry.
        self.add_dynamic_items(RoutedActionButton, RoutedActionSelect)

        try:
            platform_manifest = await self.platform_api.manifest()
            contract_issues = verify_backend_manifest(
                platform_manifest, self.platform_ui_registry
            )
            if contract_issues:
                self.log.error(
                    "Runtime domain-first degradado: %s", "; ".join(contract_issues)
                )
            else:
                self.log.info("Contratos domain-first do bot e backend compativeis.")
        except httpx.HTTPError:
            # O legado continua disponivel; apenas o runtime novo fica
            # degradado e o diagnostico explicara a incompatibilidade.
            self.log.exception("Nao foi possivel validar contratos da Yuno Platform")

        # Cogs e views persistentes vem do registry. Adicionar um modulo novo e
        # criar a pasta com MODULE = ModuleSpec(...); este arquivo nao muda.
        self.module_context = await load_modules(self)
        self.log.info("Modulos carregados: %s", ", ".join(discover_modules()))
        self.platform_coordinator.start()

        settings = get_settings()
        if settings.control_plane_enabled:
            removed = apply_control_plane_command_policy(self.tree)
            self.log.info(
                "Control Plane ativo. Comandos removidos da arvore: %s",
                ", ".join(removed) or "nenhum",
            )
            # O sync global e o do servidor de teste recebem exatamente a
            # mesma arvore reduzida; isso tambem remove registros antigos.
            await self.tree.sync()
            if settings.discord_test_guild_id:
                guild = discord.Object(id=settings.discord_test_guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
            return
        if settings.discord_test_guild_id:
            guild = discord.Object(id=settings.discord_test_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            return
        await self.tree.sync()

    async def on_ready(self) -> None:
        guilds = ", ".join(f"{guild.name} ({guild.id})" for guild in self.guilds) or "nenhum servidor"
        self.log.info("Yuno conectado como %s. Servidores: %s", self.user, guilds)

    async def close(self) -> None:
        await self.platform_coordinator.stop()
        await super().close()


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
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await deny(interaction, "use dentro de um servidor.")
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        config = await self._carregar_config(interaction)
        if config is None:
            return
        if not is_control_plane_admin(interaction.guild, interaction.user, config):
            await interaction.followup.send(
                "Você não possui permissão para administrar a Central.", ephemeral=True
            )
            return

        bot_member = interaction.guild.me
        if not bot_member or not bot_member.guild_permissions.manage_channels:
            await interaction.followup.send(
                "Eu preciso da permissão Gerenciar Canais para reconciliar a estrutura inicial.",
                ephemeral=True,
            )
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
            saved_setup = await self.bot.api.save_guild_config(
                interaction.guild.id,
                setup_config,
                actor_id=interaction.user.id,
            )
        except httpx.HTTPError:
            await interaction.followup.send(
                "Criei os canais, mas nao consegui salvar a configuracao. Rode o comando de novo "
                "em alguns instantes — nada sera duplicado.",
                ephemeral=True,
            )
            return

        if get_settings().control_plane_enabled:
            central_channel = resultado.channels.get("painel")
            if not isinstance(central_channel, discord.TextChannel):
                await interaction.followup.send(
                    "A estrutura foi salva, mas o canal da Central não pôde ser resolvido.",
                    ephemeral=True,
                )
                return
            states = await dashboard.fetch_control_states(
                self.bot.api,
                interaction.guild.id,
                interaction.user.id,
                platform_api=self.bot.platform_api,
            )
            try:
                message_id = await dashboard.publish_or_update(
                    self.bot,
                    central_channel,
                    saved_setup,
                    control_states=states,
                )
            except discord.HTTPException:
                await interaction.followup.send(
                    "A estrutura foi salva, mas não consegui publicar a Central.", ephemeral=True
                )
                return
            central_config = dashboard.with_dashboard_ref(
                saved_setup,
                channel_id=central_channel.id,
                message_id=message_id,
            )
            try:
                await self.bot.api.save_guild_config(
                    interaction.guild.id,
                    central_config,
                    actor_id=interaction.user.id,
                )
            except httpx.HTTPError:
                await dashboard.rollback_unsaved_dashboard(
                    saved_setup, central_channel, message_id
                )
                await interaction.followup.send(
                    "A Central foi publicada, mas a referência não pôde ser salva. Tente novamente.",
                    ephemeral=True,
                )
                return
            await dashboard.remove_previous_dashboard(
                saved_setup, central_channel, message_id
            )
            await interaction.followup.send(
                f"Central reconciliada e publicada em {central_channel.mention}. {resultado.resumo().capitalize()}.",
                ephemeral=True,
            )
            return

        linhas = [f"Setup concluido: {resultado.resumo()}."]
        if resultado.created:
            linhas.append(f"Criados: {', '.join(resultado.created)}")
        if resultado.adopted:
            linhas.append(f"Adotei os que ja existiam: {', '.join(resultado.adopted)}")
        linhas.append("Pode rodar este comando quantas vezes quiser: nada e duplicado.")
        linhas.append("Próximo passo: rode `/yuno painel` para configurar e publicar os painéis dos módulos.")
        linhas.append("Use `/yuno diagnostico` a qualquer momento para conferir o estado.")

        await interaction.followup.send("\n".join(linhas), ephemeral=True)

    @yuno.command(name="painel", description="Publica ou atualiza o painel administrativo dos modulos")
    @app_commands.default_permissions(manage_guild=True)
    async def yuno_painel(self, interaction: discord.Interaction) -> None:
        if not await self._exigir_admin(interaction):
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        config = await self._carregar_config(interaction)
        if config is None:
            return

        channel_id = server_setup.saved_channel_id(config, "painel")
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send(
                "Canal do painel ainda nao existe. Rode `/yuno configurar` primeiro.", ephemeral=True
            )
            return

        try:
            message_id = await dashboard.publish_or_update(self.bot, channel, config)
        except discord.HTTPException:
            await interaction.followup.send("Nao consegui publicar o painel no canal.", ephemeral=True)
            return

        updated_config = dashboard.with_dashboard_ref(config, channel_id=channel.id, message_id=message_id)
        try:
            await self.bot.api.save_guild_config(interaction.guild.id, updated_config)
        except httpx.HTTPError:
            await interaction.followup.send(
                "Painel publicado, mas nao consegui salvar a referencia da mensagem.", ephemeral=True
            )
            return

        await interaction.followup.send(f"Painel publicado em {channel.mention}.", ephemeral=True)

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


def apply_control_plane_command_policy(tree: app_commands.CommandTree) -> list[str]:
    """Mantem exclusivamente ``/yuno configurar`` na arvore em memoria."""

    removed: list[str] = []
    for command in list(tree.get_commands()):
        if command.name == "yuno":
            continue
        removed.append(f"/{command.name}")
        tree.remove_command(command.name)

    yuno = tree.get_command("yuno")
    if isinstance(yuno, app_commands.Group):
        for command in list(yuno.commands):
            if command.name == "configurar":
                continue
            removed.append(f"/yuno {command.name}")
            yuno.remove_command(command.name)
    return sorted(removed)


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
