import discord
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.parceria.embeds import parcerias_panel_embed
from yuno_bot.commands.parceria.modals import ParceriaCadastrarModal
from yuno_bot.commands.parceria.permissions import role_name_matches
from yuno_bot.commands.parceria.repository import ParceriasRepository
from yuno_bot.commands.parceria.views import ParceriaPanelView
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
        await interaction.response.send_modal(ParceriaCadastrarModal(self.bot.api))

    @app_commands.command(name="setup_parcerias", description="Configura o painel fixo de parcerias")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_parcerias(
        self,
        interaction: discord.Interaction,
        canal_registro: discord.TextChannel,
        canal_ativas: discord.TextChannel,
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

        await interaction.response.defer(ephemeral=True, thinking=True)

        current_config = await self.repository.get_config(interaction.guild.id)
        panel_message = await self._publish_or_update_panel(canal_registro, current_config)
        if not panel_message:
            await interaction.followup.send("Canal de registro de parcerias não encontrado.", ephemeral=True)
            return

        await self.repository.upsert_config(
            guild_id=interaction.guild.id,
            category_id=categoria.id if categoria else None,
            registrar_channel_id=canal_registro.id,
            ativas_channel_id=canal_ativas.id,
            panel_message_id=panel_message.id,
        )

        warnings = await self._apply_gerente_permissions(
            interaction.guild,
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
        response_lines.extend(warnings)
        await interaction.followup.send("\n".join(response_lines), ephemeral=True)

    async def _publish_or_update_panel(
        self,
        panel_channel: discord.TextChannel,
        current_config,
    ) -> discord.Message | None:
        embed = parcerias_panel_embed()
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

    async def _apply_gerente_permissions(
        self,
        guild: discord.Guild,
        *,
        channels: list[discord.TextChannel],
        category: discord.CategoryChannel | None,
    ) -> list[str]:
        warnings: list[str] = []
        gerente_roles = [role for role in guild.roles if role_name_matches(role.name, ("gerente",))]
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

        for role in gerente_roles:
            for target in targets:
                try:
                    await target.set_permissions(role, overwrite=overwrite, reason="Yuno parcerias: liberar gerentes")
                except discord.HTTPException:
                    warnings.append(f"Aviso: não consegui liberar {role.mention} em {target.mention}.")
        return warnings
