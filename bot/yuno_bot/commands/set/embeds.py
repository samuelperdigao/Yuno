import discord

from yuno_bot.commands.shared import YUNO_GREEN, YUNO_ORANGE, YUNO_RED, make_log_embed


def build_set_payload(nome: str, id_fivem: str) -> dict[str, str]:
    nome = nome.strip()
    id_fivem = id_fivem.strip()
    return {
        "nome": nome,
        "id_fivem": id_fivem,
        "apelido_sugerido": f"{nome} | {id_fivem}",
    }


def request_embed(interaction: discord.Interaction, record: dict, payload: dict[str, str]) -> discord.Embed:
    embed = discord.Embed(title="Nova solicitacao de set", color=YUNO_ORANGE, timestamp=discord.utils.utcnow())
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Nome", value=payload["nome"], inline=True)
    embed.add_field(name="ID FiveM", value=f"`{payload['id_fivem']}`", inline=True)
    embed.add_field(name="Solicitante", value=f"{interaction.user.mention}\n`{interaction.user.id}`", inline=False)
    embed.set_footer(text="Aguardando aprovacao")
    return embed


def created_log_embed(interaction: discord.Interaction, record: dict, payload: dict[str, str]) -> discord.Embed:
    embed = make_log_embed("Set solicitado", interaction, color=YUNO_ORANGE)
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Nome", value=payload["nome"], inline=True)
    embed.add_field(name="ID FiveM", value=f"`{payload['id_fivem']}`", inline=True)
    return embed


def approval_log_embed(interaction: discord.Interaction, record: dict, nickname_status: str) -> discord.Embed:
    embed = make_log_embed("Set aprovado", interaction, color=YUNO_GREEN)
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Solicitante", value=f"<@{record['requester_id']}>", inline=True)
    embed.add_field(name="Apelido", value=nickname_status or "Nao alterado", inline=False)
    return embed


def rejection_log_embed(interaction: discord.Interaction, record: dict, motivo: str) -> discord.Embed:
    embed = make_log_embed("Set reprovado", interaction, color=YUNO_RED)
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Solicitante", value=f"<@{record['requester_id']}>", inline=True)
    embed.add_field(name="Motivo", value=motivo[:1024], inline=False)
    return embed
