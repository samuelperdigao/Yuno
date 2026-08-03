import discord

from yuno_bot.commands.shared import YUNO_ORANGE, clean_text, make_log_embed


def encomenda_panel_embed(guild_name: str | None = None) -> discord.Embed:
    embed = discord.Embed(
        title="📦 Central de Encomendas",
        description=(
            "Registre uma nova encomenda pelo botão abaixo.\n\n"
            "Tenha em mãos o item, a quantidade, o prazo e a identificação do cliente ou família."
        ),
        color=YUNO_ORANGE,
    )
    embed.set_footer(text=f"Yuno • Encomendas{f' • {guild_name}' if guild_name else ''}")
    return embed


def build_encomenda_payload(item: str, quantidade: int, prazo: str, cliente_familia: str, valor_observacao: str) -> dict:
    return {
        "item": item.strip(),
        "quantidade": quantidade,
        "prazo": prazo.strip(),
        "cliente_familia": cliente_familia.strip(),
        "valor_observacao": clean_text(valor_observacao),
    }


def encomenda_post_embed(interaction: discord.Interaction, record: dict, payload: dict) -> discord.Embed:
    embed = discord.Embed(title="Nova encomenda", color=YUNO_ORANGE, timestamp=discord.utils.utcnow())
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Cliente/Familia", value=payload["cliente_familia"], inline=True)
    embed.add_field(name="Item", value=payload["item"], inline=False)
    embed.add_field(name="Quantidade", value=f"`{payload['quantidade']}`", inline=True)
    embed.add_field(name="Prazo", value=payload["prazo"], inline=True)
    embed.add_field(name="Valor/observacao", value=payload["valor_observacao"][:1024], inline=False)
    embed.set_footer(text=f"Criada por {interaction.user.display_name}")
    return embed


def encomenda_log_embed(interaction: discord.Interaction, record: dict, payload: dict) -> discord.Embed:
    embed = make_log_embed("Encomenda criada", interaction, color=YUNO_ORANGE)
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Item", value=payload["item"], inline=True)
    embed.add_field(name="Quantidade", value=f"`{payload['quantidade']}`", inline=True)
    embed.add_field(name="Cliente/Familia", value=payload["cliente_familia"], inline=False)
    return embed
