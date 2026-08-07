import discord
import httpx
from discord import app_commands
from discord.ext import commands, tasks

from yuno_bot.commands.farm_tickets.embeds import farm_goal_embed, farm_log_embed, farm_panel_embed, farm_ranking_embed, farm_ticket_embed
from yuno_bot.commands.farm_tickets.helpers import MemberFolderError, current_week_id, member_has_any_role, parse_discord_ids, resolve_or_create_member_folder
from yuno_bot.commands.farm_tickets.views import FarmPanelView, FarmTicketControlView, create_private_ticket_channel, ticket_id_from_message
from yuno_bot.commands.meta.embeds import parse_meta_definition
from yuno_bot.commands.panels import publish_or_update_panel, remove_previous_panel, rollback_unsaved_panel, with_panel_config
from yuno_bot.guards import deny, ensure_allowed
from yuno_bot.config import setup_required_message


class FarmTicketsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.auto_finalize_old_tickets.start()
        self.replay_logs_and_cleanup.start()

    def cog_unload(self) -> None:
        self.auto_finalize_old_tickets.cancel()
        self.replay_logs_and_cleanup.cancel()

    farm = app_commands.Group(name="farm", description="Sistema semanal de farm")

    @farm.command(name="ranking", description="Mostra quem mais entregou farm na semana atual")
    async def ranking(self, interaction: discord.Interaction) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "farm_tickets", "ranking")
        if not allowed:
            await deny(interaction, reason)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.show_weekly_ranking(interaction)

    @app_commands.command(name="setup_farm_tickets", description="Configura o sistema semanal de tickets de farm")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_farm_tickets(
        self,
        interaction: discord.Interaction,
        categorias_tickets: str,
        cargos_admin: str,
        cargos_participantes: str,
        canal_log: discord.TextChannel,
        canal_painel: discord.TextChannel,
        categoria_pastas: discord.CategoryChannel,
    ) -> None:
        if not await self._ensure_setup_admin(interaction):
            return
        if not interaction.guild:
            await deny(interaction, "use dentro de um servidor.")
            return

        category_ids = parse_discord_ids(categorias_tickets)
        admin_role_ids = parse_discord_ids(cargos_admin)
        participant_role_ids = parse_discord_ids(cargos_participantes)
        categories = [interaction.guild.get_channel(category_id) for category_id in category_ids]
        admin_roles = [interaction.guild.get_role(role_id) for role_id in admin_role_ids]
        participant_roles = [interaction.guild.get_role(role_id) for role_id in participant_role_ids]
        if not category_ids or any(not isinstance(category, discord.CategoryChannel) for category in categories):
            await interaction.response.send_message("Informe categorias validas em `categorias_tickets`.", ephemeral=True)
            return
        if not admin_role_ids or any(role is None for role in admin_roles):
            await interaction.response.send_message("Informe cargos administrativos validos em `cargos_admin`.", ephemeral=True)
            return
        if not participant_role_ids or any(role is None for role in participant_roles):
            await interaction.response.send_message(
                "Informe cargos participantes validos em `cargos_participantes` — sem isso, ninguem consegue abrir ticket.",
                ephemeral=True,
            )
            return

        payload = {
            "category_ids": [str(category_id) for category_id in category_ids],
            "admin_role_ids": [str(role_id) for role_id in admin_role_ids],
            "log_channel_id": str(canal_log.id),
            "panel_channel_id": str(canal_painel.id),
            "folders_category_id": str(categoria_pastas.id),
            "participant_role_ids": [str(role_id) for role_id in participant_role_ids],
        }
        await interaction.response.defer(ephemeral=True)
        try:
            await self.bot.api.save_farm_ticket_config(interaction.guild.id, payload)
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui salvar a configuracao de tickets de farm.", ephemeral=True)
            return
        await interaction.followup.send("Sistema de tickets de farm configurado.", ephemeral=True)

    @app_commands.command(name="setup_farm_meta", description="Define a meta de farm da semana atual")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_farm_meta(self, interaction: discord.Interaction, definicao: str) -> None:
        if not await self._ensure_setup_admin(interaction):
            return
        if not interaction.guild:
            await deny(interaction, "use dentro de um servidor.")
            return
        try:
            items = parse_meta_definition(definicao, max_items=5)
        except ValueError as exc:
            await interaction.response.send_message(f"Erro na meta: {exc}", ephemeral=True)
            return
        week_id = current_week_id()
        await interaction.response.defer(ephemeral=True)
        try:
            goal = await self.bot.api.save_farm_weekly_goal(
                interaction.guild.id,
                {"week_id": week_id, "items": items, "created_by": str(interaction.user.id)},
            )
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui salvar a meta semanal de farm.", ephemeral=True)
            return
        await interaction.followup.send(embed=farm_goal_embed(goal["week_id"], goal["items"], interaction.guild.name), ephemeral=True)

    @app_commands.command(name="setup_farm_painel", description="Publica o painel fixo de farm")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_farm_painel(self, interaction: discord.Interaction) -> None:
        if not await self._ensure_setup_admin(interaction):
            return
        if not interaction.guild:
            await deny(interaction, "use dentro de um servidor.")
            return
        await interaction.response.defer(ephemeral=True)
        try:
            config = await self.bot.api.get_farm_ticket_config(interaction.guild.id)
            guild_config = await self.bot.api.get_guild_config(interaction.guild.id, force=True)
        except httpx.HTTPError:
            await interaction.followup.send(
                setup_required_message(
                    "Farm Tickets",
                    "Configure primeiro com `/setup_farm_tickets`.",
                ),
                ephemeral=True,
            )
            return
        channel = interaction.guild.get_channel(int(config["panel_channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send("Canal do painel configurado nao esta acessivel.", ephemeral=True)
            return
        message = await publish_or_update_panel(
            channel,
            guild_config,
            module_key="farm_tickets",
            embed=farm_panel_embed(interaction.guild.name),
            view=FarmPanelView(self),
        )
        if message is None:
            await interaction.followup.send("Nao consegui publicar o painel de farm.", ephemeral=True)
            return
        updated_config = with_panel_config(
            guild_config,
            module_key="farm_tickets",
            channel_id=channel.id,
            message_id=message.id,
            command_names=("abrir", "ver", "ranking", "excluir"),
        )
        try:
            await self.bot.api.save_guild_config(interaction.guild.id, updated_config)
        except httpx.HTTPError:
            await rollback_unsaved_panel(guild_config, message, module_key="farm_tickets")
            await interaction.followup.send(
                "Painel publicado, mas nao consegui salvar a referencia da mensagem.", ephemeral=True
            )
            return
        await remove_previous_panel(
            guild_config,
            channel,
            module_key="farm_tickets",
            message_id=message.id,
        )
        await interaction.followup.send(f"Painel de farm publicado e fixado em {channel.mention}.", ephemeral=True)

    async def show_weekly_ranking(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.followup.send("Use dentro de um servidor.", ephemeral=True)
            return
        try:
            data = await self.bot.api.get_farm_weekly_ranking(
                interaction.guild.id,
                current_week_id(),
                limit=10,
            )
        except httpx.HTTPStatusError as exc:
            await interaction.followup.send(_detail(exc), ephemeral=True)
            return
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui carregar o ranking agora.", ephemeral=True)
            return
        await interaction.followup.send(
            embed=farm_ranking_embed(data, interaction.guild.name),
            ephemeral=True,
        )

    async def open_weekly_ticket(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.followup.send("Use dentro de um servidor.", ephemeral=True)
            return
        week_id = current_week_id()
        try:
            config = await self.bot.api.get_farm_ticket_config(interaction.guild.id)
            await self.bot.api.get_farm_weekly_goal(interaction.guild.id, week_id)
        except httpx.HTTPStatusError as exc:
            await interaction.followup.send(_detail(exc), ephemeral=True)
            return
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui verificar a configuracao de farm.", ephemeral=True)
            return

        if not member_has_any_role(interaction.user, config.get("participant_role_ids") or []):
            await interaction.followup.send("Seu cargo nao participa do farm semanal.", ephemeral=True)
            return

        folders_category_id = config.get("folders_category_id")
        if not folders_category_id:
            await interaction.followup.send("A categoria de pastas individuais nao esta configurada.", ephemeral=True)
            return
        try:
            folder = await resolve_or_create_member_folder(
                interaction.guild,
                interaction.user,
                int(folders_category_id),
                config.get("admin_role_ids") or [],
            )
        except (MemberFolderError, ValueError) as exc:
            await interaction.followup.send(
                f"Nao foi possivel identificar sua pasta individual: {exc}\n"
                "Procure a administracao para regularizar a pasta antes de abrir o ticket.",
                ephemeral=True,
            )
            return

        try:
            reservation = await self.bot.api.reserve_farm_ticket(
                interaction.guild.id,
                {
                    "week_id": week_id,
                    "user_id": str(interaction.user.id),
                    "member_name": interaction.user.display_name,
                    "folder_channel_id": str(folder.channel_id),
                    "folder_slot": folder.slot,
                    "game_id": folder.game_id,
                    "folder_nickname": folder.nickname,
                },
            )
        except httpx.HTTPStatusError as exc:
            await interaction.followup.send(_detail(exc), ephemeral=True)
            return
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui reservar seu ticket agora.", ephemeral=True)
            return

        ticket = reservation["ticket"]
        if ticket.get("channel_id"):
            channel = interaction.guild.get_channel(int(ticket["channel_id"]))
            if isinstance(channel, discord.TextChannel):
                await interaction.followup.send(f"Voce ja tem um ticket ativo: {channel.mention}", ephemeral=True)
                return

        channel = None
        try:
            channel = await create_private_ticket_channel(interaction, config, folder)
            if not channel:
                raise RuntimeError("sem categoria disponivel")
            message = await channel.send(
                content=interaction.user.mention,
                embed=farm_ticket_embed(ticket, interaction.user),
                view=FarmTicketControlView(self),
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
            try:
                await message.pin(reason="Controle do farm semanal")
            except discord.HTTPException:
                pass
            ticket = await self.bot.api.set_farm_ticket_channel(
                int(ticket["id"]),
                {"channel_id": str(channel.id), "panel_message_id": str(message.id), "status": "aberto"},
            )
            await message.edit(embed=farm_ticket_embed(ticket, interaction.user), view=FarmTicketControlView(self))
        except Exception:
            if channel:
                try:
                    await channel.delete(reason="Falha ao criar ticket de farm")
                except discord.HTTPException:
                    pass
            try:
                await self.bot.api.cancel_farm_ticket(int(ticket["id"]), {"actor_id": str(interaction.user.id), "action": "cancel", "payload": {"reason": "falha ao criar canal"}})
            except httpx.HTTPError:
                pass
            await interaction.followup.send("Nao consegui criar seu canal privado de farm.", ephemeral=True)
            return

        await self.flush_pending_logs()
        await interaction.followup.send(f"Ticket criado: {channel.mention}", ephemeral=True)

    async def current_user_ticket(self, interaction: discord.Interaction) -> dict | None:
        if not interaction.guild:
            return None
        try:
            return await self.bot.api.get_active_farm_ticket(guild_id=interaction.guild.id, week_id=current_week_id(), user_id=interaction.user.id)
        except httpx.HTTPError:
            return None

    async def ticket_from_interaction(self, interaction: discord.Interaction) -> dict | None:
        ticket_id = ticket_id_from_message(interaction.message)
        if not ticket_id:
            await interaction.response.send_message("Nao consegui identificar o ticket desta mensagem.", ephemeral=True)
            return None
        try:
            return await self.bot.api.get_farm_ticket(ticket_id)
        except httpx.HTTPError:
            await interaction.response.send_message("Nao consegui carregar este ticket.", ephemeral=True)
            return None

    async def refresh_ticket_channel_message(self, guild: discord.Guild | None, ticket: dict) -> None:
        if not guild or not ticket.get("channel_id") or not ticket.get("panel_message_id"):
            return
        channel = guild.get_channel(int(ticket["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(int(ticket["panel_message_id"]))
            member = guild.get_member(int(ticket["user_id"]))
            await message.edit(embed=farm_ticket_embed(ticket, member), view=FarmTicketControlView(self))
        except discord.HTTPException:
            return

    async def lock_member_channel_permissions(self, guild: discord.Guild | None, ticket: dict) -> None:
        if not guild or not ticket.get("channel_id"):
            return
        channel = guild.get_channel(int(ticket["channel_id"]))
        member = guild.get_member(int(ticket["user_id"]))
        if not isinstance(channel, discord.TextChannel) or not member:
            return
        overwrite = channel.overwrites_for(member)
        overwrite.send_messages = False
        overwrite.attach_files = False
        try:
            await channel.set_permissions(member, overwrite=overwrite, reason="Ticket de farm finalizado")
        except discord.HTTPException:
            pass

    async def delete_ticket_channel(self, guild: discord.Guild | None, ticket: dict, actor_id: int | None, *, manual: bool) -> None:
        try:
            await self.bot.api.delete_farm_ticket(
                int(ticket["id"]),
                {"actor_id": str(actor_id) if actor_id else None, "action": "delete", "payload": {"manual": manual}},
            )
        except httpx.HTTPError:
            return
        if guild and ticket.get("channel_id"):
            channel = guild.get_channel(int(ticket["channel_id"]))
            if isinstance(channel, discord.TextChannel):
                try:
                    await channel.delete(reason="Limpeza de ticket de farm")
                except discord.HTTPException:
                    pass
        await self.flush_pending_logs()

    async def flush_pending_logs(self) -> None:
        try:
            actions = await self.bot.api.get_pending_farm_ticket_logs()
        except httpx.HTTPError:
            return
        for action in actions:
            guild = self.bot.get_guild(int(action["guild_id"]))
            if not guild:
                continue
            try:
                config = await self.bot.api.get_farm_ticket_config(guild.id)
                channel = guild.get_channel(int(config["log_channel_id"]))
                if not isinstance(channel, discord.TextChannel):
                    raise RuntimeError("canal de log indisponivel")
                message = await channel.send(embed=farm_log_embed(action), allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
                if action.get("action") == "ticket_aberto":
                    try:
                        thread = await message.create_thread(name=f"farm-ticket-{action.get('ticket_id')}")
                        await thread.send("Thread de detalhes do ticket de farm.")
                    except discord.HTTPException:
                        pass
                await self.bot.api.mark_farm_ticket_log_sent(int(action["id"]), message.id)
            except (discord.HTTPException, httpx.HTTPError, RuntimeError, ValueError):
                try:
                    await self.bot.api.mark_farm_ticket_log_failed(int(action["id"]))
                except httpx.HTTPError:
                    pass

    @tasks.loop(minutes=1)
    async def auto_finalize_old_tickets(self) -> None:
        try:
            tickets = await self.bot.api.get_stale_farm_tickets(current_week_id())
        except httpx.HTTPError:
            return
        for ticket in tickets:
            try:
                updated = await self.bot.api.finalize_farm_ticket(
                    int(ticket["id"]),
                    {"actor_id": None, "reason": "Prazo semanal encerrado"},
                )
            except httpx.HTTPError:
                continue
            guild = self.bot.get_guild(int(updated["guild_id"]))
            await self.lock_member_channel_permissions(guild, updated)
            await self.refresh_ticket_channel_message(guild, updated)
        await self.flush_pending_logs()

    @tasks.loop(minutes=15)
    async def replay_logs_and_cleanup(self) -> None:
        await self.flush_pending_logs()
        try:
            tickets = await self.bot.api.get_deletable_farm_tickets(current_week_id())
        except httpx.HTTPError:
            return
        for ticket in tickets:
            guild = self.bot.get_guild(int(ticket["guild_id"]))
            await self.delete_ticket_channel(guild, ticket, None, manual=False)

    @auto_finalize_old_tickets.before_loop
    @replay_logs_and_cleanup.before_loop
    async def before_tasks(self) -> None:
        await self.bot.wait_until_ready()

    async def _ensure_setup_admin(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await deny(interaction, "use dentro de um servidor.")
            return False
        if (
            interaction.user.guild_permissions.manage_guild
            or interaction.user.guild_permissions.administrator
            or interaction.guild.owner_id == interaction.user.id
        ):
            return True
        await deny(interaction, "voce precisa ter permissao de gerenciar servidor.")
        return False


def _detail(exc: httpx.HTTPStatusError) -> str:
    try:
        data = exc.response.json()
        return str(data.get("detail") or "Erro inesperado.")
    except ValueError:
        return "Erro inesperado."
