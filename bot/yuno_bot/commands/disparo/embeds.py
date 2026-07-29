import discord

EVERYONE_ALLOWED_MENTIONS = discord.AllowedMentions(everyone=True, users=False, roles=False, replied_user=False)


def painel_disparo_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📨 Central de Disparo de Mensagens",
        description=(
            "Envie um comunicado para todas as pastas privadas de membro (farm_tickets) de uma vez.\n\n"
            "Use para cobranças, lembretes de farm, avisos de meta semanal e outros comunicados rápidos."
        ),
        color=discord.Color.blue(),
    )
    embed.add_field(
        name="🎯 Destino",
        value="Somente pastas privadas individuais de membro — canais livres, tutoriais e divisores visuais são ignorados automaticamente.",
        inline=False,
    )
    embed.add_field(name="🔓 Permissão", value="Qualquer pessoa com acesso a este canal pode usar o painel.", inline=False)
    embed.set_footer(text="Sistema de Disparo")
    return embed
