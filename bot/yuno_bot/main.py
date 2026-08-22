import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from uuid import uuid4

import discord
import httpx
from discord import app_commands
from discord.ext import commands

from yuno_bot import dashboard, diagnostics, server_setup
from yuno_bot.api_client import YunoAPI
from yuno_bot.config import get_settings
from yuno_bot.control_plane import is_control_plane_admin
from yuno_bot.guards import deny
from yuno_bot.modules import ModuleContext, discover_modules, load_modules
from yuno_bot.platform.api import PlatformAPIClient
from yuno_bot.platform.contracts import ActorContext
from yuno_bot.platform.coordinator import PlatformCoordinator
from yuno_bot.platform.registry import discover_ui_modules, verify_backend_manifest
from yuno_bot.platform.router import (
    InteractionRouter,
    RoutedActionButton,
    RoutedActionSelect,
    RoutedChannelSelect,
    RoutedRoleSelect,
)

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
        self.module_context: ModuleContext | None = None
        self._registration_recovery_task: asyncio.Task | None = None
        self._tags_periodic_task: asyncio.Task | None = None
        self._meta_recovery_task: asyncio.Task | None = None
        self._tag_role_debounce: dict[int, asyncio.Task] = {}
        self._tag_hierarchy_fingerprints: dict[int, str] = {}
        self._central_refreshed_guilds: set[int] = set()

    async def setup_hook(self) -> None:
        await self.add_cog(YunoAdminCog(self))
        # Dispatcher generico somente para modulos domain-first. As views
        # antigas continuam no loader legado e nao alimentam este registry.
        self.add_dynamic_items(
            RoutedActionButton,
            RoutedActionSelect,
            RoutedChannelSelect,
            RoutedRoleSelect,
            dashboard.CentralModuleSelect,
            dashboard.CentralActionButton,
            dashboard.CentralActionSelect,
            dashboard.CentralChannelSelect,
            dashboard.CentralRoleSelect,
        )

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
        if self.platform_ui_registry.get("registration") is not None:
            self._registration_recovery_task = asyncio.create_task(
                self._run_registration_recovery_sweeper(),
                name="yuno-registration-recovery-sweeper",
            )
        if self.platform_ui_registry.get("tags") is not None:
            self._tags_periodic_task = asyncio.create_task(
                self._run_tags_periodic_sweeper(),
                name="yuno-tags-periodic-sweeper",
            )
        if self.platform_ui_registry.get("meta") is not None:
            self._meta_recovery_task = asyncio.create_task(
                self._run_meta_recovery_sweeper(),
                name="yuno-meta-recovery-sweeper",
            )

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
        for guild in self.guilds:
            self._tag_hierarchy_fingerprints[guild.id] = self._role_hierarchy_fingerprint(guild)
        if get_settings().control_plane_enabled:
            await self.refresh_published_central_once()

    async def refresh_published_central_once(self) -> None:
        """Reconciliacao segura: edita somente a mensagem ja registrada."""

        if self.user is None:
            return
        for guild in self.guilds:
            if guild.id in self._central_refreshed_guilds:
                continue
            try:
                config = await self.api.get_guild_config(guild.id)
                states = await dashboard.fetch_control_states(
                    self.api,
                    guild.id,
                    self.user.id,
                    platform_api=self.platform_api,
                )
                refreshed = await dashboard.refresh_existing(
                    self,
                    guild,
                    config,
                    control_states=states,
                )
                if refreshed:
                    self._central_refreshed_guilds.add(guild.id)
                    self.log.info("Central navegavel atualizada na guild %s", guild.id)
            except Exception:
                self.log.exception("Falha ao atualizar a Central publicada na guild %s", guild.id)

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.type is not discord.InteractionType.component:
            return
        custom_id = str((interaction.data or {}).get("custom_id") or "")
        if not custom_id.startswith("yuno:"):
            return
        self.log.info(
            "Components V2 recebido guild=%s interaction=%s custom_id=%s fase=dispatch",
            interaction.guild_id,
            interaction.id,
            custom_id,
        )
        try:
            if await dashboard.dispatch_components_v2(interaction):
                return
            await self.platform_interaction_router.dispatch_components_v2(interaction)
        except Exception:
            self.log.exception(
                "Falha no dispatch Components V2 guild=%s interaction=%s custom_id=%s fase=dispatch",
                interaction.guild_id,
                interaction.id,
                custom_id,
            )
            message = "Nao consegui concluir esta acao. Tente novamente."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)

    def _system_actor(self, guild_id: int, correlation_id: str) -> ActorContext | None:
        if self.user is None:
            return None
        return ActorContext(
            guild_id=guild_id,
            user_id=self.user.id,
            role_ids=(),
            discord_permissions=(),
            channel_id=None,
            category_id=None,
            actor_type="system",
            is_guild_owner=False,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _role_hierarchy_fingerprint(guild: discord.Guild) -> str:
        return hashlib.sha256(
            ",".join(str(role.id) for role in guild.roles).encode("ascii")
        ).hexdigest()

    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if self.platform_ui_registry.get("tags") is None or after.bot:
            return
        roles_changed = tuple(role.id for role in before.roles) != tuple(role.id for role in after.roles)
        nickname_changed = before.nick != after.nick
        if not roles_changed and not nickname_changed:
            return
        correlation = f"member-update:{after.guild.id}:{after.id}:{uuid4().hex}"
        actor = self._system_actor(after.guild.id, correlation)
        if actor is None:
            return
        fingerprint = hashlib.sha256(
            (",".join(str(role.id) for role in after.roles) + "|" + (after.nick or "")).encode("utf-8")
        ).hexdigest()
        try:
            await self.platform_api.tags_request_member(
                after.guild.id,
                {
                    "discord_user_id": str(after.id),
                    "observed_fingerprint": fingerprint,
                    "reason": "roles_changed" if roles_changed else "nickname_changed",
                },
                actor=actor,
            )
        except httpx.HTTPError:
            self.log.exception(
                "Falha ao solicitar Tags para membro %s na guild %s", after.id, after.guild.id
            )

    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        del before
        guild = after.guild
        current = self._role_hierarchy_fingerprint(guild)
        previous = self._tag_hierarchy_fingerprints.get(guild.id)
        self._tag_hierarchy_fingerprints[guild.id] = current
        if previous is not None and previous != current:
            self._debounce_tag_run(guild.id, "hierarchy_changed")

    async def on_guild_role_delete(self, role: discord.Role) -> None:
        self._tag_hierarchy_fingerprints[role.guild.id] = self._role_hierarchy_fingerprint(role.guild)
        self._debounce_tag_run(role.guild.id, "role_deleted")

    def _debounce_tag_run(self, guild_id: int, reason: str) -> None:
        if self.platform_ui_registry.get("tags") is None:
            return
        previous = self._tag_role_debounce.pop(guild_id, None)
        if previous is not None:
            previous.cancel()
        self._tag_role_debounce[guild_id] = asyncio.create_task(
            self._create_debounced_tag_run(guild_id, reason),
            name=f"yuno-tags-role-debounce:{guild_id}",
        )

    async def _create_debounced_tag_run(self, guild_id: int, reason: str) -> None:
        try:
            await asyncio.sleep(3)
            correlation = f"role-event:{guild_id}:{uuid4().hex}"
            actor = self._system_actor(guild_id, correlation)
            if actor is None:
                return
            await self.platform_api.tags_create_run(
                guild_id, {"mode": "effective", "reason": reason}, actor=actor
            )
        except asyncio.CancelledError:
            return
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in {403, 409}:
                self.log.exception("Falha ao criar run de Tags na guild %s", guild_id)
        except httpx.HTTPError:
            self.log.exception("Falha ao criar run de Tags na guild %s", guild_id)
        finally:
            self._tag_role_debounce.pop(guild_id, None)

    async def on_raw_member_remove(self, payload: discord.RawMemberRemoveEvent) -> None:
        if self.user is None:
            return
        user_id = payload.user.id
        correlation = f"member-remove:{payload.guild_id}:{user_id}"
        actor = self._system_actor(payload.guild_id, correlation)
        if actor is None:
            return
        try:
            if self.platform_ui_registry.get("registration") is not None:
                await self.platform_api.registration_deactivate_member(
                    payload.guild_id, user_id, actor=actor
                )
            if self.platform_ui_registry.get("tags") is not None:
                await self.platform_api.tags_cancel_member(
                    payload.guild_id, user_id, actor=actor
                )
            if self.platform_ui_registry.get("meta") is not None:
                await self.platform_api.meta_remove_member(
                    payload.guild_id, user_id, correlation
                )
        except httpx.HTTPError:
            self.log.exception(
                "Falha ao inativar cadastro do membro %s na guild %s",
                user_id,
                payload.guild_id,
            )

    async def sweep_registration_recovery_once(self) -> None:
        now = datetime.now(timezone.utc)
        for guild in self.guilds:
            try:
                stale = await self.platform_api.registration_stale(guild.id)
                for request in stale:
                    await self.platform_api.schedule_task(
                        guild.id,
                        "registration",
                        {
                            "job_key": "registration.processing.recover",
                            "resource_type": "registration_request",
                            "resource_id": request["id"],
                            "payload": {"request_id": request["id"]},
                            "due_at": now.isoformat(),
                            "idempotency_key": (
                                f"stale:{request['id']}:{request['revision']}"
                            ),
                            "correlation_id": f"registration-sweeper:{guild.id}",
                            "max_attempts": 10,
                        },
                    )
            except Exception:
                self.log.exception(
                    "Falha ao agendar recuperacao de claims do Registro na guild %s",
                    guild.id,
                )

    async def _run_registration_recovery_sweeper(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            await self.sweep_registration_recovery_once()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                return

    async def sweep_tags_periodic_once(self) -> None:
        day_key = datetime.now(timezone.utc).date().isoformat()
        for guild in self.guilds:
            actor = self._system_actor(
                guild.id, f"tags-periodic-ensure:{guild.id}:{day_key}"
            )
            if actor is None:
                return
            try:
                await self.platform_api.tags_ensure_periodic(
                    guild.id, day_key, actor=actor
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in {403, 409}:
                    self.log.exception(
                        "Falha ao garantir reconciliacao periodica de Tags na guild %s",
                        guild.id,
                    )
            except httpx.HTTPError:
                self.log.exception(
                    "Falha ao garantir reconciliacao periodica de Tags na guild %s",
                    guild.id,
                )

    async def _run_tags_periodic_sweeper(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            await self.sweep_tags_periodic_once()
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                return

    async def sweep_meta_recovery_once(self) -> None:
        boundary = datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat()
        for guild in self.guilds:
            try:
                await self.platform_api.meta_recovery(
                    guild.id, f"meta-recovery:{guild.id}:{boundary}"
                )
            except httpx.HTTPError:
                self.log.exception(
                    "Falha ao reconciliar transicoes de Metas na guild %s", guild.id
                )

    async def _run_meta_recovery_sweeper(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            await self.sweep_meta_recovery_once()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                return

    async def close(self) -> None:
        for task in tuple(self._tag_role_debounce.values()):
            task.cancel()
        if self._tag_role_debounce:
            await asyncio.gather(*self._tag_role_debounce.values(), return_exceptions=True)
        self._tag_role_debounce.clear()
        if self._meta_recovery_task is not None:
            self._meta_recovery_task.cancel()
            try:
                await self._meta_recovery_task
            except asyncio.CancelledError:
                pass
            self._meta_recovery_task = None
        if self._tags_periodic_task is not None:
            self._tags_periodic_task.cancel()
            try:
                await self._tags_periodic_task
            except asyncio.CancelledError:
                pass
            self._tags_periodic_task = None
        if self._registration_recovery_task is not None:
            self._registration_recovery_task.cancel()
            try:
                await self._registration_recovery_task
            except asyncio.CancelledError:
                pass
            self._registration_recovery_task = None
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

    @yuno.command(name="configurar", description="Publica ou reconcilia a Central do Yuno neste canal")
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

        if get_settings().control_plane_enabled:
            central_channel = interaction.channel
            if not isinstance(central_channel, discord.TextChannel):
                await interaction.followup.send(
                    "Use este comando em um canal de texto onde a Central deve ser publicada.",
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
                    config,
                    control_states=states,
                )
            except discord.HTTPException:
                await interaction.followup.send(
                    "Não consegui publicar a Central neste canal.", ephemeral=True
                )
                return
            central_config = dashboard.with_dashboard_ref(
                config,
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
                    config, central_channel, message_id
                )
                await interaction.followup.send(
                    "A Central foi publicada, mas a referência não pôde ser salva. Tente novamente.",
                    ephemeral=True,
                )
                return
            await dashboard.remove_previous_dashboard(
                config, central_channel, message_id
            )
            await interaction.followup.send(
                f"Central reconciliada e publicada em {central_channel.mention}.",
                ephemeral=True,
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
