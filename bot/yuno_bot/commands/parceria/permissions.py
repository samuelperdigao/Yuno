import discord
import httpx

from yuno_bot.api_client import YunoAPI


MANAGER_ROLE_KEYWORDS = (
    "liderança",
    "lideranca",
    "aprovação",
    "aprovacao",
    "equipe",
    "editor",
    "gerente",
)


def role_name_matches(name: str, keywords: tuple[str, ...] = MANAGER_ROLE_KEYWORDS) -> bool:
    normalized = name.casefold()
    return any(keyword.casefold() in normalized for keyword in keywords)


def member_has_named_management_role(member: discord.Member) -> bool:
    return any(role_name_matches(role.name) for role in member.roles)


def member_has_direct_management(member: discord.Member) -> bool:
    return (
        member.guild.owner_id == member.id
        or member.guild_permissions.administrator
        or member.guild_permissions.manage_guild
    )


async def can_manage_parcerias(
    interaction: discord.Interaction,
    api: YunoAPI,
    *,
    command: str,
) -> bool:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False

    member = interaction.user
    if member_has_direct_management(member) or member_has_named_management_role(member):
        return True

    category_id = None
    if isinstance(interaction.channel, discord.TextChannel) and interaction.channel.category:
        category_id = interaction.channel.category.id

    for api_command in (command, "gerenciar", "cadastrar"):
        try:
            allowed, _reason = await api.check_permission(
                guild_id=interaction.guild.id,
                module="parceria",
                command=api_command,
                role_ids=[role.id for role in member.roles],
                channel_id=interaction.channel_id,
                category_id=category_id,
            )
        except httpx.HTTPError:
            continue
        if allowed:
            return True
    return False
