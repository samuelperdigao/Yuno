import discord


def format_delta(delta) -> str:
    dias = delta.days
    horas = delta.seconds // 3600
    minutos = (delta.seconds % 3600) // 60
    if dias >= 365:
        return f"{dias // 365}a {dias % 365}d"
    if dias > 0:
        return f"{dias}d {horas}h {minutos}m"
    if horas > 0:
        return f"{horas}h {minutos}m"
    return f"{minutos}m"


def member_join_embed(member: discord.Member) -> discord.Embed:
    agora = discord.utils.utcnow()
    idade_conta = format_delta(agora - member.created_at)
    alerta_nova = "\n**CONTA NOVA**" if (agora - member.created_at).days < 7 else ""
    embed = discord.Embed(title="Novo membro entrou no servidor", color=discord.Color.green(), timestamp=agora)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Usuário", value=f"{member.mention}\n`{member.display_name}`\n`{member}`", inline=True)
    embed.add_field(name="ID", value=f"`{member.id}`", inline=True)
    embed.add_field(name="Conta criada", value=f"`{idade_conta} atrás`{alerta_nova}", inline=True)
    embed.add_field(name="Membros no servidor", value=f"`{member.guild.member_count}`", inline=True)
    embed.set_footer(text=f"ID: {member.id}")
    return embed


def member_leave_embed(
    member: discord.Member,
    *,
    motivo: str,
    responsavel: discord.abc.User | None,
    pasta_liberada: bool,
) -> discord.Embed:
    agora = discord.utils.utcnow()
    tempo_str = format_delta(agora - member.joined_at) if member.joined_at else "Desconhecido"
    cargos = [role.mention for role in member.roles if not role.is_default()]
    cargos_txt = " ".join(cargos)[:1024] if cargos else "*(nenhum)*"

    embed = discord.Embed(title="Membro saiu do servidor", color=discord.Color.from_rgb(255, 76, 76), timestamp=agora)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Usuário", value=f"{member.display_name}\n`{member}`", inline=True)
    embed.add_field(name="ID", value=f"`{member.id}`", inline=True)
    embed.add_field(name="Tempo no servidor", value=tempo_str, inline=True)
    embed.add_field(name="Motivo da saída", value=motivo, inline=True)
    embed.add_field(name="Responsável", value=responsavel.mention if responsavel else "-", inline=True)
    if pasta_liberada:
        embed.add_field(name="Pasta de farm", value="Liberada automaticamente", inline=True)
    embed.add_field(name="Cargos que tinha", value=cargos_txt, inline=False)
    embed.set_footer(text=f"ID: {member.id}")
    return embed
