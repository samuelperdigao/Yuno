"""Configuração dos Tickets de Farm dentro da Central de Gestão.

O módulo exige configuração publicada (`LifecyclePolicy(requires_published_configuration=True)`)
antes de provisionar categoria, canais e painel.  Esta superfície é o único caminho
que cria essa publicação: rascunho -> seleções -> revisão -> publicação.

A tipografia (numeração das seções, selos de estado, rodapé `-#`) vem de
`platform/ui_kit.py`, o mesmo kit usado pelo painel público do módulo.
"""

from __future__ import annotations

from typing import Any

import discord
import httpx

from yuno_bot import dashboard
from yuno_bot.platform.components_v2 import (
    action_row,
    button,
    channel_select,
    edit_message,
    payload,
    role_select,
    text_display,
)
from yuno_bot.platform import ui_kit as uk
from yuno_bot.platform.contracts import ActorContext

MODULE_KEY = "farm_tickets"
COLOR = uk.NEXUS_VIOLET
TEXT_CHANNEL_TYPE = 0
CATEGORY_CHANNEL_TYPE = 4
MAX_ADMIN_ROLES = 25

# Espelha ADMIN_CAPABILITIES de backend/app/domain_modules/farm_tickets/definition.py.
# O publish e recusado quando os grants nao cobrem exatamente estas capabilities
# para todos os cargos administradores configurados.
ADMIN_CAPABILITIES = (
    "farm_tickets.open_for_member",
    "farm_tickets.submit",
    "farm_tickets.edit",
    "farm_tickets.read_proofs",
    "farm_tickets.withdraw",
    "farm_tickets.assign",
    "farm_tickets.approve",
    "farm_tickets.finalize",
    "farm_tickets.delete",
)

EMPTY_CONFIG: dict[str, Any] = {
    "category_id": "",
    "panel_channel_id": "",
    "log_channel_id": "",
    "administrator_role_ids": [],
}

# `administrator_role_ids` e obrigatorio com `min_length: 1`, entao o backend
# recusa qualquer rascunho sem cargo administrador.  Enquanto o primeiro cargo
# nao entra, as escolhas ficam nesta memoria de sessao e sao gravadas juntas.
_pending: dict[tuple[int, int], dict[str, Any]] = {}


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


def _session_key(interaction: discord.Interaction) -> tuple[int, int]:
    return (
        int(interaction.guild_id or 0),
        int(interaction.user.id) if interaction.user else 0,
    )


def _merge(draft: dict, key: tuple[int, int], patch: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        **EMPTY_CONFIG,
        **(draft.get("data") or {}),
        **_pending.get(key, {}),
        **(patch or {}),
    }


def _is_persistable(config: dict[str, Any]) -> bool:
    return bool(config.get("administrator_role_ids"))


def _missing_fields(config: dict[str, Any]) -> list[str]:
    labels = {
        "category_id": "Categoria principal",
        "panel_channel_id": "Canal do painel",
        "log_channel_id": "Canal de logs",
        "administrator_role_ids": "Cargos administradores",
    }
    return [label for key, label in labels.items() if not config.get(key)]


UNDEFINED = "⚪ Ainda não definido"


def _reference(value: Any, *, kind: str) -> str:
    text = str(value or "").strip()
    if not text:
        return UNDEFINED
    return f"<#{text}>" if kind == "channel" else f"<@&{text}>"


def _role_summary(config: dict[str, Any]) -> str:
    roles = list(config.get("administrator_role_ids") or [])
    if not roles:
        return UNDEFINED
    return ", ".join(f"<@&{role_id}>" for role_id in roles)


CONFIG_LINE_ORDER = ("category_id", "panel_channel_id", "log_channel_id", "administrator_role_ids")


def _config_lines(config: dict[str, Any], *, keys: tuple[str, ...] = CONFIG_LINE_ORDER) -> str:
    """Resumo da configuração, opcionalmente só dos campos de uma seção."""

    rendered = {
        "category_id": ("CATEGORIA", _reference(config["category_id"], kind="channel")),
        "panel_channel_id": ("PAINEL PÚBLICO", _reference(config["panel_channel_id"], kind="channel")),
        "log_channel_id": ("AUDITORIA", _reference(config["log_channel_id"], kind="channel")),
        "administrator_role_ids": ("EQUIPE", _role_summary(config)),
    }
    return uk.nexus_metrics(*(rendered[key] for key in keys))


def build_admin_payload(instance: dict, config: dict[str, Any]) -> dict[str, Any]:
    published = int(instance.get("published_config_version_id") is not None)
    is_active = bool(published) and instance.get("lifecycle") == "active"
    if is_active:
        state = uk.State.APPROVED
        status = "Operacional"
        status_detail = "O painel de tickets está publicado e atendendo os membros."
    elif published:
        state = uk.State.RUNNING
        status = "Publicado, porém inativo"
        status_detail = "A configuração existe, mas o módulo não está atendendo."
    else:
        state = uk.State.PENDING
        status = "Aguardando publicação"
        status_detail = (
            "Enquanto não houver publicação, nenhuma categoria, canal ou painel é criado."
        )
    return dashboard.central_shell(payload(
        uk.panel(
            header=[
                uk.nexus_title(
                    "TICKETS DE FARM",
                    path="MODULES / FARM TICKETS",
                    subtitle="Lançamentos comprovados e recolhimentos vinculados aos ciclos de Metas.",
                ),
            ],
            blocks=[
                text_display(uk.nexus_state("ESTADO", status, state=state) + "\n" + status_detail),
                text_display(uk.nexus_configuration(
                    ("CATEGORIA", _reference(config["category_id"], kind="channel")),
                    ("PAINEL PÚBLICO", _reference(config["panel_channel_id"], kind="channel")),
                    ("AUDITORIA", _reference(config["log_channel_id"], kind="channel")),
                    ("EQUIPE", _role_summary(config)),
                )),
            ],
            actions=[
                action_row(
                    button(
                        custom_id=dashboard.central_custom_id(MODULE_KEY, "open_system"),
                        label="CONFIGURAR",
                        style=1,
                    ),
                    button(
                        custom_id=dashboard.route_custom_id(MODULE_KEY, "diagnostic"),
                        label="DIAGNÓSTICO",
                        style=2,
                    ),
                ),
                dashboard.route_navigation(MODULE_KEY, "overview"),
            ],
            footer="NEXUS CORE // SESSION ACTIVE",
            accent_color=COLOR,
        )
    ))


async def render_admin(interaction: discord.Interaction, api: Any) -> None:
    try:
        instance, draft = await _admin_state(api, interaction.guild_id)
        config = _merge(draft, _session_key(interaction))
        await _replace_central(interaction, build_admin_payload(instance, config))
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))


def build_system_payload(config: dict[str, Any], *, unsaved: bool) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = [
        text_display(
            "// GERAL\n\n"
            + _config_lines(config, keys=("category_id", "panel_channel_id", "log_channel_id"))
        ),
        action_row(
                channel_select(
                    custom_id=dashboard.central_custom_id(MODULE_KEY, "set_category"),
                    placeholder="Categoria que recebe os canais de ticket…",
                    channel_types=[CATEGORY_CHANNEL_TYPE],
                )
        ),
        action_row(
                channel_select(
                    custom_id=dashboard.central_custom_id(MODULE_KEY, "set_panel_channel"),
                    placeholder="Publicar o painel de abertura em…",
                    channel_types=[TEXT_CHANNEL_TYPE],
                )
        ),
        action_row(
                channel_select(
                    custom_id=dashboard.central_custom_id(MODULE_KEY, "set_log_channel"),
                    placeholder="Registrar o histórico e os logs em…",
                    channel_types=[TEXT_CHANNEL_TYPE],
                )
        ),
        uk.rule(),
        text_display(
            "// EQUIPE\n\n"
            + _config_lines(config, keys=("administrator_role_ids",))
            + "\n\nEstes cargos recolhem, assumem, aprovam e finalizam os tickets. "
            "Abrir o próprio ticket continua liberado para todos os membros."
        ),
        action_row(
                role_select(
                    custom_id=dashboard.central_custom_id(MODULE_KEY, "set_admin_roles"),
                    placeholder="Cargos que recolhem, aprovam e finalizam",
                    max_values=MAX_ADMIN_ROLES,
                )
        ),
    ]
    if unsaved:
        blocks.append(text_display(uk.nexus_notice(
            "RASCUNHO LOCAL",
            "Aguardando equipe administradora",
            "As escolhas serão gravadas quando ao menos um cargo administrador for definido.",
        )))
    return dashboard.central_shell(payload(
        uk.panel(
            header=[uk.nexus_title(
                "CONFIGURAÇÃO",
                path="MODULES / FARM TICKETS / CONFIG",
                subtitle="Escolha os recursos do servidor. Nada é criado antes da publicação.",
            )],
            blocks=blocks,
            actions=[
                action_row(
                button(
                    custom_id=dashboard.central_custom_id(MODULE_KEY, "review_publish"),
                    label="REVISAR E PUBLICAR",
                    style=1,
                ),
                button(
                    custom_id=dashboard.route_custom_id(MODULE_KEY, "overview"),
                    label="VOLTAR",
                    style=2,
                ),
                ),
                dashboard.route_navigation(MODULE_KEY, "configuration"),
            ],
            footer="NEXUS CORE // SESSION ACTIVE",
            accent_color=COLOR,
        )
    ))


async def _render_system(
    interaction: discord.Interaction,
    api: Any,
    *,
    config: dict[str, Any] | None = None,
) -> None:
    key = _session_key(interaction)
    if config is None:
        _, draft = await _admin_state(api, interaction.guild_id)
        config = _merge(draft, key)
    await _replace_central(
        interaction,
        build_system_payload(config, unsaved=bool(_pending.get(key))),
    )


async def open_system(interaction: discord.Interaction, api: Any) -> None:
    try:
        await _render_system(interaction, api)
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))


async def overview(interaction: discord.Interaction, api: Any) -> None:
    await render_admin(interaction, api)


async def _save_draft(interaction: discord.Interaction, api: Any, config: dict[str, Any]) -> None:
    """Grava o rascunho completo; mantém a seleção em memória quando inválido."""

    key = _session_key(interaction)
    if not _is_persistable(config):
        _pending[key] = dict(config)
        return
    draft = await api.configuration_draft(interaction.guild_id, MODULE_KEY)
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
    _pending.pop(key, None)


async def _apply_patch(
    interaction: discord.Interaction, api: Any, patch: dict[str, Any]
) -> None:
    await _defer_if_needed(interaction)
    key = _session_key(interaction)
    draft = await api.configuration_draft(interaction.guild_id, MODULE_KEY)
    config = _merge(draft, key, patch)
    await _save_draft(interaction, api, config)
    await _render_system(interaction, api, config=config)


async def _set_single(interaction: discord.Interaction, api: Any, field: str) -> None:
    values = _selected_ids(interaction)
    if not values:
        await _send_interaction_error(interaction, "Selecione um valor.")
        return
    try:
        await _apply_patch(interaction, api, {field: values[0]})
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))


async def set_category(interaction: discord.Interaction, api: Any) -> None:
    await _set_single(interaction, api, "category_id")


async def set_panel_channel(interaction: discord.Interaction, api: Any) -> None:
    await _set_single(interaction, api, "panel_channel_id")


async def set_log_channel(interaction: discord.Interaction, api: Any) -> None:
    await _set_single(interaction, api, "log_channel_id")


async def set_admin_roles(interaction: discord.Interaction, api: Any) -> None:
    values = _selected_ids(interaction)
    if not values:
        await _send_interaction_error(
            interaction, "Escolha ao menos um cargo administrador."
        )
        return
    try:
        await _apply_patch(
            interaction, api, {"administrator_role_ids": list(dict.fromkeys(values))}
        )
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))


def build_grants(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Grants exigidos por `_validate_permission_grants` no publish do modulo."""

    grants: list[dict[str, Any]] = [
        {
            "capability": "farm_tickets.open_own",
            "subject_type": "everyone",
            "subject_id": "",
            "scope_type": "guild",
            "scope_id": "",
            "constraints": {},
        }
    ]
    role_ids = list(dict.fromkeys(str(item) for item in config.get("administrator_role_ids") or []))
    grants.extend(
        {
            "capability": capability,
            "subject_type": "role",
            "subject_id": role_id,
            "scope_type": "guild",
            "scope_id": "",
            "constraints": {},
        }
        for capability in ADMIN_CAPABILITIES
        for role_id in role_ids
    )
    return grants


def preflight(guild: discord.Guild, config: dict[str, Any]) -> list[str]:
    errors: list[str] = [
        f"Campo obrigatório ausente: {label}." for label in _missing_fields(config)
    ]
    bot_member = guild.me
    category = (
        guild.get_channel(int(config["category_id"])) if config.get("category_id") else None
    )
    if config.get("category_id") and not isinstance(category, discord.CategoryChannel):
        errors.append("A categoria principal não existe mais neste servidor.")
    for key, label in (
        ("panel_channel_id", "Canal do painel"),
        ("log_channel_id", "Canal de logs"),
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
    if config.get("panel_channel_id") and config["panel_channel_id"] == config.get(
        "log_channel_id"
    ):
        errors.append("O painel e os logs precisam de canais diferentes.")
    for role_id in config.get("administrator_role_ids") or []:
        role = guild.get_role(int(role_id))
        if role is None:
            errors.append(f"Cargo administrador inexistente: {role_id}.")
        elif role.is_default():
            errors.append("@everyone não pode ser cargo administrador de Tickets.")
    if bot_member is not None and not bot_member.guild_permissions.manage_channels:
        errors.append("Bot sem Gerenciar Canais, exigido para criar os canais de ticket.")
    return errors


async def review_publish(interaction: discord.Interaction, api: Any) -> None:
    try:
        await _defer_if_needed(interaction)
        _, draft = await _admin_state(api, interaction.guild_id)
        config = _merge(draft, _session_key(interaction))
        errors = preflight(interaction.guild, config)
        if errors:
            await _send_interaction_error(
                interaction, "Publicação bloqueada:\n- " + "\n- ".join(errors)
            )
            return
        roles = len(config["administrator_role_ids"])
        role_label = "cargo administrador" if roles == 1 else "cargos administradores"
        await _replace_central(
            interaction,
            dashboard.central_shell(payload(
                uk.panel(
                    header=[uk.nexus_title(
                        "REVISAR PUBLICAÇÃO",
                        path="MODULES / FARM TICKETS / PUBLISH",
                        subtitle="Confirme os recursos e permissões que serão ativados.",
                    )],
                    blocks=[
                        text_display(uk.nexus_configuration(
                            ("CATEGORIA", _reference(config["category_id"], kind="channel")),
                            ("PAINEL PÚBLICO", _reference(config["panel_channel_id"], kind="channel")),
                            ("AUDITORIA", _reference(config["log_channel_id"], kind="channel")),
                            ("EQUIPE", _role_summary(config)),
                        )),
                        text_display(uk.nexus_notice(
                            "PUBLICAÇÃO",
                            f"{roles} {role_label}",
                            "Recebem recolhimento, atribuição, aprovação, finalização e exclusão.",
                        )),
                    ],
                    actions=[action_row(
                        button(
                            custom_id=dashboard.central_custom_id(MODULE_KEY, "confirm_publish"),
                            label="CONFIRMAR PUBLICAÇÃO",
                            style=3,
                        ),
                        button(
                            custom_id=dashboard.central_custom_id(MODULE_KEY, "open_system"),
                            label="VOLTAR",
                            style=2,
                        ),
                    ), dashboard.route_navigation(MODULE_KEY, "configuration")],
                    footer="A confirmação cria uma versão imutável e provisiona categoria, canais e painel.\nNEXUS CORE // SESSION ACTIVE",
                    accent_color=COLOR,
                )
            )),
        )
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))


async def confirm_publish(interaction: discord.Interaction, api: Any) -> None:
    try:
        await _defer_if_needed(interaction)
        actor = actor_from(interaction)
        instance, draft = await _admin_state(api, interaction.guild_id)
        config = _merge(draft, _session_key(interaction))
        errors = preflight(interaction.guild, config)
        if errors:
            await _send_interaction_error(
                interaction, "Publicação bloqueada:\n- " + "\n- ".join(errors)
            )
            return
        await _save_draft(interaction, api, config)
        draft = await api.configuration_draft(interaction.guild_id, MODULE_KEY)
        version = await api.publish_configuration(
            interaction.guild_id,
            MODULE_KEY,
            {
                "expected_revision": draft["revision"],
                "expected_published_version": draft["base_published_version"],
                "grants": build_grants(config),
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
            f"Tickets de Farm publicado na versão {version['version']}. "
            "A categoria, os canais e o painel são provisionados pela reconciliação.",
            ephemeral=True,
        )
    except Exception as exc:
        await _send_interaction_error(interaction, error_text(exc))
