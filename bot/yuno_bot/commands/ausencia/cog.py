import discord
import httpx
from discord import app_commands
from discord.ext import commands, tasks

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.ausencia.embeds import (
    ausencia_channel_id,
    ausencia_log_embed,
    ausencia_public_embed,
    ausencias_list_embed,
    build_ausencia_setup_config,
    format_date_br,
    panel_embed,
)
from yuno_bot.commands.ausencia.views import AusenciaPanelView
from yuno_bot.commands.panels import publish_panel_command
from yuno_bot.commands.shared import resolve_text_channel, send_module_log


PERMISSION_ERROR = "❌ Sem permissão para usar este comando."
NOT_CONFIGURED_ERROR = "❌ O módulo de Ausências não está configurado. Um administrador deve usar /setup_ausencia."


def has_manage_guild(interaction: discord.Interaction) -> bool:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False
    permissions = interaction.user.guild_permissions
    return permissions.manage_guild or permissions.administrator or interaction.guild.owner_id == interaction.user.id


async def publish_ausencia_registration(
    api: YunoAPI,
    interaction: discord.Interaction,
    ausencia: dict,
    *,
    channel: discord.TextChannel | None = None,
) -> discord.TextChannel | None:
    if not interaction.guild:
        return None
    if channel is None:
        config = await api.get_guild_config(interaction.guild.id)
        channel = await resolve_text_channel(interaction.guild, ausencia_channel_id(config))
    if not channel:
        return None

    embed = ausencia_public_embed(interaction.user, ausencia)
    message = None
    previous_message_id = ausencia.get("message_id")
    if previous_message_id:
        try:
            message = await channel.fetch_message(int(previous_message_id))
            await message.edit(embed=embed, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
        except (ValueError, discord.HTTPException):
            message = None

    if message is None:
        message = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))

    await api.update_ausencia_message(guild_id=interaction.guild.id, user_id=interaction.user.id, message_id=message.id)
    await send_module_log(api, interaction, "ausencia", ausencia_log_embed(interaction.user, ausencia))
    return channel


class AusenciaCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.verificar_ausencias_vencidas.start()

    def cog_unload(self) -> None:
        self.verificar_ausencias_vencidas.cancel()

    @app_commands.command(name="setup_ausencia", description="Configura o canal de registros de ausências")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_ausencia(self, interaction: discord.Interaction, canal: discord.TextChannel) -> None:
        if not has_manage_guild(interaction):
            await interaction.response.send_message(PERMISSION_ERROR, ephemeral=True)
            return
        if not interaction.guild:
            await interaction.response.send_message(NOT_CONFIGURED_ERROR, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            current_config = await self.bot.api.get_guild_config(interaction.guild.id)
            updated_config = build_ausencia_setup_config(current_config, channel_id=canal.id)
            if not updated_config.get("guild_name"):
                updated_config["guild_name"] = interaction.guild.name
            await self.bot.api.save_guild_config(interaction.guild.id, updated_config)
        except httpx.HTTPError:
            await interaction.followup.send("❌ Erro interno. Tente novamente.", ephemeral=True)
            return

        await interaction.followup.send(f"✅ Canal de ausências configurado em {canal.mention}.", ephemeral=True)

    @app_commands.command(name="painel_ausencia", description="Publica o painel de registro de ausências")
    @app_commands.default_permissions(manage_guild=True)
    async def painel_ausencia(self, interaction: discord.Interaction) -> None:
        await publish_panel_command(
            interaction,
            self.bot.api,
            module_key="ausencia",
            setup_channel_key="ausencias",
            embed=panel_embed(),
            view=AusenciaPanelView(self.bot.api),
            command_names=("registrar",),
            label="Painel de ausências",
        )

    @app_commands.command(name="ausencias", description="Lista os membros com ausência ativa")
    async def ausencias(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message(NOT_CONFIGURED_ERROR, ephemeral=True)
            return

        try:
            config = await self.bot.api.get_guild_config(interaction.guild.id)
            channel = await resolve_text_channel(interaction.guild, ausencia_channel_id(config))
        except httpx.HTTPError:
            await interaction.response.send_message("❌ Erro interno. Tente novamente.", ephemeral=True)
            return

        if not channel:
            await interaction.response.send_message(NOT_CONFIGURED_ERROR, ephemeral=True)
            return

        try:
            ausencias = await self.bot.api.list_ausencias(interaction.guild.id, active_only=True)
        except httpx.HTTPError:
            await interaction.response.send_message("❌ Erro interno. Tente novamente.", ephemeral=True)
            return

        if not ausencias:
            await interaction.response.send_message("✅ Nenhum membro ausente no momento.")
            return
        await interaction.response.send_message(embed=ausencias_list_embed(ausencias))

    @tasks.loop(hours=1)
    async def verificar_ausencias_vencidas(self) -> None:
        for guild in self.bot.guilds:
            try:
                vencidas = await self.bot.api.list_ausencias(guild.id, pending_notice_only=True)
            except httpx.HTTPError:
                continue

            for ausencia in vencidas:
                user_id = int(ausencia["user_id"])
                member = guild.get_member(user_id)
                if not member:
                    try:
                        member = await guild.fetch_member(user_id)
                    except discord.HTTPException:
                        member = None

                if member:
                    try:
                        await member.send(
                            f"⏰ Sua ausência venceu hoje ({format_date_br(ausencia['fim'])}).\n"
                            "Se precisar de mais tempo, registre uma nova ausência pelo painel."
                        )
                    except discord.HTTPException:
                        pass

                try:
                    await self.bot.api.mark_ausencia_avisado(guild_id=guild.id, user_id=user_id)
                except httpx.HTTPError:
                    continue

    @verificar_ausencias_vencidas.before_loop
    async def before_verificar_ausencias_vencidas(self) -> None:
        await self.bot.wait_until_ready()
