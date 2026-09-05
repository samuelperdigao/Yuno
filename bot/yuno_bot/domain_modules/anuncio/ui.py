from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import discord
import httpx

from yuno_bot import dashboard
from yuno_bot.domain_modules.anuncio.domain import AnuncioUIError, parse_yes_no
from yuno_bot.domain_modules.anuncio.embeds import (
    AnuncioLogData,
    build_announcement_embed,
    build_log_embed,
)
from yuno_bot.platform import ui_kit as uk
from yuno_bot.platform.components_v2 import (
    action_row,
    button,
    channel_select,
    edit_message,
    payload,
    role_select,
)
from yuno_bot.platform.contracts import (
    ActorContext,
    ComponentsV2Payload,
    InteractionResult,
    RoutedContext,
)
from yuno_bot.platform.panels import PanelPublisher
from yuno_bot.platform.router import RoutedModal, custom_id

MODULE_KEY = "anuncio"
COLOR = uk.BRAND
TEXT_CHANNEL_TYPE = 0
MAX_AUTHORIZED_ROLES = 25

EMPTY_CONFIG: dict[str, Any] = {
    "channel_id": "",
    "log_channel_id": "",
    "authorized_role_ids": [],
}

UNDEFINED = "⚪ Ainda não definido"


def actor_from(interaction: discord.Interaction) -> ActorContext:
    member = interaction.user if isinstance(interaction.user, discord.Member) else None
    permissions = tuple(name for name, enabled in member.guild_permissions if enabled) if member else ()
    role_ids = tuple(role.id for role in member.roles) if member else ()
    return ActorContext(
        guild_id=interaction.guild_id or 0,
        user_id=interaction.user.id if interaction.user else None,
        role_ids=role_ids,
        discord_permissions=permissions,
        channel_id=interaction.channel_id,
        category_id=getattr(interaction.channel, "category_id", None),
        actor_type="user",
        is_guild_owner=bool(
            interaction.guild
            and interaction.user
            and interaction.guild.owner_id == interaction.user.id
        ),
        correlation_id=str(interaction.id),
    )


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


def error_text(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            detail = exc.response.json().get("detail", "Operação recusada.")
            if isinstance(detail, dict):
                return str(detail.get("message") or detail.get("detail") or detail)
            return str(detail)
        except Exception:
            return f"A API recusou a operação ({exc.response.status_code})."
    if isinstance(exc, (RuntimeError, ValueError)):
        return str(exc)
    return "Não consegui concluir a operação."


def _modal_values(interaction: discord.Interaction) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in (interaction.data or {}).get("components") or []:
        for component in row.get("components") or []:
            if component.get("custom_id"):
                result[str(component["custom_id"])] = str(component.get("value") or "")
    return result


def _selected_ids(interaction: discord.Interaction) -> list[str]:
    return [str(value) for value in (interaction.data or {}).get("values") or []]


def _discord_ref(value: Any, *, kind: str) -> str:
    text = str(value or "").strip()
    if not (text.isascii() and text.isdigit()):
        return UNDEFINED
    return f"<#{text}>" if kind == "channel" else f"<@&{text}>"


def _roles_ref(config: dict[str, Any]) -> str:
    roles = list(config.get("authorized_role_ids") or [])
    return ", ".join(f"<@&{role_id}>" for role_id in roles) if roles else "Nenhum além de quem gerencia o servidor."


# --- Painel público -------------------------------------------------------


async def render_public(context: dict) -> ComponentsV2Payload:
    config = context.get("config")
    if config is None:
        config = (await context["api"].anuncio_config(context["guild"].id))["data"]
    return ComponentsV2Payload(
        payload(
            uk.panel(
                header=uk.heading(config["panel_title"], emoji="📢") + "\n\n" + config["panel_description"],
                actions=[
                    action_row(
                        button(
                            custom_id=custom_id(MODULE_KEY, "public", "open_form"),
                            label=config["button_label"],
                            emoji=config.get("button_emoji") or None,
                            style=1,
                        )
                    )
                ],
                footer=config.get("panel_footer") or "Yuno",
                accent_color=COLOR,
            )
        )
    )


class AnuncioModal(RoutedModal):
    def __init__(self, panel: dict) -> None:
        super().__init__(
            title="Novo Anúncio",
            module_key=MODULE_KEY,
            surface="public",
            action_key="submit",
            panel=panel,
        )
        self.add_item(
            discord.ui.TextInput(
                label="Título",
                custom_id="anuncio_titulo",
                max_length=256,
            )
        )
        self.add_item(
            discord.ui.TextInput(
                label="Conteúdo",
                custom_id="anuncio_conteudo",
                style=discord.TextStyle.paragraph,
                max_length=4000,
            )
        )
        self.add_item(
            discord.ui.TextInput(
                label="Mencionar @everyone? (sim/não)",
                custom_id="anuncio_mencionar_everyone",
                max_length=5,
                default="não",
            )
        )
        self.add_item(
            discord.ui.TextInput(
                label="Adicionar arquivo? (sim/não)",
                custom_id="anuncio_anexar_arquivo",
                max_length=5,
                default="não",
            )
        )


async def open_form(context: RoutedContext) -> InteractionResult:
    return InteractionResult(modal=AnuncioModal(context.panel))


async def submit(context: RoutedContext) -> InteractionResult:
    interaction = context.interaction
    values = _modal_values(interaction)
    titulo = values.get("anuncio_titulo", "").strip()
    conteudo = values.get("anuncio_conteudo", "").strip()
    try:
        mencionar_everyone = parse_yes_no(values.get("anuncio_mencionar_everyone", ""))
        anexar_arquivo = parse_yes_no(values.get("anuncio_anexar_arquivo", ""))
    except AnuncioUIError as exc:
        return InteractionResult(content=str(exc))

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True, thinking=True)

    attachment_file: discord.File | None = None
    is_image = False
    warning: str | None = None
    if anexar_arquivo:
        await interaction.followup.send(
            "📎 Envie o arquivo agora, como mensagem neste canal, em até 60 segundos.",
            ephemeral=True,
        )

        def _is_upload(message: discord.Message) -> bool:
            return (
                message.channel.id == interaction.channel_id
                and message.author.id == interaction.user.id
                and bool(message.attachments)
            )

        try:
            upload_message = await interaction.client.wait_for(
                "message", check=_is_upload, timeout=60
            )
        except asyncio.TimeoutError:
            warning = "⏱️ Tempo esgotado — publiquei o anúncio sem o arquivo."
        else:
            attachment = upload_message.attachments[0]
            attachment_file = await attachment.to_file()
            is_image = bool(attachment.content_type and attachment.content_type.startswith("image/"))
            try:
                await upload_message.delete()
            except discord.HTTPException:
                pass

    try:
        result = await context.api.anuncio_publish(
            context.actor.guild_id,
            {
                "titulo": titulo,
                "conteudo": conteudo,
                "mencionar_everyone": mencionar_everyone,
                "anexou_arquivo": attachment_file is not None,
            },
            actor=context.actor,
        )
    except Exception as exc:
        return InteractionResult(content=error_text(exc))

    config = result["config"]
    guild = interaction.guild
    assert guild is not None
    channel = guild.get_channel(int(config["channel_id"]))
    if channel is None:
        channel = await guild.fetch_channel(int(config["channel_id"]))

    embed = build_announcement_embed(titulo=titulo, conteudo=conteudo)
    if attachment_file is not None and is_image:
        embed.set_image(url=f"attachment://{attachment_file.filename}")

    send_kwargs: dict[str, Any] = {"embed": embed}
    if mencionar_everyone:
        send_kwargs["content"] = "@everyone"
        send_kwargs["allowed_mentions"] = discord.AllowedMentions(everyone=True, roles=False, users=False)
    else:
        send_kwargs["allowed_mentions"] = discord.AllowedMentions.none()
    if attachment_file is not None:
        send_kwargs["files"] = [attachment_file]
    await channel.send(**send_kwargs)

    log_channel_id = config.get("log_channel_id")
    if log_channel_id:
        log_channel = guild.get_channel(int(log_channel_id))
        if log_channel is None:
            log_channel = await guild.fetch_channel(int(log_channel_id))
        log_embed = build_log_embed(
            AnuncioLogData(
                autor_id=str(interaction.user.id),
                titulo=titulo,
                canal_id=str(channel.id),
                mencionou_everyone=mencionar_everyone,
                quantidade_arquivos=1 if attachment_file is not None else 0,
                log_title=config.get("log_title") or "Novo anúncio publicado",
            )
        )
        await log_channel.send(embed=log_embed, allowed_mentions=discord.AllowedMentions.none())

    return InteractionResult(content=warning or "📢 Anúncio publicado com sucesso.")


# --- Central administrativa ------------------------------------------------


async def _defer_if_needed(interaction: discord.Interaction) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer()


async def _send_interaction_error(interaction: discord.Interaction, message: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


async def _replace_central(
    interaction: discord.Interaction,
    data: dict[str, Any],
    *,
    channel_id: int | None = None,
    message_id: int | None = None,
) -> None:
    await _defer_if_needed(interaction)
    target_channel = channel_id or interaction.channel_id
    target_message = message_id or getattr(interaction.message, "id", None)
    if target_channel is None or target_message is None:
        raise RuntimeError("Referência da Central indisponível.")
    await edit_message(interaction.client, target_channel, target_message, data)


async def _admin_state(api: Any, guild_id: int) -> tuple[dict, dict]:
    return (
        await api.module_instance(guild_id, MODULE_KEY),
        await api.configuration_draft(guild_id, MODULE_KEY),
    )


def _merge(draft: dict, patch: dict[str, Any] | None = None) -> dict[str, Any]:
    return {**EMPTY_CONFIG, **(draft.get("data") or {}), **(patch or {})}


def build_admin_payload(instance: dict, config: dict[str, Any]) -> dict[str, Any]:
    published = instance.get("published_config_version_id") is not None
    is_active = published and instance.get("lifecycle") == "active"
    if is_active:
        state = uk.State.APPROVED
        status = uk.badge(state, "Ativo", bold=True)
        status_detail = "O painel de anúncios está publicado e pronto para uso."
    elif published:
        state = uk.State.RUNNING
        status = uk.badge(state, "Publicado, porém inativo", bold=True)
        status_detail = "A configuração existe, mas o módulo não está atendendo."
    else:
        state = uk.State.PENDING
        status = uk.badge(state, "Ainda não publicado", bold=True)
        status_detail = "Enquanto não houver publicação, o painel de anúncios não existe."
    return payload(
        uk.panel(
            header=[
                dashboard.module_navigation(MODULE_KEY),
                uk.heading("Sistema de Anúncio", emoji="📢"),
            ],
            blocks=[
                uk.field("Status", f"{status}\n{status_detail}", emoji="📌"),
                uk.rule(),
                uk.field(
                    "Configuração",
                    (
                        f"**📢 Canal de anúncios** — {_discord_ref(config.get('channel_id'), kind='channel')}\n"
                        f"**🧾 Canal de log** — {_discord_ref(config.get('log_channel_id'), kind='channel')}\n"
                        f"**🎭 Cargos autorizados a anunciar** — {_roles_ref(config)}"
                    ),
                    emoji="🧭",
                ),
            ],
            actions=[
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id(MODULE_KEY, "open_system"),
                        label="Configurar Anúncio",
                        emoji="⚙️",
                        style=2,
                    )
                )
            ],
            state=state,
        )
    )


async def render_admin(interaction: discord.Interaction, api: Any) -> None:
    try:
        instance, draft = await _admin_state(api, interaction.guild_id)
        config = _merge(draft)
        await _replace_central(interaction, build_admin_payload(instance, config))
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))


def build_system_payload(config: dict[str, Any]) -> dict[str, Any]:
    return payload(
        uk.panel(
            header=[
                dashboard.module_navigation(MODULE_KEY),
                uk.heading("Sistema de Anúncio", emoji="📢")
                + "\n\nEscolha onde os anúncios são publicados, para onde vai o log e "
                "quais cargos podem usar o painel. Nada muda no Discord antes da publicação.",
            ],
            blocks=[
                uk.field(
                    "1 · Canal de anúncios",
                    _discord_ref(config.get("channel_id"), kind="channel"),
                    emoji="📍",
                ),
                uk.field(
                    "2 · Canal de log",
                    _discord_ref(config.get("log_channel_id"), kind="channel"),
                    emoji="🧾",
                ),
                uk.field("3 · Cargos autorizados a anunciar", _roles_ref(config), emoji="🎭"),
            ],
            actions=[
                action_row(
                    channel_select(
                        custom_id=dashboard.central_custom_id(MODULE_KEY, "set_channel"),
                        placeholder="Publicar anúncios em…",
                        channel_types=[TEXT_CHANNEL_TYPE],
                    )
                ),
                action_row(
                    channel_select(
                        custom_id=dashboard.central_custom_id(MODULE_KEY, "set_log_channel"),
                        placeholder="Enviar log de publicações em…",
                        channel_types=[TEXT_CHANNEL_TYPE],
                    )
                ),
                action_row(
                    role_select(
                        custom_id=dashboard.central_custom_id(MODULE_KEY, "set_authorized_roles"),
                        placeholder="Cargos autorizados a publicar anúncios (opcional)",
                        min_values=0,
                        max_values=MAX_AUTHORIZED_ROLES,
                    )
                ),
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id(MODULE_KEY, "review_publish"),
                        label="Revisar e publicar",
                        emoji="👁️",
                        style=1,
                    ),
                    button(
                        custom_id=dashboard.central_custom_id(MODULE_KEY, "overview"),
                        label="Voltar",
                        emoji="↩️",
                        style=2,
                    ),
                ),
            ],
            accent_color=COLOR,
        )
    )


async def open_system(interaction: discord.Interaction, api: Any) -> None:
    try:
        _, draft = await _admin_state(api, interaction.guild_id)
        await _replace_central(interaction, build_system_payload(_merge(draft)))
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))


async def overview(interaction: discord.Interaction, api: Any) -> None:
    await render_admin(interaction, api)


async def _apply_patch(interaction: discord.Interaction, api: Any, patch: dict[str, Any]) -> None:
    await _defer_if_needed(interaction)
    draft = await api.configuration_draft(interaction.guild_id, MODULE_KEY)
    config = _merge(draft, patch)
    await api.save_configuration_draft(
        interaction.guild_id,
        MODULE_KEY,
        {
            "expected_revision": draft["revision"],
            "expected_published_version": draft["base_published_version"],
            "schema_version": draft["schema_version"],
            "data": dict(config),
        },
        actor=actor_from(interaction),
    )
    await _replace_central(interaction, build_system_payload(config))


async def set_channel(interaction: discord.Interaction, api: Any) -> None:
    values = _selected_ids(interaction)
    if not values:
        await _send_interaction_error(interaction, "Selecione um canal.")
        return
    try:
        await _apply_patch(interaction, api, {"channel_id": values[0]})
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))


async def set_log_channel(interaction: discord.Interaction, api: Any) -> None:
    values = _selected_ids(interaction)
    if not values:
        await _send_interaction_error(interaction, "Selecione um canal.")
        return
    try:
        await _apply_patch(interaction, api, {"log_channel_id": values[0]})
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))


async def set_authorized_roles(interaction: discord.Interaction, api: Any) -> None:
    values = _selected_ids(interaction)
    try:
        await _apply_patch(interaction, api, {"authorized_role_ids": list(dict.fromkeys(values))})
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))


def preflight(guild: discord.Guild, config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key, label in (("channel_id", "Canal de anúncios"), ("log_channel_id", "Canal de log")):
        if not config.get(key):
            errors.append(f"Campo obrigatório ausente: {label}.")
    bot_member = guild.me
    for key, label in (("channel_id", "Canal de anúncios"), ("log_channel_id", "Canal de log")):
        value = config.get(key)
        if not value:
            continue
        channel = guild.get_channel(int(value))
        if not isinstance(channel, discord.TextChannel):
            errors.append(f"{label} não aponta para um canal de texto.")
            continue
        if bot_member is None:
            continue
        permissions = channel.permissions_for(bot_member)
        if not permissions.view_channel or not permissions.send_messages:
            errors.append(f"Bot sem acesso de envio em {channel.mention}.")
    if config.get("channel_id") and config["channel_id"] == config.get("log_channel_id"):
        errors.append("O canal de anúncios e o de log precisam ser diferentes.")
    for role_id in config.get("authorized_role_ids") or []:
        role = guild.get_role(int(role_id))
        if role is None:
            errors.append(f"Cargo autorizado inexistente: {role_id}.")
        elif role.is_default():
            errors.append("@everyone não pode ser um cargo autorizado a anunciar.")
    return errors


async def review_publish(interaction: discord.Interaction, api: Any) -> None:
    try:
        await _defer_if_needed(interaction)
        _, draft = await _admin_state(api, interaction.guild_id)
        config = _merge(draft)
        errors = preflight(interaction.guild, config)
        if errors:
            await _send_interaction_error(interaction, "Publicação bloqueada:\n- " + "\n- ".join(errors))
            return
        await _replace_central(
            interaction,
            payload(
                uk.panel(
                    header=[
                        dashboard.module_navigation(MODULE_KEY),
                        uk.heading("Revisar publicação do Anúncio", emoji="👁️"),
                    ],
                    blocks=[
                        f"Anúncios: <#{config['channel_id']}>\n"
                        f"Log: <#{config['log_channel_id']}>\n"
                        f"Cargos autorizados: {_roles_ref(config)}\n\n"
                        "A confirmação cria uma versão imutável e reconcilia o painel público."
                    ],
                    actions=[
                        action_row(
                            button(
                                custom_id=dashboard.central_custom_id(MODULE_KEY, "confirm_publish"),
                                label="Confirmar publicação",
                                emoji="✅",
                                style=3,
                            ),
                            button(
                                custom_id=dashboard.central_custom_id(MODULE_KEY, "open_system"),
                                label="Voltar",
                                emoji="↩️",
                                style=2,
                            ),
                        )
                    ],
                    accent_color=COLOR,
                )
            ),
        )
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))


def _grants_from(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "capability": "anuncio.publish",
            "subject_type": "role",
            "subject_id": role_id,
            "scope_type": "guild",
            "scope_id": "",
            "constraints": {},
        }
        for role_id in dict.fromkeys(config.get("authorized_role_ids") or [])
    ]


async def confirm_publish(interaction: discord.Interaction, api: Any) -> None:
    try:
        await _defer_if_needed(interaction)
        actor = actor_from(interaction)
        instance, draft = await _admin_state(api, interaction.guild_id)
        config = _merge(draft)
        errors = preflight(interaction.guild, config)
        if errors:
            await _send_interaction_error(interaction, "Publicação bloqueada:\n- " + "\n- ".join(errors))
            return
        version = await api.publish_configuration(
            interaction.guild_id,
            MODULE_KEY,
            {
                "expected_revision": draft["revision"],
                "expected_published_version": draft["base_published_version"],
                "grants": _grants_from(config),
            },
            actor=actor,
        )
        try:
            await PanelPublisher(interaction.client, api).reconcile(
                guild=interaction.guild,
                module_key=MODULE_KEY,
                panel_key="public",
                channel_id=int(config["channel_id"]),
                actor=actor,
                render_context={"config": config, "config_version": version["version"]},
            )
        except Exception:
            await api.schedule_task(
                interaction.guild_id,
                MODULE_KEY,
                {
                    "job_key": "anuncio.panel.reconcile",
                    "resource_type": "panel",
                    "resource_id": "public",
                    "payload": {"panel_key": "public"},
                    "due_at": datetime.now(timezone.utc).isoformat(),
                    "idempotency_key": f"public:{version['version']}",
                    "correlation_id": actor.correlation_id,
                    "max_attempts": 5,
                },
            )
            await interaction.followup.send(
                content="Versão publicada, mas o painel visual ficou na versão anterior. "
                "A reconciliação foi enfileirada.",
                ephemeral=True,
            )
            return
        if instance.get("lifecycle") != "active":
            await api.update_lifecycle(
                interaction.guild_id,
                MODULE_KEY,
                lifecycle="active",
                expected_lifecycle=instance["lifecycle"],
                actor=actor,
                reason=None,
            )
        await render_admin(interaction, api)
        await interaction.followup.send(
            f"Anúncio publicado na versão {version['version']}.", ephemeral=True
        )
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))


async def run_job(bot: discord.Client, api: Any, item: dict) -> dict:
    guild = bot.get_guild(int(item["guild_id"]))
    if guild is None:
        raise RuntimeError("Guild indisponível para recuperação.")
    actor = system_actor(bot, guild.id, item["correlation_id"])
    if item["key"] != "anuncio.panel.reconcile":
        return {"changed": False, "reason": "job desconhecido"}
    config_ref = await api.anuncio_config(guild.id)
    config = config_ref["data"]
    await PanelPublisher(bot, api).reconcile(
        guild=guild,
        module_key=MODULE_KEY,
        panel_key="public",
        channel_id=int(config["channel_id"]),
        actor=actor,
        render_context={"config": config, "config_version": config_ref["version"]},
    )
    instance = await api.module_instance(guild.id, MODULE_KEY)
    activated = False
    if instance["lifecycle"] != "active":
        await api.update_lifecycle(
            guild.id,
            MODULE_KEY,
            lifecycle="active",
            expected_lifecycle=instance["lifecycle"],
            actor=actor,
            reason="Painel público recuperado após publicação.",
        )
        activated = True
    return {"changed": True, "panel_key": "public", "activated": activated}
