"""Configuração de Entrada e Saída de Membros dentro da Central de Gestão.

Ao contrário de Tickets de Farm, aqui não há campo obrigatório que bloqueie o
rascunho: os dois canais são exigidos só na publicação (`preflight`), e cargos
de entrada e mensagem extra são sempre opcionais. Por isso não existe o
mecanismo de memória de sessão (`_pending`) usado em farm_tickets/admin.py —
cada seleção já é persistível.
"""

from __future__ import annotations

from typing import Any

import discord
import httpx

from yuno_bot import dashboard
from yuno_bot.platform import ui_kit as uk
from yuno_bot.platform.components_v2 import (
    action_row,
    button,
    channel_select,
    container,
    edit_message,
    payload,
    role_select,
    separator,
    text_display,
)
from yuno_bot.platform.contracts import ActorContext

MODULE_KEY = "log_membros"
COLOR = uk.BRAND
TEXT_CHANNEL_TYPE = 0
MAX_JOIN_ROLES = 25
EXTRA_MESSAGE_MAX_LENGTH = 500

EMPTY_CONFIG: dict[str, Any] = {
    "join_channel_id": "",
    "leave_channel_id": "",
    "join_role_ids": [],
    "leave_extra_message": "",
}

UNDEFINED = "⚪ Ainda não definido"


def actor_from(interaction: discord.Interaction) -> ActorContext:
    member = interaction.user if isinstance(interaction.user, discord.Member) else None
    permissions = tuple(
        name for name, enabled in (member.guild_permissions if member else []) if enabled
    )
    return ActorContext(
        guild_id=int(interaction.guild_id or 0),
        user_id=interaction.user.id if interaction.user else None,
        role_ids=tuple(role.id for role in member.roles) if member else (),
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


def error_text(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            detail = exc.response.json().get("detail", "Operação recusada.")
            if isinstance(detail, dict):
                errors = detail.get("errors")
                if isinstance(errors, list) and errors:
                    return "\n- ".join([str(detail.get("detail") or "Operação recusada."), *map(str, errors)])
                return str(detail.get("message") or detail.get("detail") or detail)
            return str(detail)
        except Exception:
            return f"A API recusou a operação ({exc.response.status_code})."
    if isinstance(exc, (RuntimeError, ValueError)):
        return str(exc)
    return "Não consegui concluir a operação."


def _selected_ids(interaction: discord.Interaction) -> list[str]:
    return [str(value) for value in ((interaction.data or {}).get("values") or [])]


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


def _missing_fields(config: dict[str, Any]) -> list[str]:
    labels = {
        "join_channel_id": "Canal de log de entrada",
        "leave_channel_id": "Canal de log de saída",
    }
    return [label for key, label in labels.items() if not config.get(key)]


def _channel_ref(value: Any) -> str:
    text = str(value or "").strip()
    return f"<#{text}>" if text else UNDEFINED


def _roles_ref(config: dict[str, Any]) -> str:
    roles = list(config.get("join_role_ids") or [])
    return ", ".join(f"<@&{role_id}>" for role_id in roles) if roles else "Nenhum (opcional)."


def _extra_message_ref(config: dict[str, Any]) -> str:
    text = str(config.get("leave_extra_message") or "").strip()
    return text if text else "Nenhuma (opcional)."


CONFIG_LINE_ORDER = ("join_channel_id", "leave_channel_id", "join_role_ids", "leave_extra_message")


def _config_lines(config: dict[str, Any], *, keys: tuple[str, ...] = CONFIG_LINE_ORDER) -> str:
    rendered = {
        "join_channel_id": f"**📥 Canal de log de entrada** — {_channel_ref(config['join_channel_id'])}",
        "leave_channel_id": f"**📤 Canal de log de saída** — {_channel_ref(config['leave_channel_id'])}",
        "join_role_ids": f"**🎭 Cargos atribuídos na entrada** — {_roles_ref(config)}",
        "leave_extra_message": f"**📝 Mensagem extra na saída** — {_extra_message_ref(config)}",
    }
    return "\n".join(rendered[key] for key in keys)


def build_admin_payload(instance: dict, config: dict[str, Any]) -> dict[str, Any]:
    published = instance.get("published_config_version_id") is not None
    is_active = published and instance.get("lifecycle") == "active"
    if is_active:
        state = uk.State.APPROVED
        status = uk.badge(state, "Ativo", bold=True)
        status_detail = "O log de entrada e saída está publicado e atendendo o servidor."
    elif published:
        state = uk.State.RUNNING
        status = uk.badge(state, "Publicado, porém inativo", bold=True)
        status_detail = "A configuração existe, mas o módulo não está atendendo."
    else:
        state = uk.State.PENDING
        status = uk.badge(state, "Ainda não publicado", bold=True)
        status_detail = "Enquanto não houver publicação, nenhuma entrada ou saída é registrada."
    return payload(
        uk.panel(
            header=[
                dashboard.module_navigation(MODULE_KEY),
                uk.space(),
                uk.heading("Entrada e Saída de Membros", emoji="👥")
                + "\n\nLog automático de entrada e saída, com cargo de boas-vindas "
                "configurável e detecção de expulsão/banimento.",
            ],
            blocks=[
                uk.field("Status", f"{status}\n{status_detail}", emoji="📌"),
                uk.rule(),
                uk.field("Configuração", _config_lines(config), emoji="🧭"),
            ],
            actions=[
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id(MODULE_KEY, "open_system"),
                        label="Configurar entrada e saída",
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
        container(
            dashboard.module_navigation(MODULE_KEY),
            separator(spacing=1),
            text_display(
                uk.heading("Entrada e Saída de Membros", emoji="👥")
                + "\n\nEscolha os canais de log e, se quiser, cargos automáticos de "
                "entrada. Nada muda no Discord antes da publicação."
            ),
            separator(spacing=1),
            text_display(
                f"{uk.section_number(1, 'Canais de log', emoji='📍')}\n\n"
                + _config_lines(config, keys=("join_channel_id", "leave_channel_id"))
            ),
            action_row(
                channel_select(
                    custom_id=dashboard.central_custom_id(MODULE_KEY, "set_join_channel"),
                    placeholder="Publicar o log de entrada em…",
                    channel_types=[TEXT_CHANNEL_TYPE],
                )
            ),
            action_row(
                channel_select(
                    custom_id=dashboard.central_custom_id(MODULE_KEY, "set_leave_channel"),
                    placeholder="Publicar o log de saída em…",
                    channel_types=[TEXT_CHANNEL_TYPE],
                )
            ),
            separator(spacing=1),
            text_display(
                f"{uk.section_number(2, 'Cargo automático na entrada', emoji='🎭')}\n\n"
                + _config_lines(config, keys=("join_role_ids",))
                + "\n\nOpcional. Cada novo membro recebe estes cargos automaticamente."
            ),
            action_row(
                role_select(
                    custom_id=dashboard.central_custom_id(MODULE_KEY, "set_join_roles"),
                    placeholder="Cargos atribuídos a cada novo membro (opcional)",
                    min_values=0,
                    max_values=MAX_JOIN_ROLES,
                )
            ),
            separator(spacing=1),
            text_display(
                f"{uk.section_number(3, 'Mensagem extra na saída', emoji='📝')}\n\n"
                + _config_lines(config, keys=("leave_extra_message",))
                + "\n\nOpcional. Texto livre anexado ao final do log de saída."
            ),
            action_row(
                button(
                    custom_id=dashboard.central_custom_id(MODULE_KEY, "edit_leave_message"),
                    label="Editar mensagem extra",
                    emoji="📝",
                    style=2,
                )
            ),
            separator(spacing=1),
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
            accent_color=COLOR,
        )
    )


async def _render_system(
    interaction: discord.Interaction, api: Any, *, config: dict[str, Any] | None = None
) -> None:
    if config is None:
        _, draft = await _admin_state(api, interaction.guild_id)
        config = _merge(draft)
    await _replace_central(interaction, build_system_payload(config))


async def open_system(interaction: discord.Interaction, api: Any) -> None:
    try:
        await _render_system(interaction, api)
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
    await _render_system(interaction, api, config=config)


async def _set_single(interaction: discord.Interaction, api: Any, field: str) -> None:
    values = _selected_ids(interaction)
    if not values:
        await _send_interaction_error(interaction, "Selecione um canal.")
        return
    try:
        await _apply_patch(interaction, api, {field: values[0]})
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))


async def set_join_channel(interaction: discord.Interaction, api: Any) -> None:
    await _set_single(interaction, api, "join_channel_id")


async def set_leave_channel(interaction: discord.Interaction, api: Any) -> None:
    await _set_single(interaction, api, "leave_channel_id")


async def set_join_roles(interaction: discord.Interaction, api: Any) -> None:
    values = _selected_ids(interaction)
    try:
        await _apply_patch(interaction, api, {"join_role_ids": list(dict.fromkeys(values))})
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))


class LeaveMessageModal(discord.ui.Modal, title="Log de Saída · Mensagem extra"):
    def __init__(self, api: Any, current: str) -> None:
        super().__init__()
        self.api = api
        self.message_input = discord.ui.TextInput(
            label="Mensagem extra (opcional)",
            custom_id="leave_extra_message",
            default=current or None,
            placeholder="Ex.: lembrete para revisar algum processo interno.",
            max_length=EXTRA_MESSAGE_MAX_LENGTH,
            required=False,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer()
            await _apply_patch(
                interaction, self.api, {"leave_extra_message": str(self.message_input.value or "")}
            )
        except Exception as exc:
            await _send_interaction_error(interaction, error_text(exc))


async def edit_leave_message(interaction: discord.Interaction, api: Any) -> None:
    try:
        _, draft = await _admin_state(api, interaction.guild_id)
        config = _merge(draft)
        await interaction.response.send_modal(
            LeaveMessageModal(api, str(config.get("leave_extra_message") or ""))
        )
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))


def preflight(guild: discord.Guild, config: dict[str, Any]) -> list[str]:
    errors: list[str] = [
        f"Campo obrigatório ausente: {label}." for label in _missing_fields(config)
    ]
    bot_member = guild.me
    for key, label in (
        ("join_channel_id", "Canal de log de entrada"),
        ("leave_channel_id", "Canal de log de saída"),
    ):
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
    if config.get("join_channel_id") and config["join_channel_id"] == config.get("leave_channel_id"):
        errors.append("O log de entrada e o de saída precisam de canais diferentes.")
    role_ids = config.get("join_role_ids") or []
    for role_id in role_ids:
        role = guild.get_role(int(role_id))
        if role is None:
            errors.append(f"Cargo de entrada inexistente: {role_id}.")
        elif role.is_default():
            errors.append("@everyone não pode ser cargo automático de entrada.")
        elif bot_member is not None and role >= bot_member.top_role:
            errors.append(f"O cargo {role.mention} está acima do cargo do bot na hierarquia.")
    if role_ids and bot_member is not None and not bot_member.guild_permissions.manage_roles:
        errors.append("Bot sem Gerenciar Cargos, exigido para atribuir cargos de entrada.")
    return errors


async def review_publish(interaction: discord.Interaction, api: Any) -> None:
    try:
        await _defer_if_needed(interaction)
        _, draft = await _admin_state(api, interaction.guild_id)
        config = _merge(draft)
        errors = preflight(interaction.guild, config)
        if errors:
            await _send_interaction_error(
                interaction, "Publicação bloqueada:\n- " + "\n- ".join(errors)
            )
            return
        await _replace_central(
            interaction,
            payload(
                container(
                    dashboard.module_navigation(MODULE_KEY),
                    separator(spacing=1),
                    text_display(
                        uk.heading("Revisar publicação de Entrada e Saída", emoji="👁️")
                        + f"\n\n{_config_lines(config)}\n\n"
                        "A confirmação cria uma versão imutável desta configuração."
                    ),
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
                    ),
                    accent_color=COLOR,
                )
            ),
        )
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))


async def confirm_publish(interaction: discord.Interaction, api: Any) -> None:
    try:
        await _defer_if_needed(interaction)
        actor = actor_from(interaction)
        instance, draft = await _admin_state(api, interaction.guild_id)
        config = _merge(draft)
        errors = preflight(interaction.guild, config)
        if errors:
            await _send_interaction_error(
                interaction, "Publicação bloqueada:\n- " + "\n- ".join(errors)
            )
            return
        version = await api.publish_configuration(
            interaction.guild_id,
            MODULE_KEY,
            {
                "expected_revision": draft["revision"],
                "expected_published_version": draft["base_published_version"],
                "grants": [],
            },
            actor=actor,
        )
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
            f"Entrada e Saída de Membros publicado na versão {version['version']}.",
            ephemeral=True,
        )
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))
