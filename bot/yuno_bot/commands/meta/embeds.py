import discord

from yuno_bot.commands.shared import YUNO_BLUE, make_log_embed


def build_meta_payload(produto: str, quantidade: int, observacao: str) -> dict:
    return {"produto": produto.strip(), "quantidade": quantidade, "observacao": observacao.strip() or "Nao informado"}


def meta_log_embed(interaction: discord.Interaction, record: dict, payload: dict) -> discord.Embed:
    embed = make_log_embed("Meta registrada", interaction, color=YUNO_BLUE)
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Produto", value=payload["produto"], inline=True)
    embed.add_field(name="Quantidade", value=f"`{payload['quantidade']}`", inline=True)
    embed.add_field(name="Observacao", value=payload["observacao"][:1024], inline=False)
    return embed
