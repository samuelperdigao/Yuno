import discord
import httpx
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.set.embeds import build_set_panel_config, panel_embed
from yuno_bot.commands.set.modals import SetAprovarModal, SetReprovarModal, SetSolicitarModal
from yuno_bot.commands.set.views import SetPanelView
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

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            current_config = await self.bot.api.get_guild_config(interaction.guild.id)
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
            await interaction.followup.send("Painel publicado, mas nao consegui salvar a configuracao.", ephemeral=True)
            return

        await interaction.followup.send(
            "\n".join(
                [
                    "Painel de SET configurado.",
                    f"Solicitacoes: {canal_solicitacao.mention}",
                    f"Aprovacao: {canal_aprovacao.mention}",
                    f"Aprovadores: {cargo_aprovador.mention}",
                    f"Cargo aprovado: {cargo_aprovado.mention}",
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
        embed = panel_embed(interaction.guild.name if interaction.guild else None)
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
