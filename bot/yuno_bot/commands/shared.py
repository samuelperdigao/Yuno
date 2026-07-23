from typing import Any

import discord
import httpx

from yuno_bot.api_client import YunoAPI


YUNO_GOLD = discord.Color.from_rgb(255, 199, 44)
YUNO_BLUE = discord.Color.from_rgb(82, 140, 255)
YUNO_GREEN = discord.Color.green()
YUNO_ORANGE = discord.Color.orange()
YUNO_RED = discord.Color.red()


def clean_text(value: str | None, *, fallback: str = "Nao informado") -> str:
    value = (value or "").strip()
    return value or fallback


def parse_positive_int(value: str, field_name: str) -> int:
    normalized = value.strip().replace(".", "")
    if not normalized.isdigit():
        raise ValueError(f"{field_name} deve conter apenas numeros.")
    parsed = int(normalized)
    if parsed <= 0:
        raise ValueError(f"{field_name} precisa ser maior que zero.")
    return parsed


def make_success_embed(title: str, description: str, interaction: discord.Interaction) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=YUNO_GREEN, timestamp=discord.utils.utcnow())
    embed.set_footer(text=f"Yuno - solicitado por {interaction.user.display_name}")
    return embed


def make_log_embed(title: str, interaction: discord.Interaction, *, color: discord.Color = YUNO_GOLD) -> discord.Embed:
    embed = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())
    embed.add_field(name="Usuario", value=f"{interaction.user.mention}\n`{interaction.user.id}`", inline=True)
    if interaction.channel:
        embed.add_field(name="Canal", value=f"{interaction.channel.mention}", inline=True)
    embed.set_footer(text="Yuno - log do sistema")
    return embed


async def get_guild_config(api: YunoAPI, guild_id: int) -> dict[str, Any]:
    try:
        return await api.get_guild_config(guild_id)
    except httpx.HTTPError:
        return {}


def channel_id_from_setup(config: dict[str, Any], key: str) -> int | None:
    setup = (config.get("settings") or {}).get("discord_setup") or {}
    channel_id = (setup.get("channel_ids") or {}).get(key)
    if not channel_id:
        return None
    try:
        return int(channel_id)
    except (TypeError, ValueError):
        return None


def log_channel_id_from_setup(config: dict[str, Any], module: str) -> int | None:
    setup = (config.get("settings") or {}).get("discord_setup") or {}
    channel_id = (setup.get("log_channel_ids") or {}).get(module) or config.get("log_channel_id")
    if not channel_id:
        return None
    try:
        return int(channel_id)
    except (TypeError, ValueError):
        return None


async def resolve_text_channel(guild: discord.Guild, channel_id: int | None) -> discord.TextChannel | None:
    if not channel_id:
        return None
    channel = guild.get_channel(channel_id)
    if channel is None:
        try:
            channel = await guild.fetch_channel(channel_id)
        except discord.HTTPException:
            return None
    return channel if isinstance(channel, discord.TextChannel) else None


async def send_module_log(api: YunoAPI, interaction: discord.Interaction, module: str, embed: discord.Embed) -> bool:
    if not interaction.guild:
        return False
    config = await get_guild_config(api, interaction.guild.id)
    channel = await resolve_text_channel(interaction.guild, log_channel_id_from_setup(config, module))
    if not channel:
        return False
    try:
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
        return True
    except discord.HTTPException:
        return False


async def send_to_setup_channel(
    api: YunoAPI,
    interaction: discord.Interaction,
    channel_key: str,
    *,
    embed: discord.Embed,
    view: discord.ui.View | None = None,
    content: str | None = None,
) -> discord.Message | None:
    if not interaction.guild:
        return None
    config = await get_guild_config(api, interaction.guild.id)
    channel = await resolve_text_channel(interaction.guild, channel_id_from_setup(config, channel_key))
    if not channel:
        return None
    try:
        return await channel.send(
            content=content,
            embed=embed,
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
    except discord.HTTPException:
        return None


async def create_record(
    api: YunoAPI,
    interaction: discord.Interaction,
    *,
    module: str,
    title: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return await api.create_record(
        module=module,
        guild_id=interaction.guild_id,
        title=title,
        requester_id=interaction.user.id,
        channel_id=interaction.channel_id,
        payload=payload,
    )
