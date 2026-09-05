from __future__ import annotations

# Extraido do farm legado (MDM, cogs/farm_advertencias.py): punicao automatica ao
# acumular advertencias era decisao antiga do MDM e nao vira requisito aqui sem
# aprovacao explicita. O Yuno so registra e loga; a acao sobre o membro fica com a staff.
MAX_REASON_LENGTH = 300


class AdvDomainError(ValueError):
    pass


def normalize_reason(value: str) -> str:
    text = (value or "").strip()
    if not text:
        raise AdvDomainError("O motivo da advertência é obrigatório.")
    if len(text) > MAX_REASON_LENGTH:
        raise AdvDomainError(f"O motivo deve ter no máximo {MAX_REASON_LENGTH} caracteres.")
    return text


def normalize_optional_reason(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > MAX_REASON_LENGTH:
        raise AdvDomainError(f"O motivo deve ter no máximo {MAX_REASON_LENGTH} caracteres.")
    return text


def normalize_discord_id(value: str, *, field_name: str = "membro") -> str:
    text = (value or "").strip().lstrip("<@!").rstrip(">")
    if not text.isdigit():
        raise AdvDomainError(f"Informe um {field_name} válido (ID ou menção).")
    return text
