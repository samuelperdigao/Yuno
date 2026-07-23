import discord

from yuno_bot.commands.shared import YUNO_GOLD, make_log_embed


def build_radio_payload(radio_atual: str, radio_nova: str, motivo: str) -> dict[str, str]:
    return {
        "radio_atual": radio_atual.strip(),
        "radio_nova": radio_nova.strip(),
        "motivo": motivo.strip(),
    }


def radio_post_embed(interaction: discord.Interaction, record: dict, payload: dict[str, str]) -> discord.Embed:
    embed = discord.Embed(title="Radio alterada", color=YUNO_GOLD, timestamp=discord.utils.utcnow())
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Radio anterior", value=f"`{payload['radio_atual']}`", inline=True)
    embed.add_field(name="Radio nova", value=f"`{payload['radio_nova']}`", inline=True)
    embed.add_field(name="Motivo", value=payload["motivo"][:1024], inline=False)
    embed.set_footer(text=f"Alterada por {interaction.user.display_name}")
    return embed


def radio_log_embed(interaction: discord.Interaction, record: dict, payload: dict[str, str]) -> discord.Embed:
    embed = make_log_embed("Radio alterada", interaction, color=YUNO_GOLD)
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="De", value=f"`{payload['radio_atual']}`", inline=True)
    embed.add_field(name="Para", value=f"`{payload['radio_nova']}`", inline=True)
    embed.add_field(name="Motivo", value=payload["motivo"][:1024], inline=False)
    return embed
