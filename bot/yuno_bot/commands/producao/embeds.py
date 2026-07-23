import discord

from yuno_bot.commands.shared import YUNO_GREEN, make_log_embed


def build_producao_payload(produto: str, quantidade: int, observacao: str) -> dict:
    return {
        "produto": produto.strip(),
        "quantidade": quantidade,
        "observacao": observacao.strip() or "Nao informado",
    }


def producao_post_embed(interaction: discord.Interaction, record: dict, payload: dict) -> discord.Embed:
    embed = discord.Embed(title="Producao registrada", color=YUNO_GREEN, timestamp=discord.utils.utcnow())
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Produto", value=payload["produto"], inline=True)
    embed.add_field(name="Quantidade", value=f"`{payload['quantidade']}`", inline=True)
    embed.add_field(name="Observacao", value=payload["observacao"][:1024], inline=False)
    embed.set_footer(text=f"Registrada por {interaction.user.display_name}")
    return embed


def producao_log_embed(interaction: discord.Interaction, record: dict, payload: dict) -> discord.Embed:
    embed = make_log_embed("Producao registrada", interaction, color=YUNO_GREEN)
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Produto", value=payload["produto"], inline=True)
    embed.add_field(name="Quantidade", value=f"`{payload['quantidade']}`", inline=True)
    return embed
