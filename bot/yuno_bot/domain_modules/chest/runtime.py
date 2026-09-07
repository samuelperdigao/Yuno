from __future__ import annotations

from typing import Any

import discord

from yuno_bot.platform.contracts import ActorContext, RetryableJobError
from yuno_bot.platform.panels import PanelPublisher

MODULE_KEY = "chest"


def system_actor(
    bot: discord.Client, guild_id: int, correlation_id: str
) -> ActorContext:
    if bot.user is None:
        raise RuntimeError("Bot ainda nao esta pronto.")
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
        raise RetryableJobError("Destino do Sistema de Bau nao e um canal de texto.")
    return channel


async def reconcile_panel(
    bot: discord.Client,
    api: Any,
    guild: discord.Guild,
    correlation_id: str,
    chest_id: str,
) -> dict:
    try:
        version = await api.effective_configuration(guild.id, MODULE_KEY)
    except Exception as exc:
        raise RetryableJobError(
            "Configuracao publicada do Sistema de Bau indisponivel."
        ) from exc
    actor = system_actor(bot, guild.id, correlation_id)
    try:
        catalog = await api.chest_catalog(guild.id, actor=actor)
    except Exception as exc:
        raise RetryableJobError(
            "Catalogo publicado do Sistema de Bau indisponivel."
        ) from exc
    chest = next(
        (row for row in catalog.get("chests") or [] if str(row.get("id")) == str(chest_id)),
        None,
    )
    if chest is None or not chest.get("active"):
        raise RetryableJobError("Bau publicado nao encontrado para reconciliacao.")
    channel_id = chest.get("panel_channel_id") or version["data"].get("panel_channel_id")
    if not channel_id:
        raise RetryableJobError("Canal do painel do Bau nao configurado.")
    return await PanelPublisher(bot, api).reconcile(
        guild=guild,
        module_key=MODULE_KEY,
        panel_key="chest",
        channel_id=int(channel_id),
        actor=actor,
        resource_type="chest",
        resource_id=str(chest_id),
        render_context={
            "config": version["data"],
            "config_version": version["version"],
            "chest": chest,
        },
    )


async def deliver_panel(bot: discord.Client, item: dict[str, Any]) -> str | None:
    guild = bot.get_guild(int(item["guild_id"]))
    if guild is None:
        raise RetryableJobError(
            "Guild indisponivel para publicar o painel do Sistema de Bau."
        )
    panel = await reconcile_panel(
        bot,
        bot.platform_api,
        guild,
        str(item.get("correlation_id") or item["id"]),
        str(item.get("resource_id") or (item.get("payload") or {}).get("chest_id") or ""),
    )
    return panel.get("message_id")


async def deliver_log(bot: discord.Client, item: dict[str, Any]) -> str | None:
    guild = bot.get_guild(int(item["guild_id"]))
    if guild is None:
        raise RetryableJobError("Guild indisponivel para log do Sistema de Bau.")
    channel = await _channel(guild, str(item["destination_id"]))
    data = item.get("payload") or {}
    observation = (
        f"\nMotivo/observacao: {data['observation']}" if data.get("observation") else ""
    )
    message = await channel.send(
        "**YUNO NEXUS · MOVIMENTACAO**\n"
        f"{data.get('movement_type')} · {data.get('quantity')} {data.get('unit')}\n"
        f"Bau: {data.get('chest_name')}\n"
        f"Item: {data.get('item_name')}\n"
        f"Saldo: {data.get('balance_before')} → {data.get('balance_after')}\n"
        f"Ator: <@{data.get('actor_id')}> · ID `{data.get('movement_id')}`{observation}",
        allowed_mentions=discord.AllowedMentions.none(),
    )
    return str(message.id)


async def run_job(
    bot: discord.Client, api: Any, item: dict[str, Any]
) -> dict[str, Any]:
    guild = bot.get_guild(int(item["guild_id"]))
    if guild is None:
        raise RetryableJobError(
            "Guild indisponivel para reconciliar o painel do Sistema de Bau."
        )
    await reconcile_panel(
        bot,
        api,
        guild,
        str(item.get("correlation_id") or item["id"]),
        str(item.get("resource_id") or (item.get("payload") or {}).get("chest_id") or ""),
    )
    return {"reconciled": True}


async def startup(bot: discord.Client, api: Any, guild: discord.Guild) -> None:
    try:
        actor = system_actor(bot, guild.id, f"chest-startup:{guild.id}")
        catalog = await api.chest_catalog(guild.id, actor=actor)
    except Exception:
        # Ausencia de configuracao publicada e esperada durante onboarding.
        return
    for chest in catalog.get("chests") or []:
        try:
            await reconcile_panel(
                bot,
                api,
                guild,
                f"chest-startup:{guild.id}:{chest['id']}",
                str(chest["id"]),
            )
        except Exception:
            # Um canal ausente nao deve impedir a reconciliacao dos demais baus.
            continue


async def handle_resource_delete(
    bot: discord.Client,
    api: Any,
    guild_id: int,
    resource_id: int,
    resource_type: str | None,
) -> None:
    if resource_type not in {"message", "channel", "thread"}:
        return
    actor = system_actor(
        bot, guild_id, f"chest-delete:{guild_id}:{resource_type}:{resource_id}"
    )
    await api.chest_resource_deleted(
        guild_id,
        {
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "idempotency_key": f"chest:delete:{resource_type}:{resource_id}",
        },
        actor=actor,
    )


async def recover_panel(bot: discord.Client, api: Any, guild: discord.Guild, chest_id: str) -> None:
    await reconcile_panel(bot, api, guild, f"chest-recovery:{guild.id}:{chest_id}", chest_id)
