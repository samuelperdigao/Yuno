import discord

from yuno_bot.commands.shared import YUNO_GREEN, clean_text, make_log_embed


def build_parceria_payload(nome: str, produto_servico: str, contato_principal: str, contato_secundario: str, observacao: str) -> dict[str, str]:
    return {
        "nome": nome.strip(),
        "produto_servico": produto_servico.strip(),
        "contato_principal": clean_text(contato_principal),
        "contato_secundario": clean_text(contato_secundario),
        "observacao": clean_text(observacao),
    }


def parceria_post_embed(interaction: discord.Interaction, record: dict, payload: dict[str, str]) -> discord.Embed:
    embed = discord.Embed(title="Parceria cadastrada", color=YUNO_GREEN, timestamp=discord.utils.utcnow())
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Nome", value=payload["nome"], inline=True)
    embed.add_field(name="Produto/servico", value=payload["produto_servico"], inline=False)
    embed.add_field(name="Contato principal", value=payload["contato_principal"], inline=True)
    embed.add_field(name="Contato secundario", value=payload["contato_secundario"], inline=True)
    embed.add_field(name="Observacao", value=payload["observacao"][:1024], inline=False)
    embed.set_footer(text=f"Cadastrada por {interaction.user.display_name}")
    return embed


def parceria_log_embed(interaction: discord.Interaction, record: dict, payload: dict[str, str]) -> discord.Embed:
    embed = make_log_embed("Parceria cadastrada", interaction, color=YUNO_GREEN)
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Nome", value=payload["nome"], inline=True)
    embed.add_field(name="Produto/servico", value=payload["produto_servico"], inline=False)
    return embed
