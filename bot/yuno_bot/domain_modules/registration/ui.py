from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import discord
import httpx

from yuno_bot import dashboard
from yuno_bot.platform.components_v2 import (
    action_row,
    button,
    channel_select,
    container,
    edit_message,
    media,
    payload,
    role_select,
    separator,
    string_select,
    text_display,
)
from yuno_bot.platform.contracts import (
    ActorContext,
    ComponentsV2Payload,
    InteractionResult,
    RoutedContext,
)
from yuno_bot.platform.panels import PanelPublisher
from yuno_bot.platform.router import RoutedModal, custom_id


COLOR = 0xFFC72C
PROTECTED_ROLE_PERMISSIONS = (
    "administrator",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "kick_members",
    "ban_members",
    "moderate_members",
    "manage_webhooks",
)


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


def error_text(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            detail = exc.response.json().get("detail", "Operacao recusada.")
            if isinstance(detail, dict):
                return str(detail.get("message") or detail.get("detail") or detail)
            return str(detail)
        except Exception:
            return f"API recusou a operacao ({exc.response.status_code})."
    if isinstance(exc, (RuntimeError, ValueError)):
        return str(exc)
    return "Nao consegui concluir a operacao."


def _modal_values(interaction: discord.Interaction) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in (interaction.data or {}).get("components") or []:
        for component in row.get("components") or []:
            if component.get("custom_id"):
                result[str(component["custom_id"])] = str(component.get("value") or "")
    return result


def _selected_ids(interaction: discord.Interaction) -> list[str]:
    return [str(value) for value in ((interaction.data or {}).get("values") or [])]


def _hex_color(value: str) -> int:
    try:
        return int(value.lstrip("#"), 16)
    except (TypeError, ValueError):
        return COLOR


async def render_public(context: dict) -> ComponentsV2Payload:
    config = context.get("config")
    if config is None:
        config = (await context["api"].registration_config(context["guild"].id))["data"]
    components: list[dict[str, Any]] = []
    if config.get("panel_banner_url"):
        components.append(media(config["panel_banner_url"]))
    components.extend(
        [
            text_display(
                f"# {config['panel_title']}\n\n{config['panel_description']}\n\n"
                f"{config.get('panel_instructions') or ''}"
            ),
            separator(),
            action_row(
                button(
                    custom_id=custom_id("registration", "public", "open_form"),
                    label=config["button_label"],
                    emoji=config.get("button_emoji") or None,
                    style=1,
                )
            ),
            text_display(config.get("panel_footer") or "Yuno"),
        ]
    )
    return ComponentsV2Payload(
        payload(container(*components, accent_color=_hex_color(config.get("panel_color"))))
    )


async def render_review(context: dict) -> ComponentsV2Payload:
    request = context.get("request")
    if request is None:
        request = await context["api"].registration_request(
            context["guild"].id, str(context["resource_id"])
        )
    status = str(request["status"])
    lines = [
        "# Analise de registro",
        f"Membro: <@{request['discord_user_id']}>",
        f"Nome: **{request['submitted_name']}**",
        f"ID: `{request['player_id_original']}`",
        f"Estado: **{status.upper()}**",
    ]
    if request.get("reviewed_by"):
        lines.append(f"Decidido por: <@{request['reviewed_by']}>")
    if request.get("rejection_reason"):
        lines.append(f"Motivo: {request['rejection_reason']}")
    components = [text_display("\n".join(lines))]
    if status == "pending":
        components.extend(
            [
                separator(),
                action_row(
                    button(
                        custom_id=custom_id("registration", "review", "approve"),
                        label="Aprovar",
                        emoji="✅",
                        style=3,
                    ),
                    button(
                        custom_id=custom_id("registration", "review", "reject"),
                        label="Rejeitar",
                        emoji="❌",
                        style=4,
                    ),
                ),
            ]
        )
    return ComponentsV2Payload(payload(container(*components, accent_color=COLOR)))


class RegistrationModal(RoutedModal):
    def __init__(self, panel: dict) -> None:
        super().__init__(
            title="Fazer meu registro",
            module_key="registration",
            surface="public",
            action_key="submit",
            panel=panel,
        )
        self.add_item(
            discord.ui.TextInput(
                label="Nome",
                custom_id="registration_name",
                min_length=1,
                max_length=120,
            )
        )
        self.add_item(
            discord.ui.TextInput(
                label="ID",
                custom_id="registration_player_id",
                min_length=1,
                max_length=120,
            )
        )


class RejectionModal(RoutedModal):
    def __init__(self, panel: dict) -> None:
        super().__init__(
            title="Rejeitar registro",
            module_key="registration",
            surface="review",
            action_key="submit_rejection",
            panel=panel,
        )
        self.add_item(
            discord.ui.TextInput(
                label="Motivo",
                custom_id="registration_rejection_reason",
                style=discord.TextStyle.paragraph,
                min_length=1,
                max_length=1000,
            )
        )


async def open_form(context: RoutedContext) -> InteractionResult:
    return InteractionResult(modal=RegistrationModal(context.panel))


async def submit(context: RoutedContext) -> InteractionResult:
    values = _modal_values(context.interaction)
    try:
        result = await context.api.registration_submit(
            context.actor.guild_id,
            {
                "name": values.get("registration_name", ""),
                "player_id": values.get("registration_player_id", ""),
            },
            actor=context.actor,
            panel_config_version=context.panel.get("config_version"),
        )
        config = (await context.api.registration_config(context.actor.guild_id))["data"]
        return InteractionResult(
            content=f"{config['submitted_message']} Protocolo `{result['id']}`."
        )
    except Exception as exc:
        return InteractionResult(content=error_text(exc))


def _validate_delivery_role(guild: discord.Guild, role: discord.Role | None) -> None:
    bot_member = guild.me
    if role is None:
        raise RuntimeError("Cargo de membro nao encontrado.")
    if role.is_default() or role.managed:
        raise RuntimeError("O cargo entregue nao pode ser @everyone nem gerenciado.")
    if bot_member is None or not bot_member.guild_permissions.manage_roles:
        raise RuntimeError("O bot precisa de Gerenciar Cargos.")
    if bot_member.top_role <= role:
        raise RuntimeError("O cargo entregue precisa estar abaixo do maior cargo do bot.")
    protected = [name for name in PROTECTED_ROLE_PERMISSIONS if getattr(role.permissions, name, False)]
    if protected:
        raise RuntimeError("O cargo entregue possui permissoes administrativas protegidas.")


async def approve(context: RoutedContext) -> InteractionResult:
    interaction = context.interaction
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True, thinking=True)
    token: str | None = None
    member: discord.Member | None = None
    role: discord.Role | None = None
    nickname_changed = False
    role_added = False
    claim: dict[str, Any] | None = None
    previous_nickname: str | None = None
    try:
        claim = await context.api.registration_claim(
            context.actor.guild_id,
            context.panel["resource_id"],
            actor=context.actor,
        )
        token = claim["operation_token"]
        guild = interaction.guild
        assert guild is not None
        member = guild.get_member(int(claim["discord_user_id"]))
        if member is None:
            member = await guild.fetch_member(int(claim["discord_user_id"]))
        role = guild.get_role(int(claim["config"]["member_role_id"]))
        _validate_delivery_role(guild, role)
        if guild.me is None or not guild.me.guild_permissions.manage_nicknames:
            raise RuntimeError("O bot precisa de Gerenciar Apelidos.")
        if member.id == guild.owner_id or member.top_role >= guild.me.top_role:
            raise RuntimeError("O membro esta acima do bot na hierarquia.")
        previous_nickname = member.nick
        role_was_present = role in member.roles
        await context.api.registration_preflight(
            guild.id,
            claim["id"],
            {
                "operation_token": token,
                "previous_nickname": previous_nickname,
                "role_was_present": role_was_present,
                "target_nickname": claim["target_nickname"],
            },
            actor=context.actor,
        )
        await member.edit(nick=claim["target_nickname"], reason="Registro Yuno aprovado")
        nickname_changed = True
        await context.api.registration_step(guild.id, claim["id"], token, "nickname", actor=context.actor)
        if not role_was_present:
            await member.add_roles(role, reason="Registro Yuno aprovado")
            role_added = True
        await context.api.registration_step(guild.id, claim["id"], token, "role", actor=context.actor)
        await context.api.registration_complete(guild.id, claim["id"], token, actor=context.actor)
        return InteractionResult(content="Registro aprovado com nickname e cargo aplicados.")
    except Exception as exc:
        if token and claim and member is not None:
            compensated = True
            if role_added and role is not None:
                try:
                    await member.remove_roles(role, reason="Compensacao de aprovacao do Registro")
                except Exception:
                    compensated = False
            if nickname_changed:
                try:
                    await member.edit(
                        nick=previous_nickname,
                        reason="Compensacao de aprovacao do Registro",
                    )
                except Exception:
                    compensated = False
            try:
                await context.api.registration_release(
                    context.actor.guild_id,
                    claim["id"],
                    token,
                    actor=context.actor,
                    compensated=compensated,
                    error_code=type(exc).__name__,
                )
            except Exception:
                pass
        return InteractionResult(content=error_text(exc))


async def reject(context: RoutedContext) -> InteractionResult:
    return InteractionResult(modal=RejectionModal(context.panel))


async def submit_rejection(context: RoutedContext) -> InteractionResult:
    reason = _modal_values(context.interaction).get("registration_rejection_reason", "")
    try:
        await context.api.registration_reject(
            context.actor.guild_id,
            context.panel["resource_id"],
            reason,
            actor=context.actor,
        )
        return InteractionResult(content="Registro rejeitado.")
    except Exception as exc:
        return InteractionResult(content=error_text(exc))


def _module_select() -> dict[str, Any]:
    return string_select(
        custom_id=dashboard.central_custom_id("core", "select_module"),
        options=[
            {
                "label": spec.nome[:100],
                "value": spec.key,
                "emoji": {"name": spec.icon},
            }
            for spec in dashboard.dashboard_specs().values()
        ],
        placeholder="Trocar de modulo",
    )


def _section_select() -> dict[str, Any]:
    return string_select(
        custom_id=dashboard.central_custom_id("registration", "section"),
        options=[
            {"label": "Sistema", "value": "system", "emoji": {"name": "⚙️"}},
            {"label": "Painel publico", "value": "panel", "emoji": {"name": "🪧"}},
            {"label": "Mensagens", "value": "messages", "emoji": {"name": "💬"}},
        ],
        placeholder="Navegar no Registro",
    )


async def _replace_central(
    interaction: discord.Interaction,
    data: dict[str, Any],
    *,
    channel_id: int | None = None,
    message_id: int | None = None,
    notice: str = "Central atualizada.",
) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True, thinking=True)
    target_channel = channel_id or interaction.channel_id
    target_message = message_id or getattr(interaction.message, "id", None)
    if target_channel is None or target_message is None:
        raise RuntimeError("Referencia da Central indisponivel.")
    await edit_message(interaction.client, target_channel, target_message, data)
    await interaction.edit_original_response(content=notice)


async def _defer_if_needed(interaction: discord.Interaction) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True, thinking=True)


async def _send_interaction_error(interaction: discord.Interaction, message: str) -> None:
    if interaction.response.is_done():
        await interaction.edit_original_response(content=message)
    else:
        await interaction.response.send_message(message, ephemeral=True)


async def _admin_state(api: Any, guild_id: int) -> tuple[dict, dict]:
    return (
        await api.module_instance(guild_id, "registration"),
        await api.configuration_draft(guild_id, "registration"),
    )


async def render_admin(interaction: discord.Interaction, api: Any) -> None:
    try:
        instance, draft = await _admin_state(api, interaction.guild_id)
        published = int(draft["base_published_version"] or 0)
        action_label = "Editar" if published else "Configurar"
        data = payload(
            container(
                text_display(
                    "# 📝 Registro\n\n"
                    f"Lifecycle: **{instance['lifecycle']}**\n"
                    f"Configuracao publicada: **{published or 'nao'}**\n"
                    f"Rascunho: **r{draft['revision']}**"
                ),
                separator(),
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id("registration", "open_system"),
                        label=action_label,
                        emoji="✏️",
                    )
                ),
                action_row(_module_select()),
                accent_color=COLOR,
            )
        )
        await _replace_central(interaction, data, notice="Modulo Registro aberto.")
    except Exception as exc:
        if interaction.response.is_done():
            await interaction.edit_original_response(content=error_text(exc))
        else:
            await interaction.response.send_message(error_text(exc), ephemeral=True)


async def _render_section(
    interaction: discord.Interaction,
    api: Any,
    section: str,
    *,
    channel_id: int | None = None,
    message_id: int | None = None,
    notice: str = "Secao atualizada.",
) -> None:
    _, draft = await _admin_state(api, interaction.guild_id)
    config = draft["data"]
    components: list[dict[str, Any]] = [
        text_display(f"# Registro · {section.title()}\n\nRascunho **r{draft['revision']}**"),
        action_row(_section_select()),
    ]
    if section == "system":
        approvers = ", ".join(f"<@&{value}>" for value in config["approver_role_ids"]) or "nenhum"
        components.extend(
            [
                text_display(
                    f"**Painel:** <#{config['panel_channel_id']}>\n"
                    f"**Analise:** <#{config['approval_channel_id']}>\n"
                    f"**Logs:** <#{config['log_channel_id']}>\n"
                    f"**Cargo entregue:** <@&{config['member_role_id']}>\n"
                    f"**Aprovadores:** {approvers}\n"
                    f"**Nickname:** `{config['nickname_template']}`"
                ),
                action_row(channel_select(custom_id=dashboard.central_custom_id("registration", "set_panel_channel"), placeholder="Canal do painel publico", channel_types=[0])),
                action_row(channel_select(custom_id=dashboard.central_custom_id("registration", "set_approval_channel"), placeholder="Canal de analise", channel_types=[0])),
                action_row(channel_select(custom_id=dashboard.central_custom_id("registration", "set_log_channel"), placeholder="Canal de logs", channel_types=[0])),
                action_row(role_select(custom_id=dashboard.central_custom_id("registration", "set_member_role"), placeholder="Cargo entregue")),
                action_row(role_select(custom_id=dashboard.central_custom_id("registration", "add_approvers"), placeholder="Adicionar aprovadores (lote)", max_values=25)),
                action_row(role_select(custom_id=dashboard.central_custom_id("registration", "remove_approvers"), placeholder="Remover aprovadores (lote)", max_values=25)),
                action_row(
                    string_select(
                        custom_id=dashboard.central_custom_id("registration", "set_flags"),
                        options=[
                            {"label": "ID numerico", "value": "numeric_on"},
                            {"label": "ID alfanumerico", "value": "numeric_off"},
                            {"label": "Permitir reenvio", "value": "resubmit_on"},
                            {"label": "Bloquear reenvio", "value": "resubmit_off"},
                        ],
                        placeholder="Validacao e reenvio",
                        min_values=1,
                        max_values=2,
                    )
                ),
                action_row(
                    button(custom_id=dashboard.central_custom_id("registration", "edit_system"), label="Editar regras", emoji="✏️", style=2),
                    button(custom_id=dashboard.central_custom_id("registration", "review_publish"), label="Revisar publicacao", emoji="👁️", style=1),
                ),
            ]
        )
    elif section == "panel":
        components.extend(
            [
                text_display(
                    f"## {config['panel_title']}\n\n{config['panel_description']}\n\n"
                    f"Botao: {config['button_emoji']} {config['button_label']}\n"
                    f"Cor: `{config['panel_color']}`"
                ),
                action_row(button(custom_id=dashboard.central_custom_id("registration", "edit_panel"), label="Editar painel", emoji="✏️", style=2)),
                action_row(button(custom_id=dashboard.central_custom_id("registration", "review_publish"), label="Revisar publicacao", emoji="👁️", style=1)),
            ]
        )
    else:
        components.extend(
            [
                text_display(
                    f"**Enviado:** {config['submitted_message']}\n"
                    f"**Aprovado:** {config['approved_message']}\n"
                    f"**Rejeitado:** {config['rejected_message']}"
                ),
                action_row(button(custom_id=dashboard.central_custom_id("registration", "edit_messages"), label="Editar decisoes", emoji="✏️", style=2)),
                action_row(button(custom_id=dashboard.central_custom_id("registration", "edit_errors"), label="Editar alertas", emoji="⚠️", style=2)),
                action_row(button(custom_id=dashboard.central_custom_id("registration", "review_publish"), label="Revisar publicacao", emoji="👁️", style=1)),
            ]
        )
    components.append(action_row(_module_select()))
    await _replace_central(
        interaction,
        payload(container(*components, accent_color=COLOR)),
        channel_id=channel_id,
        message_id=message_id,
        notice=notice,
    )


async def open_system(interaction: discord.Interaction, api: Any) -> None:
    await _render_section(interaction, api, "system")


async def section(interaction: discord.Interaction, api: Any) -> None:
    values = _selected_ids(interaction)
    await _render_section(interaction, api, values[0] if values else "system")


async def _save_patch(interaction: discord.Interaction, api: Any, patch: dict[str, Any]) -> dict:
    draft = await api.configuration_draft(interaction.guild_id, "registration")
    actor = actor_from(interaction)
    return await api.save_configuration_draft(
        interaction.guild_id,
        "registration",
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
        await _send_interaction_error(interaction, "Selecione um valor.")
        return
    await _defer_if_needed(interaction)
    await _save_patch(interaction, api, {field: values[0]})
    await _render_section(interaction, api, "system", notice="Destino atualizado.")


async def set_panel_channel(interaction, api):
    await _set_selected(interaction, api, "panel_channel_id")


async def set_approval_channel(interaction, api):
    await _set_selected(interaction, api, "approval_channel_id")


async def set_log_channel(interaction, api):
    await _set_selected(interaction, api, "log_channel_id")


async def set_member_role(interaction, api):
    await _set_selected(interaction, api, "member_role_id")


async def _change_approvers(interaction: discord.Interaction, api: Any, *, remove: bool) -> None:
    values = _selected_ids(interaction)
    await _defer_if_needed(interaction)
    draft = await api.configuration_draft(interaction.guild_id, "registration")
    current = list(draft["data"]["approver_role_ids"])
    if remove:
        selected = set(values)
        updated = [value for value in current if value not in selected]
    else:
        updated = list(dict.fromkeys([*current, *values]))
    await _save_patch(interaction, api, {"approver_role_ids": updated})
    await _render_section(interaction, api, "system", notice="Aprovadores atualizados.")


async def add_approvers(interaction, api):
    await _change_approvers(interaction, api, remove=False)


async def remove_approvers(interaction, api):
    await _change_approvers(interaction, api, remove=True)


async def set_flags(interaction: discord.Interaction, api: Any) -> None:
    values = set(_selected_ids(interaction))
    patch: dict[str, Any] = {}
    if "numeric_on" in values and "numeric_off" in values:
        await _send_interaction_error(interaction, "Escolha apenas um modo de ID.")
        return
    if "resubmit_on" in values and "resubmit_off" in values:
        await _send_interaction_error(interaction, "Escolha apenas uma regra de reenvio.")
        return
    if "numeric_on" in values:
        patch["player_id_numeric_only"] = True
    if "numeric_off" in values:
        patch["player_id_numeric_only"] = False
    if "resubmit_on" in values:
        patch["allow_resubmit_after_rejection"] = True
    if "resubmit_off" in values:
        patch["allow_resubmit_after_rejection"] = False
    await _defer_if_needed(interaction)
    await _save_patch(interaction, api, patch)
    await _render_section(interaction, api, "system", notice="Regras atualizadas.")


CONFIG_MODAL_FIELDS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "system": (
        ("nickname_template", "Template de nickname", "{name} | {id}"),
        ("player_id_min_length", "Minimo do ID", "1"),
        ("player_id_max_length", "Maximo do ID", "16"),
        ("name_min_length", "Minimo do nome", "2"),
        ("name_max_length", "Maximo do nome", "24"),
    ),
    "panel": (
        ("panel_title", "Titulo", "Registro"),
        ("panel_description", "Descricao", ""),
        ("panel_instructions", "Instrucoes", ""),
        ("button_label", "Texto do botao", "Fazer meu registro"),
        ("panel_color", "Cor #RRGGBB", "#FFC72C"),
    ),
    "messages": (
        ("submitted_message", "Enviado", ""),
        ("approved_message", "Aprovado", ""),
        ("rejected_message", "Rejeitado", ""),
        ("already_pending_message", "Ja pendente", ""),
        ("generic_error_message", "Erro generico", ""),
    ),
    "errors": (
        ("already_registered_message", "Ja registrado", ""),
        ("duplicate_id_message", "ID duplicado", ""),
        ("resubmit_not_allowed_message", "Reenvio bloqueado", ""),
        ("panel_banner_url", "URL do banner (opcional)", ""),
        ("panel_thumbnail_url", "URL da miniatura (opcional)", ""),
    ),
}


class AdminConfigModal(discord.ui.Modal):
    def __init__(self, api: Any, group: str, config: dict, channel_id: int, message_id: int) -> None:
        super().__init__(title=f"Registro · {group.title()}")
        self.api = api
        self.group = group
        self.central_channel_id = channel_id
        self.central_message_id = message_id
        for key, label, placeholder in CONFIG_MODAL_FIELDS[group]:
            current = str(config.get(key, ""))
            style = discord.TextStyle.paragraph if len(current) > 100 else discord.TextStyle.short
            self.add_item(
                discord.ui.TextInput(
                    label=label,
                    custom_id=key,
                    default=current or None,
                    placeholder=placeholder or None,
                    max_length=2000 if style == discord.TextStyle.paragraph else 120,
                    required=key not in {"panel_banner_url", "panel_thumbnail_url"},
                    style=style,
                )
            )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        values: dict[str, Any] = _modal_values(interaction)
        for key in ("player_id_min_length", "player_id_max_length", "name_min_length", "name_max_length"):
            if key in values:
                try:
                    values[key] = int(values[key])
                except ValueError:
                    await interaction.edit_original_response(content=f"{key} deve ser numero inteiro.")
                    return
        try:
            await _save_patch(interaction, self.api, values)
            section_name = "messages" if self.group in {"messages", "errors"} else self.group
            await _render_section(
                interaction,
                self.api,
                section_name,
                channel_id=self.central_channel_id,
                message_id=self.central_message_id,
                notice="Rascunho salvo.",
            )
        except Exception as exc:
            await interaction.edit_original_response(content=error_text(exc))


async def _open_config_modal(interaction: discord.Interaction, api: Any, group: str) -> None:
    draft = await api.configuration_draft(interaction.guild_id, "registration")
    await interaction.response.send_modal(
        AdminConfigModal(
            api,
            group,
            draft["data"],
            interaction.channel_id,
            interaction.message.id,
        )
    )


async def edit_system(interaction, api):
    await _open_config_modal(interaction, api, "system")


async def edit_panel(interaction, api):
    await _open_config_modal(interaction, api, "panel")


async def edit_messages(interaction, api):
    await _open_config_modal(interaction, api, "messages")


async def edit_errors(interaction, api):
    await _open_config_modal(interaction, api, "errors")


async def _preflight(guild: discord.Guild, config: dict) -> list[str]:
    errors: list[str] = []
    bot_member = guild.me
    for key in ("panel_channel_id", "approval_channel_id", "member_role_id"):
        if not config.get(key):
            errors.append(f"Campo obrigatorio ausente: {key}.")
    for key in ("panel_channel_id", "approval_channel_id", "log_channel_id"):
        value = config.get(key)
        if not value:
            continue
        channel = guild.get_channel(int(value))
        if not isinstance(channel, discord.TextChannel):
            errors.append(f"{key} nao aponta para canal de texto.")
            continue
        if bot_member:
            perms = channel.permissions_for(bot_member)
            if not perms.view_channel or not perms.send_messages:
                errors.append(f"Bot sem acesso de envio em {channel.mention}.")
    role = guild.get_role(int(config["member_role_id"])) if config.get("member_role_id") else None
    try:
        _validate_delivery_role(guild, role)
    except RuntimeError as exc:
        errors.append(str(exc))
    for role_id in config.get("approver_role_ids") or []:
        approver = guild.get_role(int(role_id))
        if approver is None or approver.is_default():
            errors.append(f"Cargo aprovador invalido: {role_id}.")
    if bot_member and not bot_member.guild_permissions.manage_nicknames:
        errors.append("Bot sem Gerenciar Apelidos.")
    return errors


async def review_publish(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    draft = await api.configuration_draft(interaction.guild_id, "registration")
    errors = await _preflight(interaction.guild, draft["data"])
    if errors:
        await interaction.edit_original_response(content="Publicacao bloqueada:\n- " + "\n- ".join(errors))
        return
    config = draft["data"]
    data = payload(
        container(
            text_display(
                "# Revisar publicacao do Registro\n\n"
                f"Painel: <#{config['panel_channel_id']}>\n"
                f"Analise: <#{config['approval_channel_id']}>\n"
                f"Cargo: <@&{config['member_role_id']}>\n"
                f"Aprovadores: **{len(config['approver_role_ids'])}**\n"
                f"Template: `{config['nickname_template']}`\n\n"
                "A confirmacao cria uma versao imutavel e reconcilia o painel publico."
            ),
            action_row(
                button(custom_id=dashboard.central_custom_id("registration", "confirm_publish"), label="Confirmar publicacao", emoji="✅", style=3),
                button(custom_id=dashboard.central_custom_id("registration", "open_system"), label="Voltar", emoji="↩️", style=2),
            ),
            accent_color=COLOR,
        )
    )
    await _replace_central(interaction, data, notice="Revisao pronta para confirmacao.")


async def confirm_publish(interaction: discord.Interaction, api: Any) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    actor = actor_from(interaction)
    draft = await api.configuration_draft(interaction.guild_id, "registration")
    errors = await _preflight(interaction.guild, draft["data"])
    if errors:
        await interaction.edit_original_response(content="Publicacao bloqueada:\n- " + "\n- ".join(errors))
        return
    grants = [
        {
            "capability": "registration.submit",
            "subject_type": "everyone",
            "subject_id": "",
            "scope_type": "guild",
            "scope_id": "",
            "constraints": {},
        }
    ]
    grants.extend(
        {
            "capability": "registration.review",
            "subject_type": "role",
            "subject_id": role_id,
            "scope_type": "guild",
            "scope_id": "",
            "constraints": {},
        }
        for role_id in draft["data"]["approver_role_ids"]
    )
    try:
        version = await api.publish_configuration(
            interaction.guild_id,
            "registration",
            {
                "expected_revision": draft["revision"],
                "expected_published_version": draft["base_published_version"],
                "grants": grants,
            },
            actor=actor,
        )
        instance = await api.module_instance(interaction.guild_id, "registration")
        try:
            await PanelPublisher(interaction.client, api).reconcile(
                guild=interaction.guild,
                module_key="registration",
                panel_key="public",
                channel_id=int(draft["data"]["panel_channel_id"]),
                actor=actor,
                render_context={
                    "config": draft["data"],
                    "config_version": version["version"],
                },
            )
        except Exception:
            await api.schedule_task(
                interaction.guild_id,
                "registration",
                {
                    "job_key": "registration.panel.reconcile",
                    "resource_type": "panel",
                    "resource_id": "public",
                    "payload": {"panel_key": "public"},
                    "due_at": datetime.now(timezone.utc).isoformat(),
                    "idempotency_key": f"public:{version['version']}",
                    "correlation_id": actor.correlation_id,
                    "max_attempts": 5,
                },
            )
            await interaction.edit_original_response(
                content="Versao publicada, mas o painel visual ficou na versao anterior. A reconciliacao foi enfileirada."
            )
            return
        if instance["lifecycle"] != "active":
            await api.update_lifecycle(
                interaction.guild_id,
                "registration",
                lifecycle="active",
                expected_lifecycle=instance["lifecycle"],
                actor=actor,
                reason=None,
            )
        await render_admin(interaction, api)
        await interaction.edit_original_response(
            content=f"Registro publicado na versao {version['version']} e painel reconciliado."
        )
    except Exception as exc:
        await interaction.edit_original_response(content=error_text(exc))


async def deliver_review(bot: discord.Client, item: dict) -> str | None:
    guild = bot.get_guild(int(item["guild_id"]))
    if guild is None:
        raise RuntimeError("Guild indisponivel para painel de analise.")
    api = bot.platform_api
    request_id = str(item["resource_id"])
    request = await api.registration_request(guild.id, request_id)
    config_ref = await api.registration_config(guild.id)
    actor = system_actor(bot, guild.id, item["correlation_id"])
    panel = await PanelPublisher(bot, api).reconcile(
        guild=guild,
        module_key="registration",
        panel_key="review",
        channel_id=int(item["destination_id"]),
        actor=actor,
        resource_type="registration_request",
        resource_id=request_id,
        render_context={
            "request": request,
            "config_version": config_ref["version"],
        },
    )
    await api.registration_attach_review_message(
        guild.id,
        request_id,
        int(panel["channel_id"]),
        int(panel["message_id"]),
        actor=actor,
    )
    return str(panel["message_id"])


async def deliver_log(bot: discord.Client, item: dict) -> str | None:
    channel = bot.get_channel(int(item["destination_id"]))
    if channel is None:
        channel = await bot.fetch_channel(int(item["destination_id"]))
    data = item.get("payload") or {}
    decision = data.get("decision", "registro")
    embed = discord.Embed(
        title=f"Registro {decision}",
        description=f"Solicitacao `{data.get('request_id')}`",
        color=COLOR if decision == "approved" else 0xED4245,
    )
    if data.get("reason"):
        embed.add_field(name="Motivo", value=str(data["reason"])[:1024], inline=False)
    message = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    return str(message.id)


async def deliver_dm(bot: discord.Client, item: dict) -> str | None:
    user = bot.get_user(int(item["destination_id"])) or await bot.fetch_user(
        int(item["destination_id"])
    )
    data = item.get("payload") or {}
    embed = discord.Embed(
        title="Atualizacao do seu registro",
        description=str(data.get("message") or "Seu registro foi atualizado."),
        color=COLOR,
    )
    message = await user.send(embed=embed)
    return str(message.id)


async def run_job(bot: discord.Client, api: Any, item: dict) -> dict:
    guild = bot.get_guild(int(item["guild_id"]))
    if guild is None:
        raise RuntimeError("Guild indisponivel para recuperacao.")
    actor = system_actor(bot, guild.id, item["correlation_id"])
    if item["key"] == "registration.panel.reconcile":
        config_ref = await api.registration_config(guild.id)
        config = config_ref["data"]
        await PanelPublisher(bot, api).reconcile(
            guild=guild,
            module_key="registration",
            panel_key="public",
            channel_id=int(config["panel_channel_id"]),
            actor=actor,
            render_context={"config": config, "config_version": config_ref["version"]},
        )
        instance = await api.module_instance(guild.id, "registration")
        activated = False
        if instance["lifecycle"] != "active":
            await api.update_lifecycle(
                guild.id,
                "registration",
                lifecycle="active",
                expected_lifecycle=instance["lifecycle"],
                actor=actor,
                reason="Painel publico recuperado apos publicacao.",
            )
            activated = True
        return {"changed": True, "panel_key": "public", "activated": activated}
    if item["key"] != "registration.processing.recover":
        return {"changed": False, "reason": "job desconhecido"}
    stale = await api.registration_stale(guild.id)
    request = next(
        (value for value in stale if value["id"] == item["resource_id"]), None
    )
    if request is None:
        return {"changed": False, "reason": "claim nao esta vencido"}
    token = request["operation_token"]
    config_ref = await api.registration_config(guild.id)
    instance = await api.module_instance(guild.id, "registration")
    member = guild.get_member(int(request["discord_user_id"]))
    if member is None:
        try:
            member = await guild.fetch_member(int(request["discord_user_id"]))
        except discord.NotFound:
            member = None
    config_matches = (
        instance["lifecycle"] == "active"
        and config_ref["data"].get("enabled") is True
        and config_ref["version_id"] == request["config_version_reviewed_id"]
    )
    reviewed_config = request.get("reviewed_config") or config_ref["data"]
    role = guild.get_role(int(reviewed_config["member_role_id"]))
    discord_complete = bool(
        member
        and role
        and member.nick == request.get("target_nickname")
        and role in member.roles
        and config_matches
    )
    if discord_complete:
        await api.registration_complete(guild.id, request["id"], token, actor=actor)
        return {"changed": True, "result": "finalized"}
    compensated = member is not None
    if member is not None:
        if role and request.get("role_applied") and not request.get("role_was_present") and role in member.roles:
            try:
                await member.remove_roles(role, reason="Recuperacao do Registro Yuno")
            except Exception:
                compensated = False
        if request.get("nickname_applied"):
            try:
                await member.edit(nick=request.get("previous_nickname"), reason="Recuperacao do Registro Yuno")
            except Exception:
                compensated = False
    await api.registration_release(
        guild.id,
        request["id"],
        token,
        actor=actor,
        compensated=compensated,
        error_code="recovery_compensated" if compensated else "recovery_incomplete",
    )
    if not compensated:
        raise RuntimeError("Compensacao Discord continua incompleta.")
    return {"changed": True, "result": "compensated"}
