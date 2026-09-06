from __future__ import annotations

from typing import Any

import discord
import httpx

from yuno_bot import dashboard
from yuno_bot.platform import ui_kit as uk
from yuno_bot.platform.components_v2 import action_row, button, channel_select, edit_message, payload, role_select, separator, text_display
from yuno_bot.platform.contracts import ActorContext
from yuno_bot.platform.panels import PanelPublisher


MODULE_KEY = "parceria"
EMPTY = {"registrar_channel_id": "", "ativas_channel_id": "", "manager_role_ids": [], "category_id": "", "log_channel_id": ""}
MANAGER_CAPABILITIES = ("parceria.register", "parceria.edit", "parceria.deactivate")


def actor_from(interaction: discord.Interaction) -> ActorContext:
    member = interaction.user if isinstance(interaction.user, discord.Member) else None
    return ActorContext(
        guild_id=int(interaction.guild_id or 0),
        user_id=interaction.user.id if interaction.user else None,
        role_ids=tuple(role.id for role in member.roles) if member else (),
        discord_permissions=tuple(name for name, enabled in member.guild_permissions if enabled) if member else (),
        channel_id=interaction.channel_id,
        category_id=getattr(interaction.channel, "category_id", None),
        actor_type="user",
        is_guild_owner=bool(interaction.guild and interaction.user and interaction.guild.owner_id == interaction.user.id),
        correlation_id=str(interaction.id),
    )


def _selected(interaction: discord.Interaction) -> list[str]:
    return [str(value) for value in ((interaction.data or {}).get("values") or [])]


def _actor_payload(interaction: discord.Interaction) -> ActorContext:
    return actor_from(interaction)


def _grants(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "capability": capability,
            "subject_type": "role",
            "subject_id": str(role_id),
            "scope_type": "guild",
            "scope_id": "",
            "constraints": {},
        }
        for capability in MANAGER_CAPABILITIES
        for role_id in config.get("manager_role_ids") or []
    ]


def _merge(draft: dict) -> dict[str, Any]:
    return {**EMPTY, **(draft.get("data") or {})}


def _ref(value: Any, kind: str = "channel") -> str:
    value = str(value or "").strip()
    if not value:
        return "Ainda não definido"
    return f"<#{value}>" if kind == "channel" else f"<@&{value}>"


def _config_text(config: dict[str, Any]) -> str:
    roles = ", ".join(_ref(role, "role") for role in config.get("manager_role_ids") or []) or "Ainda não definido"
    return (
        f"**Registro:** {_ref(config.get('registrar_channel_id'))}\n"
        f"**Parcerias ativas:** {_ref(config.get('ativas_channel_id'))}\n"
        f"**Cargos gerentes:** {roles}\n"
        f"**Categoria:** {_ref(config.get('category_id'))}\n"
        f"**Logs:** {_ref(config.get('log_channel_id'))}"
    )


async def _replace(interaction: discord.Interaction, data: dict[str, Any]) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer()
    await edit_message(interaction.client, interaction.channel_id, interaction.message.id, data)


def build_admin_payload(instance: dict, draft: dict) -> dict[str, Any]:
    config = _merge(draft)
    published = bool(instance.get("published_config_version_id"))
    active = published and instance.get("lifecycle") == "active"
    state = uk.State.APPROVED if active else (uk.State.RUNNING if published else uk.State.PENDING)
    status = "Ativo" if active else ("Publicado, mas inativo" if published else "Aguardando publicação")
    return payload(
        uk.panel(
            header=[
                dashboard.module_navigation(MODULE_KEY),
                uk.space(),
                uk.heading("Parcerias", emoji="🤝"),
            ],
            blocks=[
                uk.field("Estado", f"{uk.badge(state, status, bold=True)}\nA configuração publicada é a única consumida pelo Runtime."),
                uk.rule(),
                uk.field("Configuração", _config_text(config), emoji="🧭"),
            ],
            actions=[action_row(button(custom_id=dashboard.central_custom_id(MODULE_KEY, "open_system"), label="Configurar Parcerias", emoji="⚙️", style=2))],
            state=state,
        )
    )


async def render_admin(interaction: discord.Interaction, api: Any) -> None:
    instance = await api.module_instance(interaction.guild_id, MODULE_KEY)
    draft = await api.configuration_draft(interaction.guild_id, MODULE_KEY)
    await _replace(interaction, build_admin_payload(instance, draft))


async def open_system(interaction: discord.Interaction, api: Any) -> None:
    draft = await api.configuration_draft(interaction.guild_id, MODULE_KEY)
    config = _merge(draft)
    components = [
        dashboard.module_navigation(MODULE_KEY), separator(),
        text_display("# 🤝 Parcerias\n\nEscolha a estrutura existente. As alterações ficam em rascunho até a publicação."),
        separator(), text_display(_config_text(config)),
        action_row(channel_select(custom_id=dashboard.central_custom_id(MODULE_KEY, "set_registrar_channel"), placeholder="Canal para receber cadastros", channel_types=[0])),
        action_row(channel_select(custom_id=dashboard.central_custom_id(MODULE_KEY, "set_ativas_channel"), placeholder="Canal das parcerias ativas", channel_types=[0])),
        action_row(role_select(custom_id=dashboard.central_custom_id(MODULE_KEY, "set_manager_roles"), placeholder="Cargos gerentes", min_values=1, max_values=25)),
        action_row(channel_select(custom_id=dashboard.central_custom_id(MODULE_KEY, "set_category"), placeholder="Categoria opcional", channel_types=[4])),
        action_row(channel_select(custom_id=dashboard.central_custom_id(MODULE_KEY, "set_log_channel"), placeholder="Canal de logs opcional", channel_types=[0])),
        separator(),
        action_row(
            button(custom_id=dashboard.central_custom_id(MODULE_KEY, "review_publish"), label="Revisar e publicar", emoji="👁️", style=1),
            button(custom_id=dashboard.central_custom_id(MODULE_KEY, "diagnose"), label="Diagnosticar", emoji="🩺", style=2),
            button(custom_id=dashboard.central_custom_id(MODULE_KEY, "recover_panel"), label="Recuperar painel", emoji="♻️", style=2),
        ),
    ]
    await _replace(interaction, {"components": components, "flags": 1 << 15})


async def _save_selection(interaction: discord.Interaction, api: Any, key: str, values: list[str]) -> None:
    draft = await api.configuration_draft(interaction.guild_id, MODULE_KEY)
    config = _merge(draft)
    config[key] = values if key == "manager_role_ids" else (values[0] if values else "")
    actor = actor_from(interaction)
    await api.save_configuration_draft(interaction.guild_id, MODULE_KEY, {"expected_revision": draft["revision"], "expected_published_version": draft["base_published_version"], "schema_version": draft["schema_version"], "data": config}, actor=actor)
    await open_system(interaction, api)


async def set_registrar_channel(interaction: discord.Interaction, api: Any) -> None:
    await _save_selection(interaction, api, "registrar_channel_id", _selected(interaction))


async def set_ativas_channel(interaction: discord.Interaction, api: Any) -> None:
    await _save_selection(interaction, api, "ativas_channel_id", _selected(interaction))


async def set_manager_roles(interaction: discord.Interaction, api: Any) -> None:
    await _save_selection(interaction, api, "manager_role_ids", _selected(interaction))


async def set_category(interaction: discord.Interaction, api: Any) -> None:
    await _save_selection(interaction, api, "category_id", _selected(interaction))


async def set_log_channel(interaction: discord.Interaction, api: Any) -> None:
    await _save_selection(interaction, api, "log_channel_id", _selected(interaction))


async def review_publish(interaction: discord.Interaction, api: Any) -> None:
    draft = await api.configuration_draft(interaction.guild_id, MODULE_KEY)
    config = _merge(draft)
    missing = [key for key in ("registrar_channel_id", "ativas_channel_id", "manager_role_ids") if not config.get(key)]
    text = "# Revisão de Parcerias\n\n" + _config_text(config)
    if missing:
        text += "\n\n⚠️ Faltam campos obrigatórios: " + ", ".join(missing)
    else:
        text += "\n\n✅ Pronto para publicar. A publicação ativará o painel e o Runtime domain-first."
    components = [dashboard.module_navigation(MODULE_KEY), separator(), text_display(text), separator(), action_row(button(custom_id=dashboard.central_custom_id(MODULE_KEY, "confirm_publish"), label="Publicar configuração", emoji="🚀", style=1), button(custom_id=dashboard.central_custom_id(MODULE_KEY, "open_system"), label="Voltar", style=2))]
    await _replace(interaction, {"components": components, "flags": 1 << 15})


async def confirm_publish(interaction: discord.Interaction, api: Any) -> None:
    draft = await api.configuration_draft(interaction.guild_id, MODULE_KEY)
    actor = actor_from(interaction)
    await api.publish_configuration(interaction.guild_id, MODULE_KEY, {"expected_revision": draft["revision"], "expected_published_version": draft["base_published_version"], "grants": _grants(_merge(draft))}, actor=actor)
    instance = await api.module_instance(interaction.guild_id, MODULE_KEY)
    await api.update_lifecycle(interaction.guild_id, MODULE_KEY, lifecycle="active", expected_lifecycle=instance["lifecycle"], actor=actor, reason="config_published")
    await render_admin(interaction, api)


async def diagnose(interaction: discord.Interaction, api: Any) -> None:
    checks = await api.diagnostics(interaction.guild_id, MODULE_KEY)
    lines = [f"**{item.get('status', 'UNKNOWN')}** · {item.get('summary', '')}" for item in checks]
    await _replace(interaction, {"components": [dashboard.module_navigation(MODULE_KEY), separator(), text_display("# 🩺 Diagnóstico\n\n" + "\n".join(lines) if lines else "Nenhuma pendência encontrada.")], "flags": 1 << 15})


async def recover_panel(interaction: discord.Interaction, api: Any) -> None:
    from yuno_bot.domain_modules.parceria.runtime import recover_panel as do_recover

    await do_recover(interaction.client, api, interaction.guild)
    await render_admin(interaction, api)
