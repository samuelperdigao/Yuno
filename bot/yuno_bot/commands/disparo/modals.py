import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.disparo.embeds import EVERYONE_ALLOWED_MENTIONS
from yuno_bot.commands.disparo.helpers import valid_member_channels
from yuno_bot.commands.shared import create_record, get_guild_config
from yuno_bot.config import setup_required_message


class DisparoModal(discord.ui.Modal, title="Disparo de Mensagem"):
    mensagem = discord.ui.TextInput(
        label="Mensagem",
        placeholder="Mensagem enviada para todas as pastas privadas dos membros",
        style=discord.TextStyle.paragraph,
        max_length=2000,
    )

    def __init__(self, api: YunoAPI):
        super().__init__()
        self.api = api

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Use este painel dentro de um servidor.", ephemeral=True)
            return

        config = await get_guild_config(self.api, interaction.guild.id)
        category_id = ((config.get("settings") or {}).get("farm_tickets") or {}).get("folders_category_id")
        if not category_id:
            await interaction.response.send_message(
                setup_required_message(
                    "Farm Tickets",
                    "Categoria de pastas de membro não configurada. Rode `/setup_farm_tickets` primeiro.",
                ),
                ephemeral=True,
            )
            return
        category = interaction.guild.get_channel(int(category_id))
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message("Categoria de pastas de membro não encontrada.", ephemeral=True)
            return

        canais = valid_member_channels(category)
        if not canais:
            await interaction.response.send_message("Nenhuma pasta de membro válida encontrada para envio.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        bot_member = interaction.guild.me
        texto = f"@everyone\n{self.mensagem.value}"
        enviados: list[dict[str, str]] = []
        for canal in canais:
            if bot_member is None:
                break
            permissoes = canal.permissions_for(bot_member)
            if not permissoes.view_channel or not permissoes.send_messages:
                continue
            try:
                mensagem_enviada = await canal.send(texto, allowed_mentions=EVERYONE_ALLOWED_MENTIONS)
            except discord.HTTPException:
                continue
            enviados.append({"channel_id": str(canal.id), "message_id": str(mensagem_enviada.id)})

        if enviados:
            try:
                record = await create_record(
                    self.api,
                    interaction,
                    module="disparo",
                    title="Disparo de mensagem",
                    payload={"mensagem": self.mensagem.value, "enviados": enviados},
                )
                settings = dict(config.get("settings") or {})
                disparo_settings = dict(settings.get("disparo") or {})
                disparo_settings["last_batch_record_id"] = record["id"]
                settings["disparo"] = disparo_settings
                updated_config = {
                    "guild_name": config.get("guild_name"),
                    "admin_role_ids": config.get("admin_role_ids") or [],
                    "log_channel_id": config.get("log_channel_id"),
                    "modules": config.get("modules") or {},
                    "command_permissions": config.get("command_permissions") or {},
                    "messages": config.get("messages") or {},
                    "settings": settings,
                }
                await self.api.save_guild_config(interaction.guild.id, updated_config)
            except httpx.HTTPError:
                # As mensagens ja foram enviadas -- so a referencia pra "apagar ultimo
                # disparo" nao foi salva. Nao vale travar a resposta por isso.
                pass

        await interaction.followup.send(f"Mensagem enviada para {len(enviados)} de {len(canais)} pasta(s).", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        message = "Ocorreu um erro ao processar o disparo."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
