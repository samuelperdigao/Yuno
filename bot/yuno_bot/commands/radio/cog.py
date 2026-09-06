import discord
import httpx
from discord.ext import commands

from yuno_bot import server_setup
from yuno_bot.commands.radio.embeds import panel_embed, radio_panel_message_id, with_radio_panel_message_id
from yuno_bot.commands.radio.views import RadioPanelView


class RadioCog(commands.Cog):
    """Painel fixo do modulo de Radio.

    Sem slash command dedicado: com o Control Plane ativo, so `/yuno
    configurar` fica na arvore sincronizada (`apply_control_plane_command_policy`
    em `main.py` remove o resto), entao um `/radio painel` nunca chegaria ao
    Discord em producao. `/yuno configurar` ja cria/adota o canal "radio" (via
    `SetupChannel` do modulo); este cog so garante que o painel exista nele,
    reconciliando no boot e a cada guild nova -- mesma ideia idempotente do
    `refresh_published_central_once` da Central.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        for guild in self.bot.guilds:
            await self.reconcile_panel(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self.reconcile_panel(guild)

    async def reconcile_panel(self, guild: discord.Guild) -> None:
        try:
            config = await self.bot.api.get_guild_config(guild.id)
        except httpx.HTTPError:
            return
        if not (config.get("modules") or {}).get("radio", False):
            return

        channel_id = server_setup.saved_channel_id(config, "radio")
        channel = guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            message = await self._publish_or_update_panel(config, channel)
        except discord.HTTPException:
            self.bot.log.exception("Falha ao publicar o painel de rádio na guild %s", guild.id)
            return

        if radio_panel_message_id(config) == message.id:
            return
        try:
            await self.bot.api.save_guild_config(
                guild.id, with_radio_panel_message_id(config, message_id=message.id)
            )
        except httpx.HTTPError:
            self.bot.log.exception("Painel de rádio publicado, mas não consegui salvar o message_id na guild %s", guild.id)

    async def _publish_or_update_panel(self, config: dict, channel: discord.TextChannel) -> discord.Message:
        embed = panel_embed()
        view = RadioPanelView(self.bot.api)
        previous_message_id = radio_panel_message_id(config)

        if previous_message_id:
            try:
                message = await channel.fetch_message(previous_message_id)
                await message.edit(embed=embed, view=view)
                return message
            except discord.HTTPException:
                pass

        return await channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
