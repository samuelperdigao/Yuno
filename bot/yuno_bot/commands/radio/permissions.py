import discord

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.shared import channel_id_from_setup, get_guild_config, resolve_text_channel


def pode_alterar_radio(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any("gerente" in role.name.casefold() for role in member.roles)


async def resolver_canal_radio(api: YunoAPI, guild: discord.Guild) -> discord.TextChannel | None:
    config = await get_guild_config(api, guild.id)
    return await resolve_text_channel(guild, channel_id_from_setup(config, "radio"))


async def configurar_permissoes_radio(canal: discord.TextChannel) -> None:
    overwrites = dict(canal.overwrites)

    default_role = canal.guild.default_role
    default_overwrite = overwrites.get(default_role, discord.PermissionOverwrite())
    default_overwrite.send_messages = False
    default_overwrite.send_messages_in_threads = False
    default_overwrite.create_public_threads = False
    default_overwrite.create_private_threads = False
    overwrites[default_role] = default_overwrite

    bot_member = canal.guild.me
    if bot_member:
        bot_overwrite = overwrites.get(bot_member, discord.PermissionOverwrite())
        bot_overwrite.view_channel = True
        bot_overwrite.send_messages = True
        bot_overwrite.embed_links = True
        bot_overwrite.mention_everyone = True
        overwrites[bot_member] = bot_overwrite

    await canal.edit(
        overwrites=overwrites,
        reason="Canal da rádio reservado ao painel interativo",
    )
