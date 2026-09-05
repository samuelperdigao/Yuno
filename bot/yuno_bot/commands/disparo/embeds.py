import discord

EVERYONE_ALLOWED_MENTIONS = discord.AllowedMentions(everyone=True, users=False, roles=False, replied_user=False)


def painel_disparo_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📨 Central de Disparo de Mensagens",
        description=(
            "Envie um comunicado para todos os canais privados de membro configurados, de uma vez.\n\n"
            "Use para cobranças, lembretes de farm, avisos e outros comunicados rápidos."
        ),
        color=discord.Color.blue(),
    )
    embed.add_field(
        name="🎯 Destino",
        value="Canais da categoria configurada — canais excluídos manualmente e pastas livres (sem dono) ficam de fora.",
        inline=False,
    )
    embed.add_field(name="🔓 Permissão", value="Qualquer pessoa com acesso a este canal pode usar o painel.", inline=False)
    embed.set_footer(text="Sistema de Disparo")
    return embed


def log_envio_embed(*, autor: discord.abc.User, enviados: int, total: int, categoria: str) -> discord.Embed:
    embed = discord.Embed(title="📨 Disparo de mensagem", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
    embed.add_field(name="Disparado por", value=f"{autor.mention}\n`{autor.id}`", inline=True)
    embed.add_field(name="Categoria", value=categoria, inline=True)
    embed.add_field(name="Resultado", value=f"{enviados} de {total} canal(is)", inline=True)
    embed.set_footer(text="Yuno · log de disparo")
    return embed


def log_exclusao_embed(*, autor: discord.abc.User, deletados: int, falhas: int) -> discord.Embed:
    embed = discord.Embed(title="🗑️ Último disparo apagado", color=discord.Color.red(), timestamp=discord.utils.utcnow())
    embed.add_field(name="Apagado por", value=f"{autor.mention}\n`{autor.id}`", inline=True)
    embed.add_field(name="Resultado", value=f"{deletados} apagada(s), {falhas} falha(s)", inline=True)
    embed.set_footer(text="Yuno · log de disparo")
    return embed
