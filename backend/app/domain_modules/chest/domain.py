from __future__ import annotations

import unicodedata
from decimal import Decimal, InvalidOperation
from enum import Enum


class MovementType(str, Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    ADJUSTMENT_CREDIT = "ADJUSTMENT_CREDIT"
    ADJUSTMENT_DEBIT = "ADJUSTMENT_DEBIT"


CREDIT_TYPES = frozenset({MovementType.DEPOSIT, MovementType.ADJUSTMENT_CREDIT})
DEBIT_TYPES = frozenset({MovementType.WITHDRAWAL, MovementType.ADJUSTMENT_DEBIT})
QUANTITY_SCALE = Decimal("0.001")
QUANTITY_MAX = Decimal("99999999999999999.999")


class ChestDomainError(ValueError):
    pass


class InsufficientBalance(ChestDomainError):
    pass


def compact_text(value: str, *, field: str = "texto", max_length: int = 120) -> str:
    result = " ".join(str(value).strip().split())
    if not result:
        raise ChestDomainError(f"{field} nao pode ficar vazio.")
    if len(result) > max_length:
        raise ChestDomainError(f"{field} excede {max_length} caracteres.")
    return result


def normalize_name(value: str) -> str:
    compacted = compact_text(value, field="nome")
    decomposed = unicodedata.normalize("NFKD", compacted)
    return "".join(
        char for char in decomposed if not unicodedata.combining(char)
    ).casefold()


def quantity(value: Decimal | int | str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ChestDomainError("Quantidade invalida.") from exc
    if not result.is_finite() or result <= 0:
        raise ChestDomainError("Quantidade deve ser positiva.")
    if result > QUANTITY_MAX:
        raise ChestDomainError("Quantidade excede o limite suportado.")
    rounded = result.quantize(QUANTITY_SCALE)
    if rounded != result:
        raise ChestDomainError("Quantidade aceita no maximo tres casas decimais.")
    return rounded


def apply_movement(
    previous: Decimal | int | str,
    movement_type: MovementType | str,
    amount: Decimal | int | str,
) -> Decimal:
    before = Decimal(str(previous)).quantize(QUANTITY_SCALE)
    kind = MovementType(movement_type)
    delta = quantity(amount)
    after = before + delta if kind in CREDIT_TYPES else before - delta
    if after < 0:
        raise InsufficientBalance("Saldo insuficiente para concluir a movimentacao.")
    return after
