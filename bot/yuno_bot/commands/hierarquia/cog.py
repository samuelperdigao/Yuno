import discord
import httpx
from discord import app_commands
from discord.ext import commands

from yuno_bot.commands.farm_tickets.helpers import parse_discord_ids
from yuno_bot.commands.hierarquia.embeds import build_hierarquia_panel_config, hierarquia_panel_embed
from yuno_bot.commands.hierarquia.views import HierarquiaPanelView
from yuno_bot.guards import deny


class HierarquiaCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    hierarquia = app_commands.Group(name="hierarquia", description="Sistema de hierarquia de cargos")

    @hierarquia.command(name="painel", description="Publica ou atualiza o painel e define a escada de cargos")
    @app_commands.describe(
        cargos_hierarquia="IDs dos cargos da hierarquia, do MENOR para o MAIOR, separados por virgula",
        cargos_gerentes="IDs dos cargos que podem promover/rebaixar, separados por virgula",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def painel(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        cargos_hierarquia: str,
        cargos_gerentes: str,
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

        ladder_role_ids = parse_discord_ids(cargos_hierarquia)
        manager_role_ids = parse_discord_ids(cargos_gerentes)
        ladder_roles = [interaction.guild.get_role(role_id) for role_id in ladder_role_ids]
        manager_roles = [interaction.guild.get_role(role_id) for role_id in manager_role_ids]
        if not ladder_role_ids or any(role is None for role in ladder_roles):
            await interaction.response.send_message("Informe cargos validos em `cargos_hierarquia`.", ephemeral=True)
            return
        if not manager_role_ids or any(role is None for role in manager_roles):
            await interaction.response.send_message("Informe cargos validos em `cargos_gerentes`.", ephemeral=True)
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

        panel_message = await self._publish_or_update_panel(current_config, canal, ladder_roles)
        if not panel_message:
            await interaction.followup.send("Nao consegui publicar o painel no canal informado.", ephemeral=True)
            return

        updated_config = build_hierarquia_panel_config(
            current_config,
            panel_channel_id=canal.id,
            ladder_role_ids=ladder_role_ids,
            manager_role_ids=manager_role_ids,
            panel_message_id=panel_message.id,
        )
        try:
            await self.bot.api.save_guild_config(interaction.guild.id, updated_config)
        except httpx.HTTPError:
            await interaction.followup.send("Painel publicado, mas nao consegui salvar a configuracao.", ephemeral=True)
            return

        await interaction.followup.send(
            f"Painel de hierarquia publicado em {canal.mention}, com {len(ladder_roles)} cargo(s) na escada.",
            ephemeral=True,
        )

    async def _publish_or_update_panel(
        self, current_config: dict, canal: discord.TextChannel, ladder_roles: list[discord.Role]
    ) -> discord.Message | None:
        hierarquia_settings = (current_config.get("settings") or {}).get("hierarquia") or {}
        previous_channel_id = hierarquia_settings.get("panel_channel_id")
        previous_message_id = hierarquia_settings.get("panel_message_id")
        embed = hierarquia_panel_embed(ladder_roles)
        view = HierarquiaPanelView(self.bot.api)

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
