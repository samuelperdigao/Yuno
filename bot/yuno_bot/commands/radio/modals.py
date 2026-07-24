import logging

import discord

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.radio.embeds import criar_embed_nova_radio
from yuno_bot.commands.radio.permissions import pode_alterar_radio, resolver_canal_radio


LOGGER = logging.getLogger(__name__)


class RadioModal(discord.ui.Modal, title="📻 Definir Nova Rádio"):
    numero = discord.ui.TextInput(
        label="Número da Rádio",
        placeholder="Ex: 1221",
        max_length=20,
        required=True,
    )

    def __init__(self, api: YunoAPI):
        super().__init__()
        self.api = api

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ Use este painel dentro de um servidor.", ephemeral=True)
            return
        if not pode_alterar_radio(interaction.user):
            await interaction.response.send_message("❌ Apenas gerentes e administradores podem alterar a rádio.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        numero = self.numero.value.strip()
        if not numero:
            await interaction.followup.send("❌ Informe o número da rádio.", ephemeral=True)
            return

        canal = await resolver_canal_radio(self.api, interaction.guild)
        if not canal:
            await interaction.followup.send("❌ Canal de rádio não encontrado.", ephemeral=True)
            return

        novo_nome = f"┃📻-radio-{numero}!"
        try:
            await canal.edit(name=novo_nome, reason=f"Rádio alterada por {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send("❌ Sem permissão para renomear o canal.", ephemeral=True)
            return
        except discord.HTTPException:
            LOGGER.exception("Falha ao renomear canal de radio guild_id=%s channel_id=%s", interaction.guild.id, canal.id)
            await interaction.followup.send("❌ Não consegui renomear o canal de rádio.", ephemeral=True)
            return

        notificou_membros = True
        try:
            await canal.send(
                content="@everyone",
                embed=criar_embed_nova_radio(interaction, numero),
                allowed_mentions=discord.AllowedMentions(everyone=True, users=False, roles=False),
            )
        except discord.Forbidden:
            notificou_membros = False
            LOGGER.warning("Sem permissao para mencionar @everyone no canal de radio guild_id=%s channel_id=%s", interaction.guild.id, canal.id)
        except discord.HTTPException:
            notificou_membros = False
            LOGGER.warning("Falha ao enviar aviso de radio guild_id=%s channel_id=%s", interaction.guild.id, canal.id, exc_info=True)

        linhas = [
            f"✅ Rádio alterada para **{numero}**!",
            f"Canal renomeado para `{novo_nome}`.",
        ]
        if notificou_membros:
            linhas.append("Membros notificados.")
        else:
            linhas.append("Não consegui notificar @everyone; verifique as permissões do bot.")
        await interaction.followup.send("\n".join(linhas), ephemeral=True)
