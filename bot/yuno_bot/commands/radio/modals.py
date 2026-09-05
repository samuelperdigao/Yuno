import discord
import httpx

from yuno_bot import server_setup
from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.radio.embeds import (
    channel_name_for,
    normalize_frequencia,
    radio_announcement_embed,
)

EVERYONE_ALLOWED_MENTIONS = discord.AllowedMentions(everyone=True, users=False, roles=False, replied_user=False)
NO_MENTIONS = discord.AllowedMentions.none()


class RadioModal(discord.ui.Modal, title="Definir Nova Rádio"):
    frequencia = discord.ui.TextInput(
        label="Frequência da rádio",
        placeholder="Ex: 1221",
        max_length=20,
    )

    def __init__(self, api: YunoAPI) -> None:
        super().__init__()
        self.api = api

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            numero = normalize_frequencia(self.frequencia.value)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Use este painel dentro de um servidor.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            config = await self.api.get_guild_config(guild.id)
        except httpx.HTTPError:
            await interaction.followup.send("Não consegui carregar a configuração do servidor.", ephemeral=True)
            return

        channel_id = server_setup.saved_channel_id(config, "radio")
        channel = guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send(
                "O canal de rádio não está configurado. Rode `/yuno configurar` para criá-lo.",
                ephemeral=True,
            )
            return

        avisos: list[str] = []

        renomeado = await self._renomear_canal(channel, numero)
        if not renomeado:
            avisos.append("não consegui renomear o canal (preciso da permissão **Gerenciar Canais**).")

        anunciado, pode_mencionar = await self._anunciar(channel, numero, interaction.user)
        if not anunciado:
            avisos.append("não consegui publicar o anúncio no canal (verifique minhas permissões de envio).")
        elif not pode_mencionar:
            avisos.append("o anúncio foi publicado, mas sem marcar @everyone (falta a permissão **Mencionar @everyone**).")

        await self._registrar(
            guild_id=guild.id,
            user_id=interaction.user.id,
            channel_id=channel.id,
            numero=numero,
            renomeado=renomeado,
            anunciado=anunciado,
        )

        if avisos:
            resumo = "Frequência definida com ressalvas:\n- " + "\n- ".join(avisos)
        else:
            resumo = f"Frequência da rádio definida para **{numero}** em {channel.mention}."
        await interaction.followup.send(resumo, ephemeral=True)

    @staticmethod
    async def _renomear_canal(channel: discord.TextChannel, numero: str) -> bool:
        novo_nome = channel_name_for(numero)
        if channel.name == novo_nome:
            return True
        try:
            await channel.edit(name=novo_nome, reason="Nova frequência de rádio definida pelo Yuno")
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    @staticmethod
    async def _anunciar(
        channel: discord.TextChannel, numero: str, autor: discord.abc.User
    ) -> tuple[bool, bool]:
        embed = radio_announcement_embed(numero, autor)
        guild_me = channel.guild.me
        pode_mencionar = bool(guild_me and channel.permissions_for(guild_me).mention_everyone)
        conteudo = "@everyone" if pode_mencionar else None
        allowed_mentions = EVERYONE_ALLOWED_MENTIONS if pode_mencionar else NO_MENTIONS
        try:
            await channel.send(content=conteudo, embed=embed, allowed_mentions=allowed_mentions)
            return True, pode_mencionar
        except (discord.Forbidden, discord.HTTPException):
            return False, pode_mencionar

    async def _registrar(
        self,
        *,
        guild_id: int,
        user_id: int,
        channel_id: int,
        numero: str,
        renomeado: bool,
        anunciado: bool,
    ) -> None:
        try:
            await self.api.create_record(
                module="radio",
                guild_id=guild_id,
                title=f"Rádio definida: {numero}",
                requester_id=user_id,
                channel_id=channel_id,
                payload={"numero": numero, "canal_renomeado": renomeado, "anuncio_enviado": anunciado},
            )
        except httpx.HTTPError:
            pass

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        message = "Ocorreu um erro ao definir a nova frequência da rádio."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
