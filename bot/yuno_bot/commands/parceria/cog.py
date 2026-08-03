import discord
import httpx
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.parceria.embeds import parcerias_panel_embed
from yuno_bot.commands.farm_tickets.helpers import parse_discord_ids
from yuno_bot.commands.parceria.repository import ParceriasRepository
from yuno_bot.commands.parceria.views import ParceriaPanelView, ParceriaRegisterModal
from yuno_bot.commands.panels import customize_panel_embed
from yuno_bot.guards import deny, ensure_allowed


class ParceriaCog(commands.Cog):
    def __init__(self, bot: commands.Bot, repository: ParceriasRepository) -> None:
        self.bot = bot
        self.repository = repository

    parceria = app_commands.Group(name="parceria", description="Sistema de parcerias")

    @parceria.command(name="cadastrar", description="Abre o formulario de parceria")
    async def cadastrar(self, interaction: discord.Interaction) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "parceria", "cadastrar")
        if not allowed:
            await deny(interaction, reason)
            return
        await interaction.response.send_modal(ParceriaRegisterModal(self.repository))

    @app_commands.command(name="setup_parcerias", description="Configura o painel fixo de parcerias")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_parcerias(
        self,
        interaction: discord.Interaction,
        canal_registro: discord.TextChannel,
        canal_ativas: discord.TextChannel,
        cargos_gerentes: str,
        categoria: discord.CategoryChannel | None = None,
    ) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await deny(interaction, "use dentro de um servidor.")
            return
        if not (
            interaction.guild.owner_id == interaction.user.id
            or interaction.user.guild_permissions.administrator
            or interaction.user.guild_permissions.manage_guild
        ):
            await deny(interaction, "voce precisa ter permissao de gerenciar servidor.")
            return

        role_ids = parse_discord_ids(cargos_gerentes)
        roles = [interaction.guild.get_role(role_id) for role_id in role_ids]
        if not role_ids or any(role is None for role in roles):
            await interaction.response.send_message("Informe cargos gerentes validos.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            guild_config = await self.bot.api.get_guild_config(interaction.guild.id, force=True)
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui carregar a configuracao do servidor.", ephemeral=True)
            return
        current_config = await self.repository.get_config(interaction.guild.id)
        panel_message = await self._publish_or_update_panel(canal_registro, current_config, guild_config)
        if not panel_message:
            await interaction.followup.send("Canal de registro de parcerias não encontrado.", ephemeral=True)
            return

        try:
            await self.repository.upsert_config(
                guild_id=interaction.guild.id,
                category_id=categoria.id if categoria else None,
                registrar_channel_id=canal_registro.id,
                ativas_channel_id=canal_ativas.id,
                panel_message_id=panel_message.id,
            )
        except httpx.HTTPError:
            if not (
                current_config
                and current_config.parceria_registrar_channel_id == canal_registro.id
                and current_config.parceria_panel_message_id == panel_message.id
            ):
                try:
                    await panel_message.delete()
                except discord.HTTPException:
                    pass
            await interaction.followup.send(
                "Painel publicado, mas nao consegui salvar a configuracao de parcerias.", ephemeral=True
            )
            return
        await self._remove_previous_panel(canal_registro, panel_message.id, current_config)

        updated_guild_config = self._with_manager_permissions(
            guild_config,
            role_ids=role_ids,
            registrar_channel_id=canal_registro.id,
        )
        try:
            await self.bot.api.save_guild_config(interaction.guild.id, updated_guild_config)
        except httpx.HTTPError:
            await interaction.followup.send(
                "Painel publicado, mas nao consegui salvar os cargos gerentes. Rode o setup novamente.",
                ephemeral=True,
            )
            return

        warnings = await self._apply_gerente_permissions(
            roles=[role for role in roles if role],
            channels=[canal_registro, canal_ativas],
            category=categoria,
        )
        response_lines = [
            "Painel de parcerias configurado.",
            f"Painel fixo: {canal_registro.mention}",
            f"Lista pública: {canal_ativas.mention}",
        ]
        if categoria:
            response_lines.append(f"Categoria: {categoria.name}")
        response_lines.append(f"Gerentes: {' '.join(role.mention for role in roles if role)}")
        response_lines.extend(warnings)
        await interaction.followup.send("\n".join(response_lines), ephemeral=True)

    @staticmethod
    def _with_manager_permissions(config: dict, *, role_ids: list[int], registrar_channel_id: int) -> dict:
        updated = {
            "guild_name": config.get("guild_name"),
            "admin_role_ids": config.get("admin_role_ids") or [],
            "log_channel_id": config.get("log_channel_id"),
            "modules": config.get("modules") or {},
            "command_permissions": dict(config.get("command_permissions") or {}),
            "messages": config.get("messages") or {},
            "settings": dict(config.get("settings") or {}),
        }
        role_values = [str(role_id) for role_id in role_ids]
        for command in ("cadastrar", "registrar", "editar", "remover", "gerenciar"):
            rule = dict(updated["command_permissions"].get(f"parceria.{command}") or {})
            rule["role_ids"] = role_values
            rule["channel_ids"] = [str(registrar_channel_id)]
            updated["command_permissions"][f"parceria.{command}"] = rule
        parceria_settings = dict(updated["settings"].get("parceria") or {})
        parceria_settings["manager_role_ids"] = role_values
        updated["settings"]["parceria"] = parceria_settings
        return updated

    async def _publish_or_update_panel(
        self,
        panel_channel: discord.TextChannel,
        current_config,
        guild_config: dict,
    ) -> discord.Message | None:
        embed = customize_panel_embed(parcerias_panel_embed(), guild_config, "parceria")
        view = ParceriaPanelView(self.bot.api, self.repository)

        if (
            current_config
            and current_config.parceria_registrar_channel_id == panel_channel.id
            and current_config.parceria_panel_message_id
        ):
            try:
                message = await panel_channel.fetch_message(current_config.parceria_panel_message_id)
                await message.edit(embed=embed, view=view)
                return message
            except discord.HTTPException:
                pass

        try:
            return await panel_channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            return None

    async def _remove_previous_panel(
        self,
        panel_channel: discord.TextChannel,
        panel_message_id: int,
        current_config,
    ) -> None:
        if not current_config or not current_config.parceria_panel_message_id:
            return
        if (
            current_config.parceria_registrar_channel_id == panel_channel.id
            and current_config.parceria_panel_message_id == panel_message_id
        ):
            return
        old_channel = panel_channel.guild.get_channel(current_config.parceria_registrar_channel_id)
        if not isinstance(old_channel, discord.TextChannel):
            return
        try:
            old_message = await old_channel.fetch_message(current_config.parceria_panel_message_id)
            bot_member = panel_channel.guild.me
            if bot_member and old_message.author.id == bot_member.id:
                await old_message.delete()
        except discord.HTTPException:
            pass

    async def _apply_gerente_permissions(
        self,
        *,
        roles: list[discord.Role],
        channels: list[discord.TextChannel],
        category: discord.CategoryChannel | None,
    ) -> list[str]:
        warnings: list[str] = []
        overwrite = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
            manage_messages=True,
        )
        targets: list[discord.abc.GuildChannel] = [*channels]
        if category:
            targets.append(category)

        for role in roles:
            for target in targets:
                try:
                    await target.set_permissions(role, overwrite=overwrite, reason="Yuno parcerias: liberar gerentes")
                except discord.HTTPException:
                    warnings.append(f"Aviso: não consegui liberar {role.mention} em {target.mention}.")
        return warnings
