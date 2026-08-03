import discord
import httpx
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.anuncio.embeds import anuncio_panel_embed, build_anuncio_panel_config
from yuno_bot.commands.anuncio.modals import AnuncioModal
from yuno_bot.commands.anuncio.views import AnuncioPanelView
from yuno_bot.commands.panels import customize_panel_embed, remove_previous_panel, rollback_unsaved_panel
from yuno_bot.commands.farm_tickets.helpers import parse_discord_ids
from yuno_bot.guards import deny, ensure_allowed


class AnuncioCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    anuncio = app_commands.Group(name="anuncio", description="Sistema de anúncios")

    @anuncio.command(name="publicar", description="Abre o formulario de anuncio")
    async def publicar(self, interaction: discord.Interaction) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "anuncio", "publicar")
        if not allowed:
            await deny(interaction, reason)
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await deny(interaction, "use dentro de um canal de texto.")
            return
        await interaction.response.send_modal(AnuncioModal(self.bot.api, interaction.channel))

    @anuncio.command(name="painel", description="Publica ou atualiza o painel de anuncios e define os cargos autorizados")
    @app_commands.default_permissions(manage_guild=True)
    async def painel(self, interaction: discord.Interaction, canal: discord.TextChannel, cargos_anunciantes: str) -> None:
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

        role_ids = parse_discord_ids(cargos_anunciantes)
        roles = [interaction.guild.get_role(role_id) for role_id in role_ids]
        if not role_ids or any(role is None for role in roles):
            await interaction.response.send_message("Informe cargos validos em `cargos_anunciantes`.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            current_config = await self.bot.api.get_guild_config(interaction.guild.id, force=True)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                await interaction.followup.send("Este servidor ainda nao possui licenca ativa.", ephemeral=True)
                return
            await interaction.followup.send("Nao consegui carregar a configuracao do servidor.", ephemeral=True)
            return
        except httpx.HTTPError:
            await interaction.followup.send("Nao consegui falar com a API do Yuno.", ephemeral=True)
            return

        panel_message = await self._publish_or_update_panel(current_config, canal)
        if not panel_message:
            await interaction.followup.send("Nao consegui publicar o painel no canal informado.", ephemeral=True)
            return

        updated_config = build_anuncio_panel_config(
            current_config, panel_channel_id=canal.id, role_ids=role_ids, panel_message_id=panel_message.id
        )
        try:
            await self.bot.api.save_guild_config(interaction.guild.id, updated_config)
        except httpx.HTTPError:
            await rollback_unsaved_panel(current_config, panel_message, module_key="anuncio")
            await interaction.followup.send("Painel publicado, mas nao consegui salvar a configuracao.", ephemeral=True)
            return

        await remove_previous_panel(
            current_config, canal, module_key="anuncio", message_id=panel_message.id
        )

        cargos_txt = " ".join(role.mention for role in roles)
        await interaction.followup.send(
            f"Painel de anuncios publicado em {canal.mention}.\nCargos autorizados: {cargos_txt}", ephemeral=True
        )

    async def _publish_or_update_panel(self, current_config: dict, canal: discord.TextChannel) -> discord.Message | None:
        anuncio_settings = (current_config.get("settings") or {}).get("anuncio") or {}
        previous_channel_id = anuncio_settings.get("panel_channel_id")
        previous_message_id = anuncio_settings.get("panel_message_id")
        embed = customize_panel_embed(anuncio_panel_embed(), current_config, "anuncio")
        view = AnuncioPanelView(self.bot.api)

        if str(previous_channel_id) == str(canal.id) and previous_message_id:
            try:
                message = await canal.fetch_message(int(previous_message_id))
                await message.edit(embed=embed, view=view)
                return message
            except (ValueError, discord.HTTPException):
                pass

        try:
            return await canal.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            return None
