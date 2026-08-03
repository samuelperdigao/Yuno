import discord

from yuno_bot.commands.shared import YUNO_ORANGE, make_log_embed


def ticket_panel_embed(guild_name: str | None = None) -> discord.Embed:
    embed = discord.Embed(
        title="📨 Central de Atendimento",
        description=(
            "Precisa falar com a equipe? Clique no botão abaixo e descreva sua solicitação.\n\n"
            "• Informe o tipo e o assunto com clareza\n"
            "• Explique os detalhes no formulário\n"
            "• Guarde o protocolo recebido"
        ),
        color=YUNO_ORANGE,
    )
    embed.set_footer(text=f"Yuno • Tickets{f' • {guild_name}' if guild_name else ''}")
    return embed


def build_ticket_payload(tipo: str, assunto: str, descricao: str) -> dict[str, str]:
    return {
        "tipo": tipo.strip(),
        "assunto": assunto.strip(),
        "descricao": descricao.strip() or "Nao informado",
    }


def ticket_post_embed(interaction: discord.Interaction, record: dict, payload: dict[str, str]) -> discord.Embed:
    embed = discord.Embed(title="Ticket aberto", color=YUNO_ORANGE, timestamp=discord.utils.utcnow())
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Tipo", value=payload["tipo"], inline=True)
    embed.add_field(name="Solicitante", value=interaction.user.mention, inline=True)
    embed.add_field(name="Assunto", value=payload["assunto"], inline=False)
    embed.add_field(name="Descricao", value=payload["descricao"][:1024], inline=False)
    embed.set_footer(text="Yuno - sistema de tickets")
    return embed


def ticket_log_embed(interaction: discord.Interaction, record: dict, payload: dict[str, str]) -> discord.Embed:
    embed = make_log_embed("Ticket aberto", interaction, color=YUNO_ORANGE)
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Tipo", value=payload["tipo"], inline=True)
    embed.add_field(name="Assunto", value=payload["assunto"], inline=False)
    return embed
