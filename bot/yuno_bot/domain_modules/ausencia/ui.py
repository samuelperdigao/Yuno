from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import discord
import httpx

from yuno_bot import dashboard
from yuno_bot.domain_modules.ausencia.renderers import AusenciaLogData, AusenciaRenderer
from yuno_bot.platform.components_v2 import (
    action_row,
    button,
    channel_select,
    edit_message,
    payload,
)
from yuno_bot.platform.contracts import (
    ActorContext,
    ComponentsV2Payload,
    InteractionResult,
    RoutedContext,
)
from yuno_bot.platform import ui_kit as uk
from yuno_bot.platform.panels import PanelPublisher
from yuno_bot.platform.router import RoutedModal, custom_id

COLOR = uk.BRAND


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
        return "⚪ Não configurado"
    return f"<#{text}>" if kind == "channel" else f"<@&{text}>"


async def render_public(context: dict) -> ComponentsV2Payload:
    config = context.get("config")
    if config is None:
        config = (await context["api"].ausencia_config(context["guild"].id))["data"]
    return ComponentsV2Payload(
        payload(
            uk.panel(
                header=uk.heading(config["panel_title"], emoji="🏖️") + "\n\n" + config["panel_description"],
                actions=[
                    action_row(
                        button(
                            custom_id=custom_id("ausencia", "public", "open_form"),
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


class AusenciaModal(RoutedModal):
    def __init__(self, panel: dict) -> None:
        super().__init__(
            title="Registrar Ausência",
            module_key="ausencia",
            surface="public",
            action_key="submit",
            panel=panel,
        )
        self.add_item(
            discord.ui.TextInput(
                label="Quantos dias você vai ficar ausente?",
                custom_id="ausencia_dias",
                min_length=1,
                max_length=3,
            )
        )
        self.add_item(
            discord.ui.TextInput(
                label="Motivo (opcional)",
                custom_id="ausencia_motivo",
                style=discord.TextStyle.paragraph,
                required=False,
                max_length=300,
            )
        )


async def open_form(context: RoutedContext) -> InteractionResult:
    return InteractionResult(modal=AusenciaModal(context.panel))


async def submit(context: RoutedContext) -> InteractionResult:
    values = _modal_values(context.interaction)
    raw_dias = values.get("ausencia_dias", "").strip()
    try:
        dias = int(raw_dias)
    except ValueError:
        return InteractionResult(content="Informe a quantidade de dias usando apenas números.")
    motivo = values.get("ausencia_motivo", "").strip() or None
    member = context.interaction.user
    display_name = str(getattr(member, "display_name", None) or getattr(member, "name", "Membro"))[:120]
    try:
        result = await context.api.ausencia_register(
            context.actor.guild_id,
            {"dias": dias, "motivo": motivo},
            member_display_name=display_name,
            actor=context.actor,
        )
        return InteractionResult(content=result["config"]["confirmation_message"])
    except Exception as exc:
        return InteractionResult(content=error_text(exc))


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
    if not interaction.response.is_done():
        await interaction.response.defer()
    target_channel = channel_id or interaction.channel_id
    target_message = message_id or getattr(interaction.message, "id", None)
    if target_channel is None or target_message is None:
        raise RuntimeError("Referência da Central indisponível.")
    await edit_message(interaction.client, target_channel, target_message, data)


async def _admin_state(api: Any, guild_id: int) -> tuple[dict, dict]:
    return (
        await api.module_instance(guild_id, "ausencia"),
        await api.configuration_draft(guild_id, "ausencia"),
    )


def build_admin_payload(instance: dict, draft: dict) -> dict[str, Any]:
    published = int(draft["base_published_version"] or 0)
    config = draft["data"]
    is_active = published > 0 and instance["lifecycle"] == "active"
    if is_active:
        status = f"🟢 **Ativo** · versão `{published}`"
    elif published:
        status = f"🟠 **Desativado** · versão `{published}`"
    else:
        status = "⚪ **Ainda não publicado**"
    return payload(
        uk.panel(
            header=[dashboard.module_navigation("ausencia"), uk.heading("Ausência", emoji="🏖️")],
            blocks=[
                f"### Status\n{status}",
                (
                    "### Configuração\n"
                    f"**Painel** — {_discord_ref(config.get('panel_channel_id'), kind='channel')}\n"
                    f"**Logs** — {_discord_ref(config.get('log_channel_id'), kind='channel')}\n"
                    f"**Máximo de dias** — `{config.get('max_dias')}`"
                ),
            ],
            actions=[
                action_row(
                    channel_select(
                        custom_id=dashboard.central_custom_id("ausencia", "set_panel_channel"),
                        placeholder="Publicar o painel de ausência em…",
                        channel_types=[0],
                    )
                ),
                action_row(
                    channel_select(
                        custom_id=dashboard.central_custom_id("ausencia", "set_log_channel"),
                        placeholder="Enviar logs de ausência em…",
                        channel_types=[0],
                    )
                ),
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id("ausencia", "edit_max_dias"),
                        label="Editar máximo de dias",
                        emoji="✏️",
                        style=2,
                    ),
                    button(
                        custom_id=dashboard.central_custom_id("ausencia", "view_active"),
                        label="Ver ausências ativas",
                        emoji="📋",
                        style=2,
                    ),
                ),
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id("ausencia", "review_publish"),
                        label="Revisar e publicar",
                        emoji="👁️",
                        style=1,
                    )
                ),
            ],
            accent_color=COLOR,
        )
    )


async def render_admin(interaction: discord.Interaction, api: Any) -> None:
    try:
        instance, draft = await _admin_state(api, interaction.guild_id)
        await _replace_central(interaction, build_admin_payload(instance, draft))
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))


async def open_system(interaction: discord.Interaction, api: Any) -> None:
    await render_admin(interaction, api)


async def _save_patch(interaction: discord.Interaction, api: Any, patch: dict[str, Any]) -> dict:
    draft = await api.configuration_draft(interaction.guild_id, "ausencia")
    actor = actor_from(interaction)
    return await api.save_configuration_draft(
        interaction.guild_id,
        "ausencia",
        {
            "expected_revision": draft["revision"],
            "expected_published_version": draft["base_published_version"],
            "schema_version": draft["schema_version"],
            "data": {**draft["data"], **patch},
        },
        actor=actor,
    )


async def _set_selected(interaction: discord.Interaction, api: Any, field: str) -> None:
    values = _selected_ids(interaction)
    if not values:
        await _send_interaction_error(interaction, "Selecione um canal.")
        return
    await _defer_if_needed(interaction)
    await _save_patch(interaction, api, {field: values[0]})
    await render_admin(interaction, api)


async def set_panel_channel(interaction, api):
    await _set_selected(interaction, api, "panel_channel_id")


async def set_log_channel(interaction, api):
    await _set_selected(interaction, api, "log_channel_id")


class MaxDiasModal(discord.ui.Modal):
    def __init__(self, api: Any, current: int, channel_id: int, message_id: int) -> None:
        super().__init__(title="Ausência · Máximo de dias")
        self.api = api
        self.central_channel_id = channel_id
        self.central_message_id = message_id
        self.add_item(
            discord.ui.TextInput(
                label="Máximo de dias permitido",
                custom_id="max_dias",
                default=str(current),
                min_length=1,
                max_length=2,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        values = _modal_values(interaction)
        try:
            max_dias = int(values.get("max_dias", ""))
        except ValueError:
            await interaction.response.send_message(
                "Informe um número inteiro para o máximo de dias.", ephemeral=True
            )
            return
        if not 1 <= max_dias <= 30:
            await interaction.response.send_message(
                "O máximo de dias deve estar entre 1 e 30.", ephemeral=True
            )
            return
        try:
            await interaction.response.defer()
            await _save_patch(interaction, self.api, {"max_dias": max_dias})
            await _replace_central(
                interaction,
                build_admin_payload(*await _admin_state(self.api, interaction.guild_id)),
                channel_id=self.central_channel_id,
                message_id=self.central_message_id,
            )
        except Exception as exc:
            await _send_interaction_error(interaction, error_text(exc))


async def edit_max_dias(interaction: discord.Interaction, api: Any) -> None:
    _, draft = await _admin_state(api, interaction.guild_id)
    await interaction.response.send_modal(
        MaxDiasModal(
            api,
            int(draft["data"].get("max_dias", 7)),
            interaction.channel_id,
            interaction.message.id,
        )
    )


async def view_active(interaction: discord.Interaction, api: Any) -> None:
    try:
        await _defer_if_needed(interaction)
        records = await api.ausencia_records(interaction.guild_id)
        if records:
            lines = [
                uk.field(
                    f"<@{item['discord_user_id']}>",
                    f"{item['days']} dia(s) · retorno "
                    + discord.utils.format_dt(
                        datetime.fromisoformat(item["ends_at"]), style="R"
                    ),
                    emoji="🏖️",
                )
                for item in records
            ]
            body = "\n\n".join(lines)
        else:
            body = uk.empty_state("Nenhuma ausência ativa no momento.")
        await _replace_central(
            interaction,
            payload(
                uk.panel(
                    header=[dashboard.module_navigation("ausencia"), uk.heading("Ausência", emoji="🏖️")],
                    blocks=[f"### Ausências ativas ({len(records)})", body],
                    actions=[
                        action_row(
                            button(
                                custom_id=dashboard.central_custom_id("ausencia", "open_system"),
                                label="Voltar",
                                emoji="↩️",
                                style=2,
                            )
                        )
                    ],
                    accent_color=COLOR,
                )
            ),
        )
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))


async def _preflight(guild: discord.Guild, config: dict) -> list[str]:
    errors: list[str] = []
    bot_member = guild.me
    if not config.get("panel_channel_id"):
        errors.append("Campo obrigatório ausente: panel_channel_id.")
    for key in ("panel_channel_id", "log_channel_id"):
        value = config.get(key)
        if not value:
            continue
        channel = guild.get_channel(int(value))
        if not isinstance(channel, discord.TextChannel):
            errors.append(f"{key} não aponta para canal de texto.")
            continue
        if bot_member:
            perms = channel.permissions_for(bot_member)
            if not perms.view_channel or not perms.send_messages:
                errors.append(f"Bot sem acesso de envio em {channel.mention}.")
    return errors


async def review_publish(interaction: discord.Interaction, api: Any) -> None:
    await _defer_if_needed(interaction)
    _, draft = await _admin_state(api, interaction.guild_id)
    errors = await _preflight(interaction.guild, draft["data"])
    if errors:
        await _send_interaction_error(interaction, "Publicação bloqueada:\n- " + "\n- ".join(errors))
        return
    config = draft["data"]
    await _replace_central(
        interaction,
        payload(
            uk.panel(
                header=[dashboard.module_navigation("ausencia"), uk.heading("Ausência", emoji="🏖️")],
                blocks=[
                    "# 👁️ Revisar publicação da Ausência\n\n"
                    f"Painel: <#{config['panel_channel_id']}>\n"
                    f"Logs: {_discord_ref(config.get('log_channel_id'), kind='channel')}\n"
                    f"Máximo de dias: `{config['max_dias']}`\n\n"
                    "A confirmação cria uma versão imutável e reconcilia o painel público."
                ],
                actions=[
                    action_row(
                        button(
                            custom_id=dashboard.central_custom_id("ausencia", "confirm_publish"),
                            label="Confirmar publicação",
                            emoji="✅",
                            style=3,
                        ),
                        button(
                            custom_id=dashboard.central_custom_id("ausencia", "open_system"),
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


async def confirm_publish(interaction: discord.Interaction, api: Any) -> None:
    await _defer_if_needed(interaction)
    actor = actor_from(interaction)
    _, draft = await _admin_state(api, interaction.guild_id)
    errors = await _preflight(interaction.guild, draft["data"])
    if errors:
        await _send_interaction_error(interaction, "Publicação bloqueada:\n- " + "\n- ".join(errors))
        return
    grants = [
        {
            "capability": "ausencia.register",
            "subject_type": "everyone",
            "subject_id": "",
            "scope_type": "guild",
            "scope_id": "",
            "constraints": {},
        }
    ]
    try:
        version = await api.publish_configuration(
            interaction.guild_id,
            "ausencia",
            {
                "expected_revision": draft["revision"],
                "expected_published_version": draft["base_published_version"],
                "grants": grants,
            },
            actor=actor,
        )
        instance = await api.module_instance(interaction.guild_id, "ausencia")
        try:
            await PanelPublisher(interaction.client, api).reconcile(
                guild=interaction.guild,
                module_key="ausencia",
                panel_key="public",
                channel_id=int(draft["data"]["panel_channel_id"]),
                actor=actor,
                render_context={"config": draft["data"], "config_version": version["version"]},
            )
        except Exception:
            await api.schedule_task(
                interaction.guild_id,
                "ausencia",
                {
                    "job_key": "ausencia.panel.reconcile",
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
        if instance["lifecycle"] != "active":
            await api.update_lifecycle(
                interaction.guild_id,
                "ausencia",
                lifecycle="active",
                expected_lifecycle=instance["lifecycle"],
                actor=actor,
                reason=None,
            )
        await render_admin(interaction, api)
        await interaction.followup.send(
            f"Ausência publicada na versão {version['version']}.", ephemeral=True
        )
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))


async def deliver_channel_embed(bot: discord.Client, item: dict) -> str | None:
    channel = bot.get_channel(int(item["destination_id"]))
    if channel is None:
        channel = await bot.fetch_channel(int(item["destination_id"]))
    data = item.get("payload") or {}
    resolved = AusenciaLogData.from_payload(data)
    embed = AusenciaRenderer().render_registered(resolved)
    message = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    return str(message.id)


async def deliver_overdue_reminder(bot: discord.Client, item: dict) -> str | None:
    user = bot.get_user(int(item["destination_id"])) or await bot.fetch_user(
        int(item["destination_id"])
    )
    data = item.get("payload") or {}
    config_ref = await bot.platform_api.ausencia_config(int(item["guild_id"]))
    config = config_ref["data"]
    resolved = AusenciaLogData.from_payload(
        {
            **data,
            "reminder_title": config.get("overdue_reminder_title"),
            "reminder_message": config.get("overdue_reminder_message"),
        }
    )
    embed = AusenciaRenderer().render_overdue_reminder(resolved)
    message = await user.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    return str(message.id)


async def run_job(bot: discord.Client, api: Any, item: dict) -> dict:
    guild = bot.get_guild(int(item["guild_id"]))
    if guild is None:
        raise RuntimeError("Guild indisponível para recuperação.")
    actor = system_actor(bot, guild.id, item["correlation_id"])
    if item["key"] != "ausencia.panel.reconcile":
        return {"changed": False, "reason": "job desconhecido"}
    config_ref = await api.ausencia_config(guild.id)
    config = config_ref["data"]
    await PanelPublisher(bot, api).reconcile(
        guild=guild,
        module_key="ausencia",
        panel_key="public",
        channel_id=int(config["panel_channel_id"]),
        actor=actor,
        render_context={"config": config, "config_version": config_ref["version"]},
    )
    instance = await api.module_instance(guild.id, "ausencia")
    activated = False
    if instance["lifecycle"] != "active":
        await api.update_lifecycle(
            guild.id,
            "ausencia",
            lifecycle="active",
            expected_lifecycle=instance["lifecycle"],
            actor=actor,
            reason="Painel público recuperado após publicação.",
        )
        activated = True
    return {"changed": True, "panel_key": "public", "activated": activated}
