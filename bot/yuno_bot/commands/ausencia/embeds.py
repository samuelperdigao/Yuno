import discord

from yuno_bot.commands.shared import YUNO_BLUE, make_log_embed


def build_ausencia_payload(inicio: str, fim: str, motivo: str) -> dict[str, str]:
    return {
        "inicio": inicio.strip(),
        "fim": fim.strip(),
        "motivo": motivo.strip(),
    }


def ausencia_post_embed(interaction: discord.Interaction, record: dict, payload: dict[str, str]) -> discord.Embed:
    embed = discord.Embed(title="Ausencia registrada", color=YUNO_BLUE, timestamp=discord.utils.utcnow())
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Membro", value=interaction.user.mention, inline=True)
    embed.add_field(name="Inicio", value=payload["inicio"], inline=True)
    embed.add_field(name="Fim", value=payload["fim"], inline=True)
    embed.add_field(name="Motivo", value=payload["motivo"][:1024], inline=False)
    embed.set_footer(text="Yuno - sistema de ausencia")
    return embed


def ausencia_log_embed(interaction: discord.Interaction, record: dict, payload: dict[str, str]) -> discord.Embed:
    embed = make_log_embed("Ausencia registrada", interaction, color=YUNO_BLUE)
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Periodo", value=f"{payload['inicio']} ate {payload['fim']}", inline=True)
    embed.add_field(name="Motivo", value=payload["motivo"][:1024], inline=False)
    return embed
