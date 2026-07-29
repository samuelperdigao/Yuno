import asyncio

import discord
import httpx
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.farm_tickets.helpers import release_member_folder
from yuno_bot.commands.membros.embeds import member_join_embed, member_leave_embed
from yuno_bot.commands.shared import channel_id_from_setup, get_guild_config, resolve_text_channel
from yuno_bot.guards import deny


class MembrosCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._pastas_reconciliadas = False

    membros = app_commands.Group(name="membros", description="Configuracao de entrada e saida de membros")

    @membros.command(name="configurar", description="Define o cargo automatico atribuido ao entrar no servidor")
    @app_commands.default_permissions(manage_guild=True)
    async def configurar(self, interaction: discord.Interaction, cargo_boas_vindas: discord.Role | None = None) -> None:
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

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            config = await self.bot.api.get_guild_config(interaction.guild.id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                await interaction.followup.send("Este servidor ainda nao possui licenca ativa.", ephemeral=True)
                return
            await interaction.followup.send("Nao consegui carregar a configuracao do servidor.", ephemeral=True)
            return
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui falar com a API do Yuno.", ephemeral=True)
            return

        settings = dict(config.get("settings") or {})
        membros_settings = dict(settings.get("membros") or {})
        membros_settings["welcome_role_id"] = str(cargo_boas_vindas.id) if cargo_boas_vindas else None
        settings["membros"] = membros_settings
        updated_config = {
            "guild_name": config.get("guild_name"),
            "admin_role_ids": config.get("admin_role_ids") or [],
            "log_channel_id": config.get("log_channel_id"),
            "modules": config.get("modules") or {},
            "command_permissions": config.get("command_permissions") or {},
            "messages": config.get("messages") or {},
            "settings": settings,
        }
        try:
            await self.bot.api.save_guild_config(interaction.guild.id, updated_config)
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui salvar a configuracao.", ephemeral=True)
            return

        texto = f"Cargo automatico definido: {cargo_boas_vindas.mention}" if cargo_boas_vindas else "Cargo automatico removido."
        await interaction.followup.send(texto, ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._pastas_reconciliadas:
            return
        self._pastas_reconciliadas = True
        self.bot.loop.create_task(self._reconciliar_pastas())

    async def _reconciliar_pastas(self) -> None:
        """Libera pastas de membros que saíram enquanto o bot estava offline."""
        await asyncio.sleep(5)
        for guild in self.bot.guilds:
            try:
                config = await get_guild_config(self.bot.api, guild.id)
            except Exception:
                continue
            if not (config.get("modules") or {}).get("membros", False):
                continue
            category_id = ((config.get("settings") or {}).get("farm_tickets") or {}).get("folders_category_id")
            if not category_id:
                continue
            category = guild.get_channel(int(category_id))
            if not isinstance(category, discord.CategoryChannel):
                continue
            for channel in category.text_channels:
                if "livre" in channel.name.casefold():
                    continue
                membro_ausente = next(
                    (
                        target
                        for target, overwrite in channel.overwrites.items()
                        if isinstance(target, discord.Member) and overwrite.view_channel and guild.get_member(target.id) is None
                    ),
                    None,
                )
                if membro_ausente is not None:
                    await release_member_folder(guild, membro_ausente, int(category_id))

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        config = await get_guild_config(self.bot.api, member.guild.id)
        if not (config.get("modules") or {}).get("membros", False):
            return

        welcome_role_id = ((config.get("settings") or {}).get("membros") or {}).get("welcome_role_id")
        if welcome_role_id:
            role = member.guild.get_role(int(welcome_role_id))
            if role:
                try:
                    await member.add_roles(role, reason="Yuno: cargo automatico ao entrar")
                except discord.HTTPException:
                    pass

        canal = await resolve_text_channel(member.guild, channel_id_from_setup(config, "membros_entrada"))
        if canal:
            try:
                await canal.send(embed=member_join_embed(member))
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        config = await get_guild_config(self.bot.api, member.guild.id)
        if not (config.get("modules") or {}).get("membros", False):
            return

        motivo, responsavel = await self._detect_leave_reason(member)

        pasta_liberada = False
        category_id = ((config.get("settings") or {}).get("farm_tickets") or {}).get("folders_category_id")
        if category_id:
            try:
                pasta_liberada = await release_member_folder(member.guild, member, int(category_id))
            except discord.HTTPException:
                pasta_liberada = False

        canal = await resolve_text_channel(member.guild, channel_id_from_setup(config, "membros_saida"))
        if canal:
            try:
                await canal.send(embed=member_leave_embed(member, motivo=motivo, responsavel=responsavel, pasta_liberada=pasta_liberada))
            except discord.HTTPException:
                pass

    async def _detect_leave_reason(self, member: discord.Member) -> tuple[str, discord.abc.User | None]:
        if not member.guild.me or not member.guild.me.guild_permissions.view_audit_log:
            return "Saiu voluntariamente", None
        agora = discord.utils.utcnow()
        try:
            async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
                if entry.target and entry.target.id == member.id and (agora - entry.created_at).total_seconds() < 10:
                    return "Expulso (kick)", entry.user
            async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
                if entry.target and entry.target.id == member.id and (agora - entry.created_at).total_seconds() < 10:
                    return "Banido", entry.user
        except discord.Forbidden:
            pass
        return "Saiu voluntariamente", None
