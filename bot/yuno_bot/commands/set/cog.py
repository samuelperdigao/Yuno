import discord
import httpx
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.set.embeds import build_set_panel_config, panel_embed
from yuno_bot.commands.set.modals import SetAprovarModal, SetReprovarModal, SetSolicitarModal
from yuno_bot.commands.set.views import SetPanelView
from yuno_bot.commands.panels import customize_panel_embed, remove_previous_panel, rollback_unsaved_panel
from yuno_bot.guards import deny, ensure_allowed


class SetCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    set_group = app_commands.Group(name="set", description="Sistema de set")

    @set_group.command(name="solicitar", description="Abre o formulario de solicitacao de set")
    async def solicitar(self, interaction: discord.Interaction) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "set", "solicitar")
        if not allowed:
            await deny(interaction, reason)
            return
        await interaction.response.send_modal(SetSolicitarModal(self.bot.api))

    @set_group.command(name="aprovar", description="Abre o formulario de aprovacao de set")
    async def aprovar(self, interaction: discord.Interaction) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "set", "aprovar")
        if not allowed:
            await deny(interaction, reason)
            return
        await interaction.response.send_modal(SetAprovarModal(self.bot.api))

    @set_group.command(name="reprovar", description="Abre o formulario de reprovacao de set")
    async def reprovar(self, interaction: discord.Interaction) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "set", "reprovar")
        if not allowed:
            await deny(interaction, reason)
            return
        await interaction.response.send_modal(SetReprovarModal(self.bot.api))

    @set_group.command(name="painel", description="Publica ou atualiza o painel fixo de solicitacao de set")
    @app_commands.default_permissions(manage_guild=True)
    async def painel(
        self,
        interaction: discord.Interaction,
        canal_solicitacao: discord.TextChannel,
        canal_aprovacao: discord.TextChannel,
        cargo_aprovador: discord.Role,
        cargo_aprovado: discord.Role,
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
        bot_member = interaction.guild.me
        if not bot_member or not bot_member.guild_permissions.manage_channels:
            await deny(interaction, "eu preciso da permissao Gerenciar Canais para restringir as abas do Yuno.")
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

        panel_message = await self._publish_or_update_panel(interaction, current_config, canal_solicitacao)
        if not panel_message:
            await interaction.followup.send("Nao consegui publicar o painel no canal informado.", ephemeral=True)
            return
        permission_warnings = await self._apply_set_visibility(
            interaction.guild,
            panel_channel=canal_solicitacao,
            approval_channel=canal_aprovacao,
            approval_role=cargo_aprovador,
        )

        updated_config = build_set_panel_config(
            current_config,
            panel_channel_id=canal_solicitacao.id,
            approval_channel_id=canal_aprovacao.id,
            approval_role_id=cargo_aprovador.id,
            approved_role_id=cargo_aprovado.id,
            panel_message_id=panel_message.id,
        )
        try:
            await self.bot.api.save_guild_config(interaction.guild.id, updated_config)
        except httpx.HTTPError:
            await rollback_unsaved_panel(current_config, panel_message, module_key="set")
            await interaction.followup.send("Painel publicado, mas nao consegui salvar a configuracao.", ephemeral=True)
            return

        await remove_previous_panel(
            current_config, canal_solicitacao, module_key="set", message_id=panel_message.id
        )

        await interaction.followup.send(
            "\n".join(
                [
                    "Painel de SET configurado.",
                    f"Solicitacoes: {canal_solicitacao.mention}",
                    f"Aprovacao: {canal_aprovacao.mention}",
                    f"Aprovadores: {cargo_aprovador.mention}",
                    f"Cargo aprovado: {cargo_aprovado.mention}",
                    f"Visibilidade: membros novos veem apenas {canal_solicitacao.mention}.",
                    *permission_warnings,
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
        set_settings = (current_config.get("settings") or {}).get("set") or {}
        previous_channel_id = set_settings.get("panel_channel_id")
        previous_message_id = set_settings.get("panel_message_id")
        embed = customize_panel_embed(
            panel_embed(interaction.guild.name if interaction.guild else None), current_config, "set"
        )
        view = SetPanelView(self.bot.api)

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

    async def _apply_set_visibility(
        self,
        guild: discord.Guild,
        *,
        panel_channel: discord.TextChannel,
        approval_channel: discord.TextChannel,
        approval_role: discord.Role,
    ) -> list[str]:
        warnings: list[str] = []
        default_role = guild.default_role

        for category in guild.categories:
            overwrite = category.overwrites_for(default_role)
            if overwrite.view_channel is False:
                continue
            overwrite.view_channel = False
            try:
                await category.set_permissions(
                    default_role,
                    overwrite=overwrite,
                    reason="Yuno painel de set: restringir entrada de membros",
                )
            except discord.HTTPException:
                warnings.append(f"Aviso: nao consegui restringir a categoria {category.name}.")

        channels = self._resolve_member_gate_channels(guild, panel_channel, approval_channel)
        for channel in channels:
            overwrite = channel.overwrites_for(default_role)
            try:
                if channel.id == panel_channel.id:
                    if (
                        overwrite.view_channel is True
                        and overwrite.send_messages is False
                        and overwrite.read_message_history is True
                    ):
                        continue
                    overwrite.view_channel = True
                    overwrite.send_messages = False
                    overwrite.read_message_history = True
                    await channel.set_permissions(
                        default_role,
                        overwrite=overwrite,
                        reason="Yuno painel de set: liberar solicitacao para membros",
                    )
                    continue
                # Canais filhos herdam o bloqueio da categoria. So precisam de
                # chamada propria quando estao sem categoria ou possuem uma
                # liberacao explicita de @everyone que venceria a heranca.
                if channel.category is not None and overwrite.view_channel is not True:
                    continue
                if overwrite.view_channel is False:
                    continue
                overwrite.view_channel = False
                await channel.set_permissions(
                    default_role,
                    overwrite=overwrite,
                    reason="Yuno painel de set: restringir entrada de membros",
                )
            except discord.HTTPException:
                warnings.append(f"Aviso: nao consegui ajustar permissoes em {channel.name}.")

        try:
            approval_overwrite = approval_channel.overwrites_for(approval_role)
            approval_overwrite.view_channel = True
            approval_overwrite.send_messages = True
            approval_overwrite.read_message_history = True
            await approval_channel.set_permissions(
                approval_role,
                overwrite=approval_overwrite,
                reason="Yuno painel de set: liberar aprovadores",
            )
        except discord.HTTPException:
            warnings.append(f"Aviso: nao consegui liberar {approval_role.mention} em {approval_channel.mention}.")

        return warnings

    def _resolve_member_gate_channels(
        self,
        guild: discord.Guild,
        panel_channel: discord.TextChannel,
        approval_channel: discord.TextChannel,
    ) -> list[discord.abc.GuildChannel]:
        channels: dict[int, discord.abc.GuildChannel] = {
            panel_channel.id: panel_channel,
            approval_channel.id: approval_channel,
        }
        for channel in guild.channels:
            if not isinstance(channel, discord.CategoryChannel):
                channels[channel.id] = channel
        return list(channels.values())
