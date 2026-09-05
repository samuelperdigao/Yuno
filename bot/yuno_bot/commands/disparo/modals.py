from __future__ import annotations

import logging

import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.disparo.embeds import EVERYONE_ALLOWED_MENTIONS, log_envio_embed
from yuno_bot.commands.disparo.helpers import send_log, valid_target_channels

log = logging.getLogger(__name__)


class DisparoModal(discord.ui.Modal, title="Disparo de Mensagem"):
    mensagem = discord.ui.TextInput(
        label="Mensagem",
        placeholder="Mensagem enviada para todos os canais privados configurados",
        style=discord.TextStyle.paragraph,
        max_length=2000,
    )

    def __init__(self, api: YunoAPI) -> None:
        super().__init__()
        self.api = api

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Use este painel dentro de um servidor.", ephemeral=True)
            return

        try:
            config = await self.api.get_guild_config(interaction.guild.id)
        except httpx.HTTPError:
            await interaction.response.send_message(
                "Não consegui carregar a configuração do servidor.", ephemeral=True
            )
            return

        disparo_settings = (config.get("settings") or {}).get("disparo") or {}
        category_id = disparo_settings.get("target_category_id")
        if not category_id:
            await interaction.response.send_message(
                "Categoria de destino não configurada. Rode `/disparo painel` primeiro.", ephemeral=True
            )
            return
        category = interaction.guild.get_channel(int(category_id))
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message("Categoria de destino não encontrada.", ephemeral=True)
            return

        canais = valid_target_channels(category, disparo_settings.get("excluded_channel_ids"))
        if not canais:
            await interaction.response.send_message("Nenhum canal válido encontrado para envio.", ephemeral=True)
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
                log.info("disparo: pulando #%s (%s) sem permissao de envio", canal.id, canal.name)
                continue
            try:
                mensagem_enviada = await canal.send(texto, allowed_mentions=EVERYONE_ALLOWED_MENTIONS)
            except discord.HTTPException as exc:
                log.info("disparo: falha ao enviar em #%s (%s): %s", canal.id, canal.name, exc)
                continue
            enviados.append({"channel_id": str(canal.id), "message_id": str(mensagem_enviada.id)})

        if enviados:
            try:
                record = await self.api.create_record(
                    module="disparo",
                    guild_id=interaction.guild.id,
                    title="Disparo de mensagem",
                    requester_id=interaction.user.id,
                    channel_id=interaction.channel_id,
                    payload={"mensagem": self.mensagem.value, "enviados": enviados},
                )
                settings = dict(config.get("settings") or {})
                novo_disparo_settings = dict(settings.get("disparo") or {})
                novo_disparo_settings["last_batch_record_id"] = record["id"]
                settings["disparo"] = novo_disparo_settings
                updated_config = {
                    "guild_name": config.get("guild_name"),
                    "admin_role_ids": config.get("admin_role_ids") or [],
                    "log_channel_id": config.get("log_channel_id"),
                    "modules": config.get("modules") or {},
                    "command_permissions": config.get("command_permissions") or {},
                    "messages": config.get("messages") or {},
                    "settings": settings,
                }
                await self.api.save_guild_config(interaction.guild.id, updated_config, actor_id=interaction.user.id)
            except httpx.HTTPError:
                # As mensagens ja foram enviadas -- so a referencia pra "apagar
                # ultimo disparo" nao foi salva. Nao vale travar a resposta por isso.
                pass

        await send_log(
            interaction.guild,
            config,
            log_envio_embed(
                autor=interaction.user,
                enviados=len(enviados),
                total=len(canais),
                categoria=category.name,
            ),
        )

        if len(enviados) < len(canais):
            await interaction.followup.send(
                f"Mensagem enviada para {len(enviados)} de {len(canais)} canal(is). "
                f"{len(canais) - len(enviados)} canal(is) foram ignorados (sem permissão ou erro do Discord).",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(f"Mensagem enviada para {len(enviados)} canal(is).", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("Erro ao processar disparo", exc_info=error)
        message = "Ocorreu um erro ao processar o disparo."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
