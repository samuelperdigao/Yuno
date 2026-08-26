from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import discord
import httpx

from yuno_bot.domain_modules.farm_tickets.api import FarmTicketsAPI
from yuno_bot.platform.contracts import ActorContext, RetryableJobError
from yuno_bot.platform.panels import PanelPublisher

MAX_GUILD_CHANNELS = 500
MAX_CATEGORY_CHANNELS = 50


def _system_actor(
    bot: discord.Client, guild_id: int, correlation_id: str
) -> ActorContext:
    if bot.user is None:
        raise RuntimeError("Bot ainda nao possui identidade Discord.")
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


def _binding(bindings: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    priority = {"ACTIVE": 0, "PROVISIONING": 1, "MISSING": 2, "DELETE_PENDING": 3}
    candidates = [
        item for item in bindings if item["kind"] == kind and item["state"] != "DELETED"
    ]
    return min(
        candidates, key=lambda item: priority.get(item["state"], 99), default=None
    )


async def _record_binding(
    api: FarmTicketsAPI,
    *,
    guild_id: int,
    actor: ActorContext,
    ticket_id: str | None,
    kind: str,
    resource_id: int,
    parent_resource_id: int | None,
    ownership: str,
) -> dict[str, Any]:
    return await api.upsert_binding(
        guild_id,
        {
            "ticket_id": ticket_id,
            "kind": kind,
            "resource_id": str(resource_id),
            "parent_resource_id": (
                str(parent_resource_id) if parent_resource_id is not None else None
            ),
            "ownership": ownership,
            "idempotency_key": f"binding:{kind}:{resource_id}",
        },
        actor=actor.as_payload(),
    )


async def _mark_missing(
    api: FarmTicketsAPI,
    *,
    guild_id: int,
    actor: ActorContext,
    binding: dict[str, Any],
) -> None:
    if binding["state"] == "MISSING":
        return
    await api.resource_deleted(
        guild_id,
        int(binding["resource_id"]),
        datetime.now(timezone.utc).isoformat(),
        {
            "CATEGORY": "category",
            "GLOBAL_PANEL_CHANNEL": "channel",
            "LOG_CHANNEL": "channel",
            "TICKET_CHANNEL": "channel",
            "GLOBAL_PANEL_MESSAGE": "message",
            "TICKET_PANEL_MESSAGE": "message",
            "TICKET_MAIN_MESSAGE": "message",
            "TICKET_THREAD": "thread",
        }.get(binding["kind"]),
        actor=actor.as_payload(),
    )


async def _ensure_global_resources(
    bot: discord.Client,
    platform_api: Any,
    guild: discord.Guild,
    actor: ActorContext,
    *,
    publish_panel: bool = True,
) -> tuple[discord.CategoryChannel, discord.TextChannel, discord.TextChannel]:
    api = FarmTicketsAPI(platform_api)
    config_ref = await platform_api.effective_configuration(guild.id, "farm_tickets")
    config = config_ref["data"]
    bindings = await api.bindings(guild.id)

    configured_category_id = int(config["category_id"])
    category = guild.get_channel(configured_category_id)
    category_binding = next(
        (
            item
            for item in bindings
            if item["kind"] == "CATEGORY"
            and item["resource_id"] == str(configured_category_id)
            and item["state"] != "DELETED"
        ),
        None,
    )
    ownership = "ADOPTED"
    if not isinstance(category, discord.CategoryChannel):
        if category_binding is not None:
            await _mark_missing(
                api, guild_id=guild.id, actor=actor, binding=category_binding
            )
        recovered = next(
            (
                (item, channel)
                for item in bindings
                if item["kind"] == "CATEGORY" and item["state"] == "ACTIVE"
                if isinstance(
                    (channel := guild.get_channel(int(item["resource_id"]))),
                    discord.CategoryChannel,
                )
                and channel.name.casefold() == "tickets de farm"
            ),
            None,
        )
        if recovered is not None:
            category_binding, category = recovered
            ownership = category_binding["ownership"]
        else:
            if len(guild.channels) >= MAX_GUILD_CHANNELS:
                raise RuntimeError(
                    "A guild atingiu o limite global de canais do Discord."
                )
            category = await guild.create_category(
                "TICKETS DE FARM", reason="Yuno Tickets V2: recovery da categoria"
            )
            ownership = "MANAGED"
    await _record_binding(
        api,
        guild_id=guild.id,
        actor=actor,
        ticket_id=None,
        kind="CATEGORY",
        resource_id=category.id,
        parent_resource_id=None,
        ownership=ownership,
    )

    async def text_resource(
        config_key: str, kind: str, fallback_name: str
    ) -> discord.TextChannel:
        configured_id = int(config[config_key])
        current = guild.get_channel(configured_id)
        existing = next(
            (
                item
                for item in bindings
                if item["kind"] == kind
                and item["resource_id"] == str(configured_id)
                and item["state"] != "DELETED"
            ),
            None,
        )
        resource_ownership = "ADOPTED"
        if not isinstance(current, discord.TextChannel):
            if existing is not None:
                await _mark_missing(
                    api, guild_id=guild.id, actor=actor, binding=existing
                )
            existing = _binding(bindings, kind)
            recovered = (
                guild.get_channel(int(existing["resource_id"]))
                if existing is not None and existing["state"] == "ACTIVE"
                else None
            )
            if isinstance(recovered, discord.TextChannel):
                assert existing is not None
                current = recovered
                resource_ownership = existing["ownership"]
            else:
                if len(guild.channels) >= MAX_GUILD_CHANNELS:
                    raise RuntimeError(
                        "A guild atingiu o limite global de canais do Discord."
                    )
                current = await guild.create_text_channel(
                    fallback_name,
                    category=category,
                    reason=f"Yuno Tickets V2: recovery de {kind}",
                )
                resource_ownership = "MANAGED"
        if current.category_id != category.id:
            await current.edit(
                category=category,
                reason=f"Yuno Tickets V2: recovery da categoria de {kind}",
            )
        await _record_binding(
            api,
            guild_id=guild.id,
            actor=actor,
            ticket_id=None,
            kind=kind,
            resource_id=current.id,
            parent_resource_id=current.category_id,
            ownership=resource_ownership,
        )
        return current

    panel_channel = await text_resource(
        "panel_channel_id", "GLOBAL_PANEL_CHANNEL", "abrir-ticket-farm"
    )
    log_channel = await text_resource(
        "log_channel_id", "LOG_CHANNEL", "logs-ticket-farm"
    )
    await log_channel.set_permissions(
        guild.default_role,
        view_channel=False,
        reason="Yuno Tickets V2: privacidade dos logs",
    )
    if guild.me is not None:
        await log_channel.set_permissions(
            guild.me,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_threads=True,
            attach_files=True,
            reason="Yuno Tickets V2: permissoes do bot",
        )
    for role_id in config.get("administrator_role_ids") or []:
        role = guild.get_role(int(role_id))
        if role is not None:
            await log_channel.set_permissions(
                role,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                reason="Yuno Tickets V2: cargo administrador publicado",
            )
    if publish_panel:
        panel = await PanelPublisher(bot, platform_api).reconcile(
            guild=guild,
            module_key="farm_tickets",
            panel_key="global",
            channel_id=panel_channel.id,
            actor=actor,
            resource_type="guild",
            resource_id=str(guild.id),
            render_context={"config_version": config_ref.get("version")},
        )
        await _record_binding(
            api,
            guild_id=guild.id,
            actor=actor,
            ticket_id=None,
            kind="GLOBAL_PANEL_MESSAGE",
            resource_id=int(panel["message_id"]),
            parent_resource_id=panel_channel.id,
            ownership="MANAGED",
        )
    return category, panel_channel, log_channel


async def _select_ticket_category(
    guild: discord.Guild,
    api: FarmTicketsAPI,
    actor: ActorContext,
    primary: discord.CategoryChannel,
) -> discord.CategoryChannel:
    bindings = await api.bindings(guild.id)
    categories: list[discord.CategoryChannel] = [primary]
    for binding in bindings:
        if binding["kind"] != "CATEGORY" or binding["state"] != "ACTIVE":
            continue
        channel = guild.get_channel(int(binding["resource_id"]))
        if isinstance(channel, discord.CategoryChannel) and channel.id != primary.id:
            categories.append(channel)
    for category in categories:
        if len(category.channels) < MAX_CATEGORY_CHANNELS:
            return category
    if len(guild.channels) >= MAX_GUILD_CHANNELS:
        raise RuntimeError("A guild atingiu o limite global de canais do Discord.")
    suffix = 2
    existing_names = {item.name.casefold() for item in guild.categories}
    while f"tickets de farm {suffix}" in existing_names:
        suffix += 1
    category = await guild.create_category(
        f"TICKETS DE FARM {suffix}", reason="Yuno Tickets V2: categoria cheia"
    )
    await _record_binding(
        api,
        guild_id=guild.id,
        actor=actor,
        ticket_id=None,
        kind="CATEGORY",
        resource_id=category.id,
        parent_resource_id=None,
        ownership="MANAGED",
    )
    return category


def _ticket_channel_name(ticket: dict[str, Any]) -> str:
    raw = f"ticket-{ticket['player_id']}-{ticket['member_name']}".casefold()
    normalized = re.sub(r"[^a-z0-9-]+", "-", raw).strip("-")
    return (normalized or f"ticket-{ticket['member_id']}")[:90]


def _ticket_log_embed(ticket: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(
        title=f"Ticket de Farm — {ticket['member_name']}",
        description=(
            f"Membro: <@{ticket['member_id']}>\n"
            f"ID: `{ticket['player_id']}`\n"
            f"Status: **{ticket['status']}**\n"
            f"Progresso geral: **{ticket['progress_percent']}%**"
        ),
        color=discord.Color.green()
        if ticket["status"] == "APPROVED"
        else discord.Color.gold(),
    )
    for objective in ticket["objectives"]:
        embed.add_field(
            name=objective["name"],
            value=(
                f"Meta: {objective['target']}\n"
                f"Lançado: {objective['launched']}\n"
                f"Recolhido: {objective['withdrawn']}\n"
                f"Saldo não recolhido: {objective['available']}"
            ),
            inline=False,
        )
    embed.add_field(
        name="Responsável",
        value=(
            f"<@{ticket['assigned_admin_id']}>"
            if ticket.get("assigned_admin_id")
            else "Não assumido"
        ),
        inline=False,
    )
    return embed


async def _sync_ticket_log(
    api: FarmTicketsAPI,
    guild: discord.Guild,
    log_channel: discord.TextChannel,
    ticket: dict[str, Any],
    actor: ActorContext,
) -> tuple[discord.Message, discord.Thread]:
    bindings = await api.bindings(guild.id, ticket_id=ticket["id"])
    main_binding = _binding(bindings, "TICKET_MAIN_MESSAGE")
    message: discord.Message | None = None
    if main_binding is not None:
        parent = guild.get_channel(
            int(main_binding.get("parent_resource_id") or log_channel.id)
        )
        if isinstance(parent, discord.TextChannel):
            try:
                message = await parent.fetch_message(int(main_binding["resource_id"]))
            except discord.NotFound:
                await _mark_missing(
                    api, guild_id=guild.id, actor=actor, binding=main_binding
                )
    embed = _ticket_log_embed(ticket)
    if message is None:
        message = await log_channel.send(
            embed=embed, allowed_mentions=discord.AllowedMentions.none()
        )
    else:
        await message.edit(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    await _record_binding(
        api,
        guild_id=guild.id,
        actor=actor,
        ticket_id=ticket["id"],
        kind="TICKET_MAIN_MESSAGE",
        resource_id=message.id,
        parent_resource_id=log_channel.id,
        ownership="MANAGED",
    )

    bindings = await api.bindings(guild.id, ticket_id=ticket["id"])
    thread_binding = _binding(bindings, "TICKET_THREAD")
    thread = (
        guild.get_thread(int(thread_binding["resource_id"]))
        if thread_binding is not None
        else None
    )
    if thread is None and thread_binding is None:
        # Threads publicas iniciadas por mensagem reutilizam o snowflake da
        # mensagem inicial. Um crash entre o create e o binding deve adotar a
        # thread existente, nao tentar cria-la novamente.
        thread = guild.get_thread(message.id)
        if thread is None:
            try:
                fetched = await guild.fetch_channel(message.id)
                thread = fetched if isinstance(fetched, discord.Thread) else None
            except (discord.NotFound, KeyError):
                thread = None
    if thread is None and thread_binding is not None:
        try:
            fetched = await guild.fetch_channel(int(thread_binding["resource_id"]))
            thread = fetched if isinstance(fetched, discord.Thread) else None
        except discord.NotFound:
            await _mark_missing(
                api, guild_id=guild.id, actor=actor, binding=thread_binding
            )
    if thread is None:
        thread = await message.create_thread(
            name=f"historico-{ticket['player_id']}"[:100],
            auto_archive_duration=10080,
            reason="Yuno Tickets V2: thread de log",
        )
    await _record_binding(
        api,
        guild_id=guild.id,
        actor=actor,
        ticket_id=ticket["id"],
        kind="TICKET_THREAD",
        resource_id=thread.id,
        parent_resource_id=log_channel.id,
        ownership="MANAGED",
    )
    return message, thread


async def _provision_ticket(
    bot: discord.Client,
    platform_api: Any,
    guild: discord.Guild,
    ticket_id: str,
    actor: ActorContext,
) -> dict[str, Any]:
    api = FarmTicketsAPI(platform_api)
    ticket = await api.ticket(guild.id, ticket_id)
    primary, _, log_channel = await _ensure_global_resources(
        bot, platform_api, guild, actor, publish_panel=True
    )
    log_message, log_thread = await _sync_ticket_log(
        api, guild, log_channel, ticket, actor
    )
    if ticket["binding_released"]:
        cleaned = await _cleanup_ticket_resources(
            bot, platform_api, guild, ticket_id, actor
        )
        return {
            **cleaned,
            "log_message_id": str(log_message.id),
            "thread_id": str(log_thread.id),
        }
    bindings = await api.bindings(guild.id, ticket_id=ticket_id)
    channel_binding = _binding(bindings, "TICKET_CHANNEL")
    channel = (
        guild.get_channel(int(channel_binding["resource_id"]))
        if channel_binding is not None
        else None
    )
    if not isinstance(channel, discord.TextChannel):
        if channel_binding is not None:
            await _mark_missing(
                api, guild_id=guild.id, actor=actor, binding=channel_binding
            )
        if len(guild.channels) >= MAX_GUILD_CHANNELS:
            raise RuntimeError("A guild atingiu o limite global de canais do Discord.")
        category = await _select_ticket_category(guild, api, actor, primary)
        member = guild.get_member(int(ticket["member_id"]))
        if member is None:
            try:
                member = await guild.fetch_member(int(ticket["member_id"]))
            except discord.NotFound:
                member = None
        overwrites: dict[Any, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
        }
        if guild.me is not None:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_threads=True,
                attach_files=True,
            )
        if member is not None:
            overwrites[member] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            )
        config = (await platform_api.effective_configuration(guild.id, "farm_tickets"))[
            "data"
        ]
        for role_id in config.get("administrator_role_ids") or []:
            role = guild.get_role(int(role_id))
            if role is not None:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                )
        channel = await guild.create_text_channel(
            _ticket_channel_name(ticket),
            category=category,
            overwrites=overwrites,
            topic=f"Yuno Farm Ticket V2 {ticket_id}",
            reason="Yuno Tickets V2: provisioning",
        )
    member = guild.get_member(int(ticket["member_id"]))
    if member is None:
        try:
            member = await guild.fetch_member(int(ticket["member_id"]))
        except discord.NotFound:
            member = None
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
    }
    if guild.me is not None:
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_threads=True,
            attach_files=True,
        )
    if member is not None:
        overwrites[member] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
        )
    config = (await platform_api.effective_configuration(guild.id, "farm_tickets"))[
        "data"
    ]
    for role_id in config.get("administrator_role_ids") or []:
        role = guild.get_role(int(role_id))
        if role is not None:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            )
    await channel.edit(
        overwrites=overwrites,
        reason="Yuno Tickets V2: reconciliacao de permissoes publicadas",
    )
    await _record_binding(
        api,
        guild_id=guild.id,
        actor=actor,
        ticket_id=ticket_id,
        kind="TICKET_CHANNEL",
        resource_id=channel.id,
        parent_resource_id=channel.category_id,
        ownership="MANAGED",
    )
    panel = await PanelPublisher(bot, platform_api).reconcile(
        guild=guild,
        module_key="farm_tickets",
        panel_key="ticket",
        channel_id=channel.id,
        actor=actor,
        resource_type="farm_ticket",
        resource_id=ticket_id,
        render_context={"ticket": ticket},
    )
    await _record_binding(
        api,
        guild_id=guild.id,
        actor=actor,
        ticket_id=ticket_id,
        kind="TICKET_PANEL_MESSAGE",
        resource_id=int(panel["message_id"]),
        parent_resource_id=channel.id,
        ownership="MANAGED",
    )
    await api.provisioning_error(
        guild.id, ticket_id, actor=actor.as_payload(), error=None
    )
    return {
        "ticket_id": ticket_id,
        "channel_id": str(channel.id),
        "log_message_id": str(log_message.id),
        "thread_id": str(log_thread.id),
    }


async def _delete_binding_resource(
    guild: discord.Guild, binding: dict[str, Any]
) -> None:
    kind = binding["kind"]
    resource_id = int(binding["resource_id"])
    if kind in {"TICKET_PANEL_MESSAGE", "TICKET_MAIN_MESSAGE"}:
        parent_id = binding.get("parent_resource_id")
        channel = guild.get_channel(int(parent_id)) if parent_id else None
        if isinstance(channel, discord.TextChannel):
            try:
                message = await channel.fetch_message(resource_id)
                await message.delete()
            except discord.NotFound:
                pass
        return
    channel = guild.get_channel(resource_id) or guild.get_thread(resource_id)
    if channel is None:
        try:
            channel = await guild.fetch_channel(resource_id)
        except discord.NotFound:
            return
    if isinstance(channel, (discord.Thread, discord.TextChannel)):
        await channel.delete(reason="Yuno Tickets V2: cleanup terminal")


async def _cleanup_ticket_resources(
    bot: discord.Client,
    platform_api: Any,
    guild: discord.Guild,
    ticket_id: str,
    actor: ActorContext,
) -> dict[str, Any]:
    del bot
    api = FarmTicketsAPI(platform_api)
    state = await api.cleanup_state(guild.id, ticket_id)
    if not state["ready"]:
        raise RetryableJobError(
            "Cleanup aguarda copia dos comprovantes na thread.",
            retry_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        )
    bindings = await api.bindings(guild.id, ticket_id=ticket_id)
    order = {
        "TICKET_PANEL_MESSAGE": 0,
        "TICKET_MAIN_MESSAGE": 0,
        "TICKET_THREAD": 1,
        "TICKET_CHANNEL": 2,
    }
    deleted = 0
    for binding in sorted(bindings, key=lambda item: order.get(item["kind"], 99)):
        if (
            binding["ownership"] != "MANAGED"
            or binding["state"] != "DELETE_PENDING"
            or binding["kind"] not in {"TICKET_PANEL_MESSAGE", "TICKET_CHANNEL"}
        ):
            continue
        await _delete_binding_resource(guild, binding)
        await api.binding_deleted(
            guild.id,
            binding["id"],
            actor=actor.as_payload(),
            idempotency_key=f"binding:{binding['id']}:deleted",
        )
        deleted += 1
    return {"ticket_id": ticket_id, "deleted_bindings": deleted}


async def run_job(bot: discord.Client, platform_api: Any, item: dict[str, Any]) -> dict:
    guild = bot.get_guild(int(item["guild_id"]))
    if guild is None:
        raise RuntimeError("Guild indisponivel para Tickets de Farm.")
    api = FarmTicketsAPI(platform_api)
    actor = _system_actor(bot, guild.id, str(item["correlation_id"]))
    payload = item.get("payload") or {}
    key = item["key"]
    if key == "farm_tickets.proof.process":
        ticket = await api.ticket(guild.id, str(payload["ticket_id"]))
        return await api.process_proof(
            guild.id,
            str(payload["ticket_id"]),
            str(payload["operation_id"]),
            {
                "expected_version": ticket["revision"],
                "idempotency_key": f"job:{item['id']}",
                "claim_token": payload["claim_token"],
            },
            actor=actor.as_payload(),
        )
    if key == "farm_tickets.operation.expire":
        return await api.expire_operation(
            guild.id,
            str(payload["operation_id"]),
            actor=actor.as_payload(),
            idempotency_key=f"job:{item['id']}",
        )
    if key == "farm_tickets.meta.consume":
        last: dict[str, Any] = {}
        for _ in range(20):
            last = await api.consume_meta(guild.id, actor=actor.as_payload(), limit=100)
            if last.get("blocked"):
                raise RetryableJobError(
                    "Evento Meta aguarda processamento de comprovante "
                    "recebido no prazo.",
                    retry_at=datetime.now(timezone.utc) + timedelta(seconds=15),
                )
            if not last.get("has_more"):
                return last
        raise RetryableJobError("Journal Meta possui mais paginas.")
    if key == "farm_tickets.storage.cleanup":
        result = await api.cleanup_storage(
            guild.id,
            str(payload["ticket_id"]),
            actor=actor.as_payload(),
            idempotency_key=f"job:{item['id']}",
        )
        if result.get("retained"):
            raise RetryableJobError(
                "Objetos retidos ate a copia na thread ser confirmada.",
                retry_at=datetime.now(timezone.utc) + timedelta(seconds=30),
            )
        return result
    if key == "farm_tickets.provision":
        try:
            return await _provision_ticket(
                bot,
                platform_api,
                guild,
                str(payload.get("ticket_id") or item["resource_id"]),
                actor,
            )
        except Exception as exc:
            ticket_id = str(payload.get("ticket_id") or item["resource_id"])
            try:
                await api.provisioning_error(
                    guild.id,
                    ticket_id,
                    actor=actor.as_payload(),
                    error=f"{type(exc).__name__}: {exc}",
                )
            except Exception:
                pass
            raise
    if key == "farm_tickets.reconcile":
        instance = await platform_api.module_instance(guild.id, "farm_tickets")
        if instance.get("published_config_version_id") is None:
            # Modulo ligado e ainda nao configurado e um estado valido: nada e
            # provisionado ate a Central publicar categoria, canais e cargos.
            return {"skipped": "unpublished_configuration"}
        for _ in range(20):
            result = await api.consume_meta(
                guild.id, actor=actor.as_payload(), limit=100
            )
            if result.get("blocked"):
                raise RetryableJobError(
                    "Bootstrap aguarda comprovante recebido no prazo.",
                    retry_at=datetime.now(timezone.utc) + timedelta(seconds=15),
                )
            if not result.get("has_more"):
                break
        await _ensure_global_resources(
            bot, platform_api, guild, actor, publish_panel=True
        )
        reconciled = 0
        for ticket in await api.tickets(
            guild.id, active_only=False, reconcile_only=True
        ):
            bindings = await api.bindings(guild.id, ticket_id=ticket["id"])
            if ticket["binding_released"] and not any(
                binding["state"] == "DELETE_PENDING" for binding in bindings
            ):
                continue
            await _provision_ticket(bot, platform_api, guild, ticket["id"], actor)
            reconciled += 1
        return {"reconciled_tickets": reconciled, "meta": result}
    raise RuntimeError(f"Job desconhecido: {key}")


async def deliver_proof_copy(bot: discord.Client, item: dict[str, Any]) -> str | None:
    api = FarmTicketsAPI(bot.platform_api)
    guild_id = int(item["guild_id"])
    ticket_id = str(item["payload"]["ticket_id"])
    proof_id = str(item["payload"]["proof_id"])
    proof = next(
        (
            entry
            for entry in await api.proofs(guild_id, ticket_id)
            if entry["id"] == proof_id
        ),
        None,
    )
    if proof is None or not proof.get("url"):
        raise RuntimeError("Comprovante ou URL pre-assinada indisponivel.")
    destination = bot.get_channel(int(item["destination_id"]))
    if destination is None:
        destination = await bot.fetch_channel(int(item["destination_id"]))
    if not isinstance(destination, discord.Thread):
        raise RuntimeError("Destino da copia nao e uma thread.")
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="yuno-proof-copy-", suffix=".image", delete=False
        ) as output:
            temp_path = Path(output.name)
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                async with client.stream("GET", proof["url"]) as response:
                    response.raise_for_status()
                    size = 0
                    async for chunk in response.aiter_bytes(64 * 1024):
                        size += len(chunk)
                        if size > 20 * 1024 * 1024:
                            raise RuntimeError(
                                "Comprovante excedeu 20 MiB durante a copia."
                            )
                        output.write(chunk)
        message = await destination.send(
            content=f"Comprovante `{proof['checksum_sha256']}`",
            file=discord.File(temp_path, filename=f"comprovante-{proof_id}.image"),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        actor = _system_actor(bot, guild_id, str(item["correlation_id"]))
        await api.proof_delivered(
            guild_id,
            ticket_id,
            proof_id,
            str(message.id),
            actor=actor.as_payload(),
        )
        return str(message.id)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


async def deliver_log(bot: discord.Client, item: dict[str, Any]) -> str | None:
    api = FarmTicketsAPI(bot.platform_api)
    guild_id = int(item["guild_id"])
    guild = bot.get_guild(guild_id)
    if guild is None:
        raise RuntimeError("Guild indisponivel para log de Tickets.")
    ticket = await api.ticket(guild_id, str(item["payload"]["ticket_id"]))
    channel = bot.get_channel(int(item["destination_id"]))
    if channel is None:
        channel = await bot.fetch_channel(int(item["destination_id"]))
    if not isinstance(channel, discord.TextChannel):
        raise RuntimeError("Canal de log de Tickets indisponivel.")
    actor = _system_actor(bot, guild_id, str(item["correlation_id"]))
    message, _ = await _sync_ticket_log(api, guild, channel, ticket, actor)
    return str(message.id)


async def deliver_event(bot: discord.Client, item: dict[str, Any]) -> str | None:
    destination = bot.get_channel(int(item["destination_id"]))
    if destination is None:
        destination = await bot.fetch_channel(int(item["destination_id"]))
    if not isinstance(destination, discord.Thread):
        raise RuntimeError("Destino de evento nao e uma thread de log.")
    payload = item.get("payload") or {}
    detail = json.dumps(
        payload.get("event_payload") or {}, ensure_ascii=False, sort_keys=True
    )
    if len(detail) > 1500:
        detail = detail[:1497] + "..."
    message = await destination.send(
        content=(
            f"`#{payload.get('sequence')}` **{payload.get('event_type')}**\n"
            f"Autor: `{payload.get('actor_id') or 'sistema'}`\n"
            f"```json\n{detail}\n```"
        ),
        allowed_mentions=discord.AllowedMentions.none(),
    )
    return str(message.id)


async def deliver_panel(bot: discord.Client, item: dict[str, Any]) -> str | None:
    guild = bot.get_guild(int(item["guild_id"]))
    if guild is None:
        raise RuntimeError("Guild indisponivel para painel de Tickets.")
    actor = _system_actor(bot, guild.id, str(item["correlation_id"]))
    if item["resource_type"] == "farm_ticket":
        result = await _provision_ticket(
            bot, bot.platform_api, guild, str(item["resource_id"]), actor
        )
        return result.get("channel_id")
    await _ensure_global_resources(
        bot, bot.platform_api, guild, actor, publish_panel=True
    )
    return str(item["destination_id"])


async def handle_message(
    bot: discord.Client, platform_api: Any, message: discord.Message
) -> None:
    if message.guild is None or message.author.bot or not message.attachments:
        return
    api = FarmTicketsAPI(platform_api)
    try:
        active = await api.channel_operation(message.guild.id, message.channel.id)
    except httpx.HTTPError:
        return
    if active is None:
        return
    attachment = next(
        (
            item
            for item in message.attachments
            if 0 < item.size <= 20 * 1024 * 1024
            and (
                (item.content_type or "").startswith("image/")
                or Path(item.filename).suffix.casefold()
                in {".jpg", ".jpeg", ".png", ".gif", ".webp"}
            )
        ),
        None,
    )
    if attachment is None:
        return
    member = message.author if isinstance(message.author, discord.Member) else None
    permissions = (
        message.channel.permissions_for(member)
        if member is not None
        else discord.Permissions.none()
    )
    actor = ActorContext(
        guild_id=message.guild.id,
        user_id=message.author.id,
        role_ids=tuple(role.id for role in member.roles) if member is not None else (),
        discord_permissions=tuple(name for name, enabled in permissions if enabled),
        channel_id=message.channel.id,
        category_id=getattr(message.channel, "category_id", None),
        actor_type="user",
        is_guild_owner=message.guild.owner_id == message.author.id,
        correlation_id=f"proof-message:{message.guild.id}:{message.id}",
    )
    try:
        await api.claim_proof(
            message.guild.id,
            active["ticket"]["id"],
            active["operation"]["id"],
            {
                "expected_version": active["ticket"]["revision"],
                "idempotency_key": f"message:{message.id}:attachment:{attachment.id}",
                "message_id": str(message.id),
                "attachment_id": str(attachment.id),
                "author_id": str(message.author.id),
                "channel_id": str(message.channel.id),
                "received_at": message.created_at.astimezone(timezone.utc).isoformat(),
                "filename": attachment.filename,
                "content_type": attachment.content_type,
                "size_bytes": attachment.size,
                "source_url": attachment.url,
            },
            actor=actor.as_payload(),
        )
        await message.add_reaction("⏳")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code not in {403, 404, 409, 422}:
            raise


async def handle_resource_delete(
    bot: discord.Client,
    platform_api: Any,
    guild_id: int,
    resource_id: int,
    resource_type: str | None,
) -> None:
    actor = _system_actor(bot, guild_id, f"discord-delete:{guild_id}:{resource_id}")
    await FarmTicketsAPI(platform_api).resource_deleted(
        guild_id,
        resource_id,
        datetime.now(timezone.utc).isoformat(),
        resource_type,
        actor=actor.as_payload(),
    )


async def startup(bot: discord.Client, platform_api: Any, guild: discord.Guild) -> None:
    actor = _system_actor(bot, guild.id, f"startup:farm-tickets:{guild.id}")
    await run_job(
        bot,
        platform_api,
        {
            "id": f"startup:{guild.id}",
            "guild_id": str(guild.id),
            "key": "farm_tickets.reconcile",
            "resource_id": str(guild.id),
            "correlation_id": actor.correlation_id,
            "payload": {"reason": "startup"},
        },
    )
