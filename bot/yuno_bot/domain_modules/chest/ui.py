from __future__ import annotations

from decimal import Decimal
from math import ceil
from typing import Any

import discord
import httpx

from yuno_bot.platform import ui_kit as uk
from yuno_bot.platform.components_v2 import (
    action_row,
    button,
    payload,
    string_select,
    text_display,
)
from yuno_bot.platform.contracts import (
    ComponentsV2Payload,
    InteractionResult,
    RoutedContext,
)
from yuno_bot.platform.router import RoutedModal, module_custom_id

MODULE_KEY = "chest"
CONTRACT_VERSION = 1
PAGE_SIZE = 23
_sessions: dict[tuple[int, int], dict[str, Any]] = {}
_pending: dict[tuple[int, int, str], dict[str, Any]] = {}


def _key(context: RoutedContext) -> tuple[int, int]:
    return (context.interaction.guild.id, context.actor.user_id or 0)


def _selected(interaction: discord.Interaction) -> str | None:
    values = list((interaction.data or {}).get("values") or [])
    return str(values[0]) if values else None


def _modal_values(interaction: discord.Interaction) -> dict[str, str]:
    values: dict[str, str] = {}

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            custom_id = node.get("custom_id")
            if custom_id and "value" in node:
                values[str(custom_id)] = str(node.get("value") or "")
            for child in node.get("components") or []:
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit((interaction.data or {}).get("components") or [])
    return values


def _error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            detail = exc.response.json().get("detail")
            if isinstance(detail, dict):
                return str(detail.get("detail") or "Operacao recusada.")
            if detail:
                return str(detail)
        except Exception:
            pass
    return "Nao foi possivel concluir a acao do Sistema de Bau. Tente novamente."


def _v2(title: str, body: str, *actions: dict[str, Any]) -> ComponentsV2Payload:
    return ComponentsV2Payload(
        payload(
            uk.panel(
                header=[
                    uk.nexus_title(
                        title,
                        path="MODULES / CHEST",
                        subtitle="Experiencia privada e autorizada.",
                    )
                ],
                blocks=[text_display(body)],
                actions=list(actions),
                footer="YUNO NEXUS // CHEST RUNTIME",
                accent_color=uk.NEXUS_VIOLET,
            )
        )
    )


async def render_global(context: dict[str, Any]) -> ComponentsV2Payload:
    config = context.get("config") or {}
    return ComponentsV2Payload(
        payload(
            uk.panel(
                header=[
                    uk.nexus_title(
                        config.get("panel_title") or "SISTEMA DE BAU",
                        path="RUNTIME / CHEST",
                        subtitle=config.get("panel_description")
                        or "Estoque operacional da organizacao.",
                    )
                ],
                blocks=[
                    text_display(
                        uk.nexus_notice(
                            "OPERACAO",
                            "Acesso pessoal",
                            "Selecione um bau para consultar ou registrar uma movimentacao. O painel publico permanece estavel.",
                        )
                    )
                ],
                actions=[
                    action_row(
                        button(
                            custom_id=module_custom_id(
                                MODULE_KEY,
                                "global",
                                "select_chest",
                                version=CONTRACT_VERSION,
                            ),
                            label="SELECIONAR BAU",
                            style=1,
                        ),
                        button(
                            custom_id=module_custom_id(
                                MODULE_KEY,
                                "global",
                                "history_own",
                                version=CONTRACT_VERSION,
                            ),
                            label="MEU HISTORICO",
                            style=2,
                        ),
                    )
                ],
                footer="As permissoes sao revalidadas em cada acao.",
                accent_color=uk.NEXUS_VIOLET,
            )
        )
    )


async def _chest_page(context: RoutedContext, page_index: int) -> InteractionResult:
    try:
        catalog = await context.api.chest_catalog(
            context.interaction.guild.id, actor=context.actor
        )
    except Exception as exc:
        return InteractionResult(content=_error(exc))
    chests = list(catalog.get("chests") or [])
    if not chests:
        return InteractionResult(
            content="Voce nao possui acesso a nenhum bau publicado."
        )
    pages = max(1, ceil(len(chests) / PAGE_SIZE))
    page_index = min(max(0, page_index), pages - 1)
    _sessions.setdefault(_key(context), {})["chest_page"] = page_index
    chunk = chests[page_index * PAGE_SIZE : (page_index + 1) * PAGE_SIZE]
    select = action_row(
        string_select(
            custom_id=module_custom_id(MODULE_KEY, "global", "choose_chest"),
            options=[
                {"label": item["name"][:100], "value": item["id"]} for item in chunk
            ],
            placeholder=f"Selecionar bau - pagina {page_index + 1}/{pages}",
        )
    )
    navigation = action_row(
        button(
            custom_id=module_custom_id(MODULE_KEY, "global", "chests_prev"),
            label="VOLTAR",
            style=2,
            disabled=page_index == 0,
        ),
        button(
            custom_id=module_custom_id(MODULE_KEY, "global", "chests_next"),
            label="AVANCAR",
            style=2,
            disabled=page_index + 1 >= pages,
        ),
    )
    return InteractionResult(
        components_v2=_v2(
            "SELECIONAR BAU",
            uk.nexus_metrics(
                ("AUTORIZADOS", len(chests)), ("PAGINA", f"{page_index + 1}/{pages}")
            ),
            select,
            navigation,
        )
    )


async def select_chest(context: RoutedContext) -> InteractionResult:
    return await _chest_page(context, 0)


async def chests_prev(context: RoutedContext) -> InteractionResult:
    return await _chest_page(
        context, int(_sessions.get(_key(context), {}).get("chest_page", 0)) - 1
    )


async def chests_next(context: RoutedContext) -> InteractionResult:
    return await _chest_page(
        context, int(_sessions.get(_key(context), {}).get("chest_page", 0)) + 1
    )


async def choose_chest(context: RoutedContext) -> InteractionResult:
    chest_id = _selected(context.interaction)
    if not chest_id:
        return InteractionResult(content="Selecao invalida.")
    try:
        stock_data = await context.api.chest_stock(
            context.interaction.guild.id, chest_id, actor=context.actor
        )
    except Exception as exc:
        return InteractionResult(content=_error(exc))
    session = _sessions.setdefault(_key(context), {})
    session["chest_id"] = chest_id
    session["chest_name"] = stock_data["chest"]["name"]
    return InteractionResult(
        components_v2=_v2(
            stock_data["chest"]["name"].upper(),
            uk.nexus_metrics(
                ("ITENS", len(stock_data.get("items") or [])),
                ("SALDO", "VISIVEL" if stock_data.get("show_balances") else "RESTRITO"),
            ),
            action_row(
                button(
                    custom_id=module_custom_id(MODULE_KEY, "global", "view_stock"),
                    label="VER ESTOQUE",
                    style=2,
                ),
                button(
                    custom_id=module_custom_id(MODULE_KEY, "global", "deposit"),
                    label="DEPOSITAR",
                    style=3,
                ),
                button(
                    custom_id=module_custom_id(MODULE_KEY, "global", "withdraw"),
                    label="RETIRAR",
                    style=1,
                ),
            ),
            action_row(
                button(
                    custom_id=module_custom_id(MODULE_KEY, "global", "select_chest"),
                    label="TROCAR BAU",
                    style=2,
                )
            ),
        )
    )


async def view_stock(context: RoutedContext) -> InteractionResult:
    chest_id = str(_sessions.get(_key(context), {}).get("chest_id") or "")
    if not chest_id:
        return await select_chest(context)
    try:
        data = await context.api.chest_stock(
            context.interaction.guild.id, chest_id, actor=context.actor
        )
    except Exception as exc:
        return InteractionResult(content=_error(exc))
    lines = []
    for item in data.get("items") or []:
        amount = (
            f"{item['quantity']} {item['unit']}"
            if item.get("quantity") is not None
            else "quantidade restrita"
        )
        lines.append(f"**{item['name']}** — {amount}")
    return InteractionResult(
        components_v2=_v2(
            data["chest"]["name"].upper(),
            "\n".join(lines) or "Nenhum item publicado neste bau.",
            action_row(
                button(
                    custom_id=module_custom_id(MODULE_KEY, "global", "select_chest"),
                    label="VOLTAR",
                    style=2,
                ),
                button(
                    custom_id=module_custom_id(MODULE_KEY, "global", "deposit"),
                    label="DEPOSITAR",
                    style=3,
                ),
                button(
                    custom_id=module_custom_id(MODULE_KEY, "global", "withdraw"),
                    label="RETIRAR",
                    style=1,
                ),
            ),
        )
    )


async def _item_page(
    context: RoutedContext, mode: str, page_index: int
) -> InteractionResult:
    session = _sessions.get(_key(context), {})
    chest_id = str(session.get("chest_id") or "")
    if not chest_id:
        return await select_chest(context)
    try:
        data = await context.api.chest_stock(
            context.interaction.guild.id, chest_id, actor=context.actor
        )
    except Exception as exc:
        return InteractionResult(content=_error(exc))
    items = list(data.get("items") or [])
    session["withdrawal_reason_required"] = data.get("withdrawal_reason_required", True)
    pages = max(1, ceil(len(items) / PAGE_SIZE))
    page_index = min(max(0, page_index), pages - 1)
    session[f"{mode}_page"] = page_index
    chunk = items[page_index * PAGE_SIZE : (page_index + 1) * PAGE_SIZE]
    if not chunk:
        return InteractionResult(content="Este bau nao possui itens publicados.")
    options = []
    for item in chunk:
        description = item.get("unit") or "unidade"
        if mode == "withdraw" and item.get("quantity") is not None:
            description = f"Disponivel: {item['quantity']} {description}"
        options.append(
            {
                "label": item["name"][:100],
                "value": item["id"],
                "description": description[:100],
            }
        )
    return InteractionResult(
        components_v2=_v2(
            "DEPOSITAR" if mode == "deposit" else "RETIRAR",
            f"Bau: **{data['chest']['name']}**\nSelecione o item. Pagina {page_index + 1}/{pages}.",
            action_row(
                string_select(
                    custom_id=module_custom_id(MODULE_KEY, "global", f"{mode}_item"),
                    options=options,
                    placeholder="Selecionar item",
                )
            ),
            action_row(
                button(
                    custom_id=module_custom_id(MODULE_KEY, "global", f"{mode}_prev"),
                    label="VOLTAR",
                    style=2,
                    disabled=page_index == 0,
                ),
                button(
                    custom_id=module_custom_id(MODULE_KEY, "global", f"{mode}_next"),
                    label="AVANCAR",
                    style=2,
                    disabled=page_index + 1 >= pages,
                ),
            ),
        )
    )


async def deposit(context: RoutedContext) -> InteractionResult:
    return await _item_page(context, "deposit", 0)


async def withdraw(context: RoutedContext) -> InteractionResult:
    return await _item_page(context, "withdraw", 0)


async def deposit_prev(context: RoutedContext) -> InteractionResult:
    return await _item_page(
        context,
        "deposit",
        int(_sessions.get(_key(context), {}).get("deposit_page", 0)) - 1,
    )


async def deposit_next(context: RoutedContext) -> InteractionResult:
    return await _item_page(
        context,
        "deposit",
        int(_sessions.get(_key(context), {}).get("deposit_page", 0)) + 1,
    )


async def withdraw_prev(context: RoutedContext) -> InteractionResult:
    return await _item_page(
        context,
        "withdraw",
        int(_sessions.get(_key(context), {}).get("withdraw_page", 0)) - 1,
    )


async def withdraw_next(context: RoutedContext) -> InteractionResult:
    return await _item_page(
        context,
        "withdraw",
        int(_sessions.get(_key(context), {}).get("withdraw_page", 0)) + 1,
    )


class MovementModal(RoutedModal):
    def __init__(self, *, context: RoutedContext, mode: str, item_id: str) -> None:
        super().__init__(
            title="Depositar item" if mode == "deposit" else "Retirar item",
            module_key=MODULE_KEY,
            surface="global",
            action_key=f"{mode}_submit",
            panel={
                **context.panel,
                "chest_id": _sessions[_key(context)]["chest_id"],
                "item_id": item_id,
            },
            timeout=600,
        )
        self.amount = discord.ui.TextInput(
            label="Quantidade",
            custom_id="quantity",
            placeholder="1",
            min_length=1,
            max_length=24,
        )
        self.observation = discord.ui.TextInput(
            label="Observacao" if mode == "deposit" else "Motivo",
            custom_id="observation",
            required=mode == "withdraw"
            and bool(_sessions[_key(context)].get("withdrawal_reason_required", True)),
            max_length=500,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.amount)
        self.add_item(self.observation)


async def deposit_item(context: RoutedContext) -> InteractionResult:
    item_id = _selected(context.interaction)
    return (
        InteractionResult(
            modal=MovementModal(context=context, mode="deposit", item_id=item_id)
        )
        if item_id
        else InteractionResult(content="Selecao invalida.")
    )


async def withdraw_item(context: RoutedContext) -> InteractionResult:
    item_id = _selected(context.interaction)
    return (
        InteractionResult(
            modal=MovementModal(context=context, mode="withdraw", item_id=item_id)
        )
        if item_id
        else InteractionResult(content="Selecao invalida.")
    )


async def _submit(context: RoutedContext, mode: str) -> InteractionResult:
    values = _modal_values(context.interaction)
    try:
        amount = Decimal(values.get("quantity") or "")
        if amount <= 0:
            raise ValueError
    except Exception:
        return InteractionResult(content="Informe uma quantidade positiva valida.")
    key = (context.interaction.guild.id, context.actor.user_id or 0, mode)
    _pending[key] = {
        "chest_id": str(context.panel.get("chest_id") or ""),
        "item_id": str(context.panel.get("item_id") or ""),
        "quantity": str(amount),
        "observation": values.get("observation") or None,
        "idempotency_key": f"chest:{mode}:{context.interaction.id}",
    }
    label = "deposito" if mode == "deposit" else "retirada"
    return InteractionResult(
        components_v2=_v2(
            "CONFIRMAR MOVIMENTACAO",
            f"Confirme o {label} de **{amount}**. O ledger sera permanente.",
            action_row(
                button(
                    custom_id=module_custom_id(MODULE_KEY, "global", f"{mode}_confirm"),
                    label="CONFIRMAR",
                    style=3 if mode == "deposit" else 1,
                ),
                button(
                    custom_id=module_custom_id(MODULE_KEY, "global", f"{mode}_cancel"),
                    label="CANCELAR",
                    style=2,
                ),
            ),
        )
    )


async def deposit_submit(context: RoutedContext) -> InteractionResult:
    return await _submit(context, "deposit")


async def withdraw_submit(context: RoutedContext) -> InteractionResult:
    return await _submit(context, "withdraw")


async def _confirm(context: RoutedContext, mode: str) -> InteractionResult:
    pending = _pending.pop(
        (context.interaction.guild.id, context.actor.user_id or 0, mode), None
    )
    if pending is None:
        return InteractionResult(
            content="A confirmacao expirou. Inicie a movimentacao novamente."
        )
    try:
        result = await context.api.chest_move(
            context.interaction.guild.id,
            {
                **pending,
                "movement_type": "DEPOSIT" if mode == "deposit" else "WITHDRAWAL",
                "origin": "discord",
            },
            actor=context.actor,
        )
    except Exception as exc:
        return InteractionResult(content=_error(exc))
    return InteractionResult(
        content=f"Movimentacao registrada. Saldo atual: {result['balance_after']} {result['unit']} (sequencia {result['sequence']})."
    )


async def deposit_confirm(context: RoutedContext) -> InteractionResult:
    return await _confirm(context, "deposit")


async def withdraw_confirm(context: RoutedContext) -> InteractionResult:
    return await _confirm(context, "withdraw")


async def deposit_cancel(context: RoutedContext) -> InteractionResult:
    _pending.pop(
        (context.interaction.guild.id, context.actor.user_id or 0, "deposit"), None
    )
    return InteractionResult(content="Deposito cancelado.")


async def withdraw_cancel(context: RoutedContext) -> InteractionResult:
    _pending.pop(
        (context.interaction.guild.id, context.actor.user_id or 0, "withdraw"), None
    )
    return InteractionResult(content="Retirada cancelada.")


async def history_own(context: RoutedContext) -> InteractionResult:
    try:
        rows = await context.api.chest_history(
            context.interaction.guild.id,
            {"actor_id": str(context.actor.user_id), "limit": 20},
            actor=context.actor,
        )
    except Exception as exc:
        return InteractionResult(content=_error(exc))
    lines = [
        f"**{row['movement_type']}** · {row['quantity']} {row['unit']} · {row['chest_name']} / {row['item_name']}"
        for row in rows
    ]
    return InteractionResult(
        components_v2=_v2(
            "MEU HISTORICO", "\n".join(lines) or "Nenhuma movimentacao encontrada."
        )
    )


async def own_history_owner(
    interaction: discord.Interaction, panel: dict[str, Any], api: Any
) -> str | None:
    del panel, api
    return str(interaction.user.id) if interaction.user else None
