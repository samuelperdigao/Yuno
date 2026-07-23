import discord

from yuno_bot.api_client import YunoAPI


async def ensure_allowed(interaction: discord.Interaction, api: YunoAPI, module: str, command: str) -> tuple[bool, str]:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False, "Este comando precisa ser usado dentro de um servidor."

    category_id = None
    if isinstance(interaction.channel, discord.TextChannel) and interaction.channel.category:
        category_id = interaction.channel.category.id

    return await api.check_permission(
        guild_id=interaction.guild.id,
        module=module,
        command=command,
        role_ids=[role.id for role in interaction.user.roles],
        channel_id=interaction.channel_id,
        category_id=category_id,
    )


async def deny(interaction: discord.Interaction, reason: str) -> None:
    await interaction.response.send_message(f"Yuno nao pode executar isso agora: {reason}", ephemeral=True)
