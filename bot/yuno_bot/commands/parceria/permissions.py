import discord
import httpx

from yuno_bot.api_client import YunoAPI


MANAGER_ROLE_KEYWORDS = ("lideranca", "liderança", "aprovacao", "aprovação", "equipe", "editor", "gerente")


def role_name_matches(name: str, keywords: tuple[str, ...] = MANAGER_ROLE_KEYWORDS) -> bool:
    """Compatibilidade para testes legados; autorizacao real usa IDs configurados."""
    normalized = name.casefold()
    return any(keyword.casefold() in normalized for keyword in keywords)


def member_has_named_management_role(member: discord.Member) -> bool:
    """Compatibilidade; nao e chamada pelo fluxo de autorizacao."""
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

    try:
        config = await api.get_guild_config(interaction.guild.id)
    except httpx.HTTPError:
        return False
    if not (config.get("modules") or {}).get("parceria", False):
        return False

    member = interaction.user
    if member_has_direct_management(member):
        return True

    permissions = config.get("command_permissions") or {}
    rule = permissions.get(f"parceria.{command}") or permissions.get("parceria.gerenciar") or {}
    allowed_roles = {str(role_id) for role_id in rule.get("role_ids") or []}
    member_roles = {str(role.id) for role in member.roles}
    if not allowed_roles or not member_roles.intersection(allowed_roles):
        return False

    allowed_channels = {str(channel_id) for channel_id in rule.get("channel_ids") or []}
    return not allowed_channels or str(interaction.channel_id) in allowed_channels
