import discord
import httpx
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.meta.embeds import build_meta_panel_config, meta_panel_embed
from yuno_bot.commands.meta.modals import MetaRegistrarModal
from yuno_bot.commands.meta.views import MetaPanelView
from yuno_bot.commands.panels import customize_panel_embed, remove_previous_panel, rollback_unsaved_panel
from yuno_bot.guards import deny, ensure_allowed


class MetaCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    meta = app_commands.Group(name="meta", description="Sistema de metas semanais")

    @meta.command(name="registrar", description="Abre o formulario de registro de meta")
    async def registrar(self, interaction: discord.Interaction) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "meta", "registrar")
        if not allowed:
            await deny(interaction, reason)
            return
        await interaction.response.send_modal(MetaRegistrarModal(self.bot.api))

    @meta.command(name="painel", description="Publica ou atualiza o painel fixo de definicao de metas")
    @app_commands.default_permissions(manage_guild=True)
    async def painel(
        self,
        interaction: discord.Interaction,
        canal_painel: discord.TextChannel,
        canal_resultado: discord.TextChannel,
        cargo_definidor: discord.Role,
    ) -> None:
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

        panel_message = await self._publish_or_update_panel(interaction, current_config, canal_painel)
        if not panel_message:
            await interaction.followup.send("Nao consegui publicar o painel no canal informado.", ephemeral=True)
            return

        updated_config = build_meta_panel_config(
            current_config,
            panel_channel_id=canal_painel.id,
            result_channel_id=canal_resultado.id,
            allowed_role_id=cargo_definidor.id,
            panel_message_id=panel_message.id,
        )
        try:
            await self.bot.api.save_guild_config(interaction.guild.id, updated_config)
        except httpx.HTTPError:
            await rollback_unsaved_panel(current_config, panel_message, module_key="meta")
            await interaction.followup.send("Painel publicado, mas nao consegui salvar a configuracao.", ephemeral=True)
            return

        await remove_previous_panel(
            current_config, canal_painel, module_key="meta", message_id=panel_message.id
        )

        await interaction.followup.send(
            "\n".join(
                [
                    "Painel de metas configurado.",
                    f"Painel fixo: {canal_painel.mention}",
                    f"Publicacao das metas: {canal_resultado.mention}",
                    f"Pode definir metas: {cargo_definidor.mention}",
                ]
            ),
            ephemeral=True,
        )

    async def _publish_or_update_panel(
        self,
        interaction: discord.Interaction,
        current_config: dict,
        panel_channel: discord.TextChannel,
    ) -> discord.Message | None:
        meta_settings = (current_config.get("settings") or {}).get("meta") or {}
        previous_channel_id = meta_settings.get("panel_channel_id")
        previous_message_id = meta_settings.get("panel_message_id")
        embed = customize_panel_embed(
            meta_panel_embed(interaction.guild.name if interaction.guild else None), current_config, "meta"
        )
        view = MetaPanelView(self.bot.api)

        if str(previous_channel_id) == str(panel_channel.id) and previous_message_id:
            try:
                message = await panel_channel.fetch_message(int(previous_message_id))
                await message.edit(embed=embed, view=view)
                return message
            except (ValueError, discord.HTTPException):
                pass

        try:
            return await panel_channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            return None
