from __future__ import annotations

from typing import Any

import discord
import httpx

from yuno_bot.platform import ui_kit as uk
from yuno_bot.platform.components_v2 import action_row, button, payload, separator, string_select, text_display
from yuno_bot.platform.contracts import ComponentsV2Payload, InteractionResult, RoutedContext
from yuno_bot.platform.router import RoutedModal, module_custom_id


MODULE_KEY = "parceria"
CONTRACT_VERSION = 1
_pending_confirm: dict[tuple[int, int], tuple[str, int]] = {}


def _modal_values(interaction: discord.Interaction) -> dict[str, str]:
    values: dict[str, str] = {}
    for row in (interaction.data or {}).get("components") or []:
        for component in row.get("components") or []:
            if component.get("custom_id"):
                values[str(component["custom_id"])] = str(component.get("value") or "")
    return values


def _selected(interaction: discord.Interaction) -> str | None:
    values = list((interaction.data or {}).get("values") or [])
    return str(values[0]) if values else None


def _actor(interaction: discord.Interaction):
    from yuno_bot.domain_modules.parceria.admin import actor_from

    return actor_from(interaction)


def error_text(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            detail = exc.response.json().get("detail", "Operação recusada.")
            if isinstance(detail, dict):
                return str(detail.get("detail") or detail.get("message") or detail)
            return str(detail)
        except Exception:
            return f"A API recusou a operação ({exc.response.status_code})."
    return "Não consegui concluir a operação."


class RegistrationModal(RoutedModal):
    def __init__(self, panel: dict[str, Any]):
        super().__init__(title="Registrar parceria", module_key=MODULE_KEY, surface="global", action_key="submit_registration", panel=panel)
        self.family = discord.ui.TextInput(label="Família", custom_id="family_name", max_length=100)
        self.product = discord.ui.TextInput(label="Produto", custom_id="product_name", max_length=100)
        self.contact_01 = discord.ui.TextInput(label="Contato 1", custom_id="contact_01", required=False, max_length=150)
        self.contact_02 = discord.ui.TextInput(label="Contato 2", custom_id="contact_02", required=False, max_length=150)
        self.add_item(self.family)
        self.add_item(self.product)
        self.add_item(self.contact_01)
        self.add_item(self.contact_02)


class EditModal(RoutedModal):
    def __init__(self, panel: dict[str, Any], parceria_id: str, current: dict[str, Any]):
        super().__init__(title="Editar parceria", module_key=MODULE_KEY, surface="global", action_key="edit_submit", panel={**panel, "resource_id": parceria_id, "publication_revision": current.get("publication_revision")})
        self.parceria_id = parceria_id
        self.expected_revision = int(current.get("publication_revision") or 1)
        self.family = discord.ui.TextInput(label="Família", custom_id="family_name", default=str(current.get("family_name") or ""), max_length=100)
        self.product = discord.ui.TextInput(label="Produto", custom_id="product_name", default=str(current.get("product_name") or ""), max_length=100)
        contacts = list(current.get("contacts") or [])
        self.contact_01 = discord.ui.TextInput(label="Contato 1", custom_id="contact_01", default=contacts[0] if contacts else "", required=False, max_length=150)
        self.contact_02 = discord.ui.TextInput(label="Contato 2", custom_id="contact_02", default=contacts[1] if len(contacts) > 1 else "", required=False, max_length=150)
        for item in (self.family, self.product, self.contact_01, self.contact_02):
            self.add_item(item)


async def render_global(context: dict[str, Any]) -> ComponentsV2Payload:
    config = context.get("config") or {}
    return ComponentsV2Payload(
        payload(
            uk.panel(
                header=uk.heading("Parcerias", emoji="🤝") + "\n\nRegistre e mantenha as parcerias ativas da organização.",
                blocks=[
                    uk.field("Como funciona", "Preencha os dados, envie a imagem neste canal e o Yuno publicará uma mensagem própria para cada parceria."),
                    uk.field("Canal de registro", f"<#{config.get('registrar_channel_id')}>" if config.get("registrar_channel_id") else "Não configurado"),
                ],
                actions=[
                    action_row(
                        button(custom_id=module_custom_id(MODULE_KEY, "global", "register", version=CONTRACT_VERSION), label="Registrar parceria", emoji="➕", style=3),
                        button(custom_id=module_custom_id(MODULE_KEY, "global", "edit", version=CONTRACT_VERSION), label="Editar parceria", emoji="✏️", style=2),
                        button(custom_id=module_custom_id(MODULE_KEY, "global", "deactivate", version=CONTRACT_VERSION), label="Remover parceria", emoji="🗑️", style=4),
                    )
                ],
                footer="As ações são restritas aos cargos gerentes publicados.",
                accent_color=uk.BRAND,
            )
        )
    )


async def register(context: RoutedContext) -> InteractionResult:
    return InteractionResult(modal=RegistrationModal(context.panel))


async def submit_registration(context: RoutedContext) -> InteractionResult:
    values = _modal_values(context.interaction)
    try:
        await context.api.parceria_begin_registration(
            context.interaction.guild.id,
            {
                "family_name": values.get("family_name", ""),
                "product_name": values.get("product_name", ""),
                "contacts": [value for value in (values.get("contact_01"), values.get("contact_02")) if value],
                "channel_id": str(context.interaction.channel_id),
                "idempotency_key": f"parceria-registration:{context.interaction.id}",
            },
            actor=context.actor,
        )
    except Exception as exc:
        return InteractionResult(content=error_text(exc))
    return InteractionResult(content="Dados recebidos. Envie agora uma imagem PNG, JPEG ou WebP neste canal, com até 8 MiB. A sessão expira em cinco minutos.")


def _selection(items: list[dict], action: str) -> ComponentsV2Payload:
    options = [
        {"label": f"{item.get('family_name', 'Parceria')[:90]}", "value": str(item["id"]), "description": str(item.get("product_name") or "")[:100]}
        for item in items[:25]
    ]
    return ComponentsV2Payload(payload({"components": [text_display("Escolha uma parceria para continuar."), separator(), action_row(string_select(custom_id=module_custom_id(MODULE_KEY, "global", action, version=CONTRACT_VERSION), options=options, placeholder="Selecionar parceria"))], "flags": 1 << 15}))


async def edit(context: RoutedContext) -> InteractionResult:
    try:
        items = await context.api.parceria_list(context.interaction.guild.id)
    except Exception as exc:
        return InteractionResult(content=error_text(exc))
    if not items:
        return InteractionResult(content="Não há parcerias cadastradas.")
    return InteractionResult(components_v2=_selection(items, "edit_select"))


async def edit_select(context: RoutedContext) -> InteractionResult:
    parceria_id = _selected(context.interaction)
    if not parceria_id:
        return InteractionResult(content="Seleção inválida.")
    try:
        current = await context.api.parceria_get(context.interaction.guild.id, parceria_id)
    except Exception as exc:
        return InteractionResult(content=error_text(exc))
    return InteractionResult(modal=EditModal(context.panel, parceria_id, current))


async def edit_submit(context: RoutedContext) -> InteractionResult:
    values = _modal_values(context.interaction)
    parceria_id = str(context.panel.get("resource_id") or "")
    try:
        await context.api.parceria_edit(
            context.interaction.guild.id,
            parceria_id,
            {"family_name": values.get("family_name", ""), "product_name": values.get("product_name", ""), "contacts": [value for value in (values.get("contact_01"), values.get("contact_02")) if value], "expected_revision": int(context.panel.get("publication_revision") or 1)},
            actor=context.actor,
        )
    except Exception as exc:
        return InteractionResult(content=error_text(exc))
    return InteractionResult(content="Parceria editada. A publicação pública será atualizada automaticamente.")


async def deactivate(context: RoutedContext) -> InteractionResult:
    try:
        items = await context.api.parceria_list(context.interaction.guild.id)
    except Exception as exc:
        return InteractionResult(content=error_text(exc))
    items = [item for item in items if item.get("status") != "inactive"]
    if not items:
        return InteractionResult(content="Não há parcerias ativas para remover.")
    return InteractionResult(components_v2=_selection(items, "deactivate_select"))


async def deactivate_select(context: RoutedContext) -> InteractionResult:
    parceria_id = _selected(context.interaction)
    if not parceria_id:
        return InteractionResult(content="Seleção inválida.")
    current = await context.api.parceria_get(context.interaction.guild.id, parceria_id)
    _pending_confirm[(context.interaction.guild.id, context.actor.user_id or 0)] = (parceria_id, int(current.get("publication_revision") or 1))
    return InteractionResult(components_v2=ComponentsV2Payload(payload({"components": [text_display(f"Confirme a remoção de **{current.get('family_name', 'parceria')}**. Esta ação encerrará a publicação pública."), separator(), action_row(button(custom_id=module_custom_id(MODULE_KEY, "global", "deactivate_confirm", version=CONTRACT_VERSION), label="Confirmar remoção", emoji="🗑️", style=4), button(custom_id=module_custom_id(MODULE_KEY, "global", "deactivate_cancel", version=CONTRACT_VERSION), label="Cancelar", style=2))], "flags": 1 << 15})))


async def deactivate_confirm(context: RoutedContext) -> InteractionResult:
    key = (context.interaction.guild.id, context.actor.user_id or 0)
    pending = _pending_confirm.pop(key, None)
    if pending is None:
        return InteractionResult(content="A confirmação expirou. Selecione a parceria novamente.")
    parceria_id, revision = pending
    try:
        await context.api.parceria_deactivate(context.interaction.guild.id, parceria_id, revision, actor=context.actor)
    except Exception as exc:
        return InteractionResult(content=error_text(exc))
    return InteractionResult(content="Parceria removida e publicação encerrada.")


async def deactivate_cancel(context: RoutedContext) -> InteractionResult:
    _pending_confirm.pop((context.interaction.guild.id, context.actor.user_id or 0), None)
    return InteractionResult(content="Remoção cancelada.")
