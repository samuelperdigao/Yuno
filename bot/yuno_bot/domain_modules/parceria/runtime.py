from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import discord

from yuno_bot.platform.contracts import ActorContext, RetryableJobError
from yuno_bot.platform.panels import PanelPublisher


MODULE_KEY = "parceria"


def system_actor(bot: discord.Client, guild_id: int, correlation_id: str) -> ActorContext:
    if bot.user is None:
        raise RuntimeError("Bot ainda não está pronto.")
    return ActorContext(
        guild_id=guild_id,
        user_id=bot.user.id,
        role_ids=(),
        discord_permissions=(),
        channel_id=None,
        category_id=None,
        actor_type="system",
        is_guild_owner=False,
        correlation_id=correlation_id,
    )


async def _channel(guild: discord.Guild, channel_id: str):
    channel = guild.get_channel(int(channel_id))
    if channel is None:
        channel = await guild.fetch_channel(int(channel_id))
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        raise TypeError("O destino precisa ser um canal de texto ou thread.")
    return channel


def _embed(item: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(title=f"🤝 {item.get('family_name') or 'Parceria'}", description=f"Produto: **{item.get('product_name') or 'Não informado'}**", color=0xFFC72C)
    contacts = item.get("contacts") or []
    if contacts:
        embed.add_field(name="Contato", value="\n".join(str(value) for value in contacts), inline=False)
    image = item.get("image") or {}
    if image.get("storage_url", "").startswith(("https://", "http://")):
        embed.set_image(url=image["storage_url"])
    return embed


async def deliver_publication(bot: discord.Client, item: dict[str, Any]) -> str | None:
    guild = bot.get_guild(int(item["guild_id"]))
    if guild is None:
        raise RetryableJobError("Guild indisponível para publicar parceria.")
    api = bot.platform_api
    parceria = await api.parceria_get(guild.id, item["resource_id"])
    channel = await _channel(guild, str(item["destination_id"]))
    actor = system_actor(bot, guild.id, str(item.get("correlation_id") or item["id"]))
    revision = int(item.get("payload", {}).get("revision") or parceria.get("publication_revision") or 1)
    old_channel_id = parceria.get("public_channel_id")
    old_message_id = parceria.get("public_message_id")
    if old_channel_id and old_message_id and str(old_channel_id) != str(channel.id):
        try:
            old_channel = await _channel(guild, str(old_channel_id))
            old_message = await old_channel.fetch_message(int(old_message_id))
            if bot.user is None or old_message.author.id == bot.user.id:
                await old_message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass
        old_message_id = None

    message = None
    if parceria.get("status") != "inactive" and old_message_id:
        try:
            message = await channel.fetch_message(int(old_message_id))
            await message.edit(embed=_embed(parceria))
        except discord.NotFound:
            message = None
    if parceria.get("status") == "inactive":
        if old_message_id:
            try:
                message = await channel.fetch_message(int(old_message_id))
                if bot.user is None or message.author.id == bot.user.id:
                    await message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass
        await api.parceria_publication_result(guild.id, parceria["id"], {"revision": revision, "status": "published", "channel_id": str(channel.id), "message_id": None}, actor=actor)
        return None
    if message is None:
        message = await channel.send(embed=_embed(parceria))
    await api.parceria_publication_result(guild.id, parceria["id"], {"revision": revision, "status": "published", "channel_id": str(channel.id), "message_id": str(message.id)}, actor=actor)
    return str(message.id)


async def deliver_panel(bot: discord.Client, item: dict[str, Any]) -> str | None:
    guild = bot.get_guild(int(item["guild_id"]))
    if guild is None:
        raise RetryableJobError("Guild indisponível para recuperar painel de Parcerias.")
    version = await bot.platform_api.effective_configuration(guild.id, MODULE_KEY)
    actor = system_actor(bot, guild.id, str(item.get("correlation_id") or item["id"]))
    panel = await PanelPublisher(bot, bot.platform_api).reconcile(guild=guild, module_key=MODULE_KEY, panel_key="global", channel_id=int(version["data"]["registrar_channel_id"]), actor=actor, render_context={"config": version["data"], "config_version": version["version"]})
    return panel.get("message_id")


async def deliver_log(bot: discord.Client, item: dict[str, Any]) -> str | None:
    guild = bot.get_guild(int(item["guild_id"]))
    if guild is None:
        raise RetryableJobError("Guild indisponível para log de Parcerias.")
    channel = await _channel(guild, str(item["destination_id"]))
    payload = item.get("payload") or {}
    message = await channel.send(embed=discord.Embed(title="🤝 Auditoria de Parcerias", description=str(payload.get("summary") or payload.get("reason") or "Operação concluída."), color=0x5865F2))
    return str(message.id)


async def run_job(bot: discord.Client, api: Any, item: dict[str, Any]) -> dict[str, Any]:
    guild = bot.get_guild(int(item["guild_id"]))
    if guild is None:
        raise RetryableJobError("Guild indisponível para job de Parcerias.")
    key = item["key"]
    if key == "parceria.registration.expire":
        actor = system_actor(bot, guild.id, item["correlation_id"])
        return await api._request("POST", f"/guilds/{guild.id}/modules/parceria/recovery/expire", json={"actor": actor.as_payload()}, actor_id=actor.user_id, correlation_id=actor.correlation_id)
    if key == "parceria.panel.reconcile":
        version = await api.effective_configuration(guild.id, MODULE_KEY)
        actor = system_actor(bot, guild.id, item["correlation_id"])
        await PanelPublisher(bot, api).reconcile(guild=guild, module_key=MODULE_KEY, panel_key="global", channel_id=int(version["data"]["registrar_channel_id"]), actor=actor, render_context={"config": version["data"], "config_version": version["version"]})
        return {"reconciled": True}
    return {"handled": key}


async def handle_message(bot: discord.Client, api: Any, message: discord.Message) -> None:
    if message.guild is None or message.author.bot or not message.attachments:
        return
    try:
        pending = await api.parceria_awaiting_image(message.guild.id, actor_id=message.author.id, channel_id=message.channel.id)
        attempt = pending.get("attempt")
        if not attempt:
            return
        attachment = message.attachments[0]
        content_type = attachment.content_type or ""
        payload = {
            "storage_key": f"discord:{message.guild.id}:{attachment.id}:{attachment.filename}",
            "storage_url": attachment.url,
            "content_type": content_type,
            "size_bytes": attachment.size,
            "original_filename": attachment.filename,
        }
        actor = system_actor(bot, message.guild.id, f"parceria-image:{message.id}")
        # O ator real é o autor da mensagem; system_actor aqui só fornece a forma
        # estrutural, substituindo identidade e canal antes do transporte.
        actor = ActorContext(guild_id=message.guild.id, user_id=message.author.id, role_ids=(), discord_permissions=(), channel_id=message.channel.id, category_id=getattr(message.channel, "category_id", None), actor_type="user", is_guild_owner=False, correlation_id=f"parceria-image:{message.id}")
        await api.parceria_attach_image(message.guild.id, attempt["id"], payload, actor=actor)
        await api.parceria_complete_registration(message.guild.id, attempt["id"], actor=actor)
    except Exception:
        bot.log.exception("Falha ao processar imagem de parceria na guild %s", message.guild.id)


async def handle_resource_delete(bot: discord.Client, api: Any, guild_id: int, resource_type: int, resource_id: int, extra: str | None) -> None:
    del bot, api, guild_id, resource_type, resource_id, extra


async def startup(bot: discord.Client, api: Any, guild: discord.Guild) -> None:
    try:
        version = await api.effective_configuration(guild.id, MODULE_KEY)
    except Exception:
        return
    actor = system_actor(bot, guild.id, f"parceria-startup:{guild.id}")
    await PanelPublisher(bot, api).reconcile(guild=guild, module_key=MODULE_KEY, panel_key="global", channel_id=int(version["data"]["registrar_channel_id"]), actor=actor, render_context={"config": version["data"], "config_version": version["version"]})


async def recover_panel(bot: discord.Client, api: Any, guild: discord.Guild) -> None:
    await startup(bot, api, guild)
