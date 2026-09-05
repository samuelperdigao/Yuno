"""Funções puras do módulo de entrada/saída de membros.

Nada aqui faz I/O: `runtime.py` busca os dados no Discord e na API, monta os
tipos abaixo e só então chama estas funções. Isso deixa a lógica de negócio
(idade da conta, duração no servidor, causa da saída) testável sem mockar
`discord.Client`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional

NEW_ACCOUNT_THRESHOLD_DAYS = 7
LEAVE_CAUSE_WINDOW_SECONDS = 10


@dataclass(frozen=True)
class JoinSnapshot:
    member_id: int
    member_mention: str
    display_name: str
    account_created_at: datetime
    joined_at: datetime
    member_count: int


@dataclass(frozen=True)
class LeaveCause:
    """Resultado da investigação do log de auditoria.

    `kind` distingue "unknown" (não deu para checar o audit log — sem
    permissão) de "voluntary" (checou e não achou kick/ban recente): os dois
    parecem "sem causa" à primeira vista, mas têm significado bem diferente
    para quem lê o log.
    """

    kind: str  # "voluntary" | "kicked" | "banned" | "unknown"
    moderator_id: Optional[int] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class LeaveSnapshot:
    member_id: int
    display_name: str
    joined_at: Optional[datetime]
    left_at: datetime
    role_mentions: tuple[str, ...]
    cause: LeaveCause
    extra_message: str = ""


@dataclass(frozen=True)
class AuditCandidate:
    action: str  # "kick" | "ban"
    target_id: int
    moderator_id: Optional[int]
    created_at: datetime
    reason: Optional[str]


def is_new_account(
    created_at: datetime, *, now: datetime, threshold_days: int = NEW_ACCOUNT_THRESHOLD_DAYS
) -> bool:
    return (now - created_at) < timedelta(days=threshold_days)


def _plural(value: int, singular: str) -> str:
    return f"{value} {singular}" if value == 1 else f"{value} {singular}s"


def format_duration(delta: timedelta) -> str:
    """Formata em dias/horas/minutos, ou anos+dias quando for muito longo."""

    total_seconds = max(int(delta.total_seconds()), 0)
    days, remainder = divmod(total_seconds, 86400)
    if days >= 365:
        years, remaining_days = divmod(days, 365)
        parts = [_plural(years, "ano")]
        if remaining_days:
            parts.append(_plural(remaining_days, "dia"))
        return " e ".join(parts)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    parts: list[str] = []
    if days:
        parts.append(_plural(days, "dia"))
    if hours:
        parts.append(_plural(hours, "hora"))
    if minutes or not parts:
        parts.append(_plural(minutes, "minuto"))
    return ", ".join(parts)


def detect_leave_cause(
    candidates: Iterable[AuditCandidate],
    *,
    member_id: int,
    left_at: datetime,
    window_seconds: int = LEAVE_CAUSE_WINDOW_SECONDS,
) -> LeaveCause:
    """Casa o membro que saiu com um kick/ban recente do audit log.

    Só aceita entradas criadas até `window_seconds` antes da saída: o mesmo
    critério do bot pessoal que inspirou este módulo, usado para diferenciar
    "saiu por conta própria" de "foi expulso/banido" sem depender de nenhum
    evento explícito do Discord para kick (que não existe).
    """

    matches = [
        candidate
        for candidate in candidates
        if candidate.target_id == member_id
        and timedelta(0) <= (left_at - candidate.created_at) <= timedelta(seconds=window_seconds)
    ]
    if not matches:
        return LeaveCause(kind="voluntary")
    best = max(matches, key=lambda item: item.created_at)
    kind = "banned" if best.action == "ban" else "kicked"
    return LeaveCause(kind=kind, moderator_id=best.moderator_id, reason=best.reason)
