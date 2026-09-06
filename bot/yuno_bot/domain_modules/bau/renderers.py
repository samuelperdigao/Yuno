from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import discord

from yuno_bot.platform import ui_kit as uk

LOG_COLOR = uk.BRAND
CLEAR_COLOR = uk.DANGER


def _safe_text(value: Any, *, limit: int = 1024) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = discord.utils.escape_mentions(text)
    text = discord.utils.escape_markdown(text)
    return text[:limit]


def _user_mention(user_id: str | None) -> str:
    value = str(user_id or "").strip()
    return f"<@{value}>" if value.isascii() and value.isdigit() else ""


@dataclass(frozen=True, slots=True)
class BauLogData:
    operation: str = "movimentacao"
    actor_id: str | None = None
    changes: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    items_reset: int = 0
    log_title: str = "Movimentação no Baú"

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "BauLogData":
        data = payload or {}
        return cls(
            operation=str(data.get("operation") or "movimentacao"),
            actor_id=data.get("actor_id"),
            changes=tuple(data.get("changes") or ()),
            items_reset=int(data.get("items_reset") or 0),
            log_title=str(data.get("log_title") or "Movimentação no Baú"),
        )


class BauRenderer:
    """Formata snapshots resolvidos do Baú, sem consultar domínio ou Discord."""

    def render_log(self, data: BauLogData) -> discord.Embed:
        if data.operation == "limpeza":
            return self._render_clear(data)
        return self._render_movement(data)

    def _render_movement(self, data: BauLogData) -> discord.Embed:
        embed = discord.Embed(
            title=_safe_text(data.log_title, limit=256),
            description="Uma movimentação de estoque foi registrada.",
            color=LOG_COLOR,
        )
        actor = _user_mention(data.actor_id)
        if actor:
            embed.add_field(name="👤 Responsável", value=actor, inline=False)
        lines = []
        for change in data.changes[:20]:
            name = _safe_text(change.get("item_name"), limit=100) or "Item"
            delta = int(change.get("delta") or 0)
            before = int(change.get("before") or 0)
            after = int(change.get("after") or 0)
            sign = "+" if delta > 0 else ""
            lines.append(f"**{name}** — {sign}{delta} ({before} → {after})")
        if lines:
            embed.add_field(name="📦 Itens", value="\n".join(lines), inline=False)
        if len(data.changes) > 20:
            embed.add_field(
                name="…", value=f"e mais {len(data.changes) - 20} item(ns).", inline=False
            )
        return embed

    def _render_clear(self, data: BauLogData) -> discord.Embed:
        embed = discord.Embed(
            title=_safe_text(data.log_title, limit=256),
            description="O estoque do Baú foi zerado.",
            color=CLEAR_COLOR,
        )
        actor = _user_mention(data.actor_id)
        if actor:
            embed.add_field(name="👤 Responsável", value=actor, inline=False)
        embed.add_field(name="🧹 Itens zerados", value=str(data.items_reset), inline=False)
        return embed
