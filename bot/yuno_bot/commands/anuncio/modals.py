import asyncio

import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.anuncio.embeds import anuncio_log_embed, anuncio_post_embed, build_anuncio_payload
from yuno_bot.commands.shared import create_record, send_module_log

EVERYONE_ALLOWED_MENTIONS = discord.AllowedMentions(everyone=True, users=False, roles=False, replied_user=False)


class AnuncioModal(discord.ui.Modal, title="Novo Anúncio"):
    titulo = discord.ui.TextInput(label="Título do anúncio", placeholder="Ex: Reunião da liderança", max_length=256)
    conteudo = discord.ui.TextInput(
        label="Conteúdo", style=discord.TextStyle.paragraph, placeholder="Escreva o conteúdo do anúncio", max_length=2000
    )
    adicionar_arquivo = discord.ui.TextInput(
        label="Adicionar arquivo? (sim/não)", placeholder="sim ou nao", max_length=3, required=False
    )

    def __init__(self, api: YunoAPI, canal: discord.TextChannel):
        super().__init__()
        self.api = api
        self.canal = canal

    async def on_submit(self, interaction: discord.Interaction) -> None:
        com_arquivo = self.adicionar_arquivo.value.strip().lower() in ("sim", "s", "yes", "y", "1")
        payload = build_anuncio_payload(self.titulo.value, self.conteudo.value, com_arquivo)
        embed = anuncio_post_embed(interaction, payload)

        files: list[discord.File] = []
        if com_arquivo:
            await interaction.response.send_message(
                "Envie o arquivo como mensagem neste canal em até **60 segundos**.", ephemeral=True
            )
            files = await self._collect_attachment(interaction)
        else:
            await interaction.response.defer(ephemeral=True)

        if len(files) == 1:
            embed.set_image(url=f"attachment://{files[0].filename}")

        try:
            await self.canal.send(content="@everyone", embed=embed, files=files, allowed_mentions=EVERYONE_ALLOWED_MENTIONS)
        except discord.HTTPException:
            await interaction.followup.send("Não consegui publicar o anúncio no canal.", ephemeral=True)
            return

        try:
            record = await create_record(
                self.api, interaction, module="anuncio", title=f"Anúncio: {payload['titulo']}", payload=payload
            )
        except httpx.HTTPError:
            record = None

        if record:
            await send_module_log(self.api, interaction, "anuncio", anuncio_log_embed(interaction, record, payload))
        await interaction.followup.send("Anúncio publicado com sucesso!", ephemeral=True)

    async def _collect_attachment(self, interaction: discord.Interaction) -> list[discord.File]:
        def check(message: discord.Message) -> bool:
            return (
                message.author.id == interaction.user.id
                and message.channel.id == interaction.channel_id
                and len(message.attachments) > 0
            )

        try:
            message = await interaction.client.wait_for("message", check=check, timeout=60.0)
        except asyncio.TimeoutError:
            await interaction.followup.send("Tempo esgotado. O anúncio foi publicado sem arquivo.", ephemeral=True)
            return []

        try:
            await message.delete()
        except discord.HTTPException:
            pass
        return [await attachment.to_file(use_cached=True) for attachment in message.attachments]

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        message = "Ocorreu um erro ao publicar o anúncio."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
