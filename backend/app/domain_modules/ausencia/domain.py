from __future__ import annotations

from datetime import datetime, timedelta

# Extraido do farm legado (MDM): acima disso o afastamento passa a ser tratado
# como abandono manual pela staff, nao mais um aviso automatico do painel.
NEAR_LIMIT_THRESHOLD_DAYS = 3
MAX_REASON_LENGTH = 300


class AusenciaDomainError(ValueError):
    pass


def validate_days(days: int, *, max_days: int) -> int:
    if not isinstance(days, int) or isinstance(days, bool):
        raise AusenciaDomainError("A quantidade de dias deve ser um numero inteiro.")
    if days < 1:
        raise AusenciaDomainError("A ausencia precisa durar pelo menos 1 dia.")
    if days > max_days:
        raise AusenciaDomainError(
            f"Ausencias acima de {max_days} dia(s) nao sao permitidas por aqui. "
            "Isso e tratado como PD automatico pela staff — fale com a equipe "
            "antes de se ausentar por mais tempo."
        )
    return days


def normalize_reason(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > MAX_REASON_LENGTH:
        raise AusenciaDomainError(
            f"O motivo deve ter no maximo {MAX_REASON_LENGTH} caracteres."
        )
    return text


def is_near_limit(days: int) -> bool:
    return days > NEAR_LIMIT_THRESHOLD_DAYS


def compute_window(days: int, *, now: datetime) -> tuple[datetime, datetime]:
    if now.tzinfo is None:
        raise AusenciaDomainError("now precisa incluir timezone.")
    return now, now + timedelta(days=days)
