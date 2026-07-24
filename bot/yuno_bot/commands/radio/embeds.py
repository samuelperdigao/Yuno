import discord

from yuno_bot.commands.shared import YUNO_GOLD


def criar_embed_painel_radio() -> discord.Embed:
    embed = discord.Embed(
        title="📻 Central de Rádio",
        description="Atualize a frequência oficial da organização usando o botão abaixo.",
        color=YUNO_GOLD,
    )
    embed.add_field(
        name="📡 Como alterar",
        value="\n".join(
            [
                "`1.` Clique em **Alterar rádio**",
                "`2.` Informe o número da nova frequência",
                "`3.` Confirme para avisar todos os membros",
            ]
        ),
        inline=False,
    )
    embed.add_field(
        name="🔒 Acesso restrito",
        value="Somente **gerentes** e **administradores** podem fazer alterações.",
        inline=False,
    )
    embed.set_footer(text="Yuno • Sistema de Rádio")
    return embed


def criar_embed_nova_radio(interaction: discord.Interaction, numero: str) -> discord.Embed:
    embed = discord.Embed(
        title="📻 Nova Rádio Definida",
        description="\n".join(
            [
                "A rádio do servidor foi alterada!",
                "",
                f"**Sintonize:** `{numero}`",
            ]
        ),
        color=YUNO_GOLD,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text=f"Definido por {interaction.user.display_name} • Yuno")
    return embed
