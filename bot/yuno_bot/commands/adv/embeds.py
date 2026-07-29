import discord

from yuno_bot.commands.shared import make_log_embed

COR_ADV = discord.Color.from_rgb(255, 68, 68)


def build_adv_payload(membro_id: int, descricao: str, dias: int) -> dict:
    return {
        "membro_id": str(membro_id),
        "descricao": descricao.strip(),
        "dias": dias,
    }


def adv_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="⚠️ Painel de Advertências",
        description="Clique no botão abaixo para aplicar uma advertência a um membro.",
        color=COR_ADV,
    )
    embed.set_footer(text="Sistema de Advertências")
    return embed


def adv_post_embed(interaction: discord.Interaction, record: dict, membro: discord.Member, payload: dict) -> discord.Embed:
    embed = discord.Embed(title="⚠️ Advertência", color=COR_ADV, timestamp=discord.utils.utcnow())
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Membro advertido", value=f"{membro.mention}\n`{membro.display_name}`", inline=True)
    embed.add_field(name="Duração", value=f"**{payload['dias']}** dia(s)", inline=True)
    embed.add_field(name="Descrição", value=payload["descricao"][:1024], inline=False)
    embed.set_thumbnail(url=membro.display_avatar.url)
    embed.set_footer(text=f"Advertido por {interaction.user.display_name}")
    return embed


def adv_log_embed(interaction: discord.Interaction, record: dict, membro: discord.Member, payload: dict) -> discord.Embed:
    embed = make_log_embed("Advertência registrada", interaction, color=COR_ADV)
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Membro", value=f"{membro.mention}\n`{membro.id}`", inline=True)
    embed.add_field(name="Duração", value=f"{payload['dias']} dia(s)", inline=True)
    embed.add_field(name="Descrição", value=payload["descricao"][:1024], inline=False)
    return embed
