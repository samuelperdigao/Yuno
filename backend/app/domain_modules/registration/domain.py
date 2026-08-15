from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
try:
    from enum import StrEnum
except ImportError:  # Python 3.10
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class RegistrationDomainError(ValueError):
    pass


class OrganizationMemberStatus(StrEnum):
    active = "active"
    inactive = "inactive"


class RegistrationRequestStatus(StrEnum):
    pending = "pending"
    processing = "processing"
    approved = "approved"
    rejected = "rejected"


class CompensationState(StrEnum):
    none = "none"
    prepared = "prepared"
    required = "required"
    complete = "complete"
    failed = "failed"


REQUEST_TRANSITIONS: Mapping[RegistrationRequestStatus, set[RegistrationRequestStatus]] = {
    RegistrationRequestStatus.pending: {
        RegistrationRequestStatus.processing,
        RegistrationRequestStatus.rejected,
    },
    RegistrationRequestStatus.processing: {
        RegistrationRequestStatus.pending,
        RegistrationRequestStatus.approved,
    },
    RegistrationRequestStatus.approved: set(),
    RegistrationRequestStatus.rejected: set(),
}


def ensure_request_transition(
    current: RegistrationRequestStatus, target: RegistrationRequestStatus
) -> None:
    if target not in REQUEST_TRANSITIONS.get(current, set()):
        raise RegistrationDomainError(
            f"Transicao de registro invalida: {current.value} -> {target.value}."
        )


def normalize_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().split())


def normalize_player_id(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def validate_player_id(
    value: str,
    *,
    numeric_only: bool,
    min_length: int,
    max_length: int,
) -> str:
    normalized = normalize_player_id(value)
    if not min_length <= len(normalized) <= max_length:
        raise RegistrationDomainError(
            f"O ID deve conter entre {min_length} e {max_length} caracteres."
        )
    if numeric_only and not re.fullmatch(r"[0-9]+", normalized):
        raise RegistrationDomainError("O ID deve conter apenas numeros ASCII de 0 a 9.")
    return normalized


def validate_nickname_template(value: str) -> str:
    template = unicodedata.normalize("NFKC", value).strip()
    if not template:
        raise RegistrationDomainError("O template de nickname e obrigatorio.")
    allowed = {"name", "id"}
    fields = set(re.findall(r"\{([^{}]+)\}", template))
    if "{" in re.sub(r"\{[^{}]+\}", "", template) or "}" in re.sub(
        r"\{[^{}]+\}", "", template
    ):
        raise RegistrationDomainError("Template de nickname possui chaves invalidas.")
    if not fields:
        raise RegistrationDomainError("Use ao menos um placeholder: {name} ou {id}.")
    unknown = fields - allowed
    if unknown:
        raise RegistrationDomainError(
            f"Placeholder nao permitido: {sorted(unknown)[0]}."
        )
    return template


def render_nickname(template: str, *, name: str, player_id: str) -> str:
    safe_template = validate_nickname_template(template)
    rendered = safe_template.replace("{name}", name).replace("{id}", player_id)
    if not 1 <= len(rendered) <= 32:
        raise RegistrationDomainError(
            "O nickname final deve conter de 1 a 32 caracteres."
        )
    return rendered
