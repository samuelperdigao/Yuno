from __future__ import annotations

import re
import unicodedata
from enum import Enum


class RegistrationAttemptStatus(str, Enum):
    awaiting_image = "awaiting_image"
    completed = "completed"
    expired = "expired"
    cancelled = "cancelled"


class ParceriaStatus(str, Enum):
    active = "active"
    inactive = "inactive"
    publication_pending = "publication_pending"
    degraded = "degraded"


class PublicationStatus(str, Enum):
    pending = "pending"
    published = "published"
    missing = "missing"
    archived = "archived"
    failed = "failed"


ALLOWED_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def normalize_family(value: str) -> str:
    """Normaliza família para comparação, sem alterar o nome apresentado."""

    text = " ".join(str(value or "").strip().split())
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text).strip().casefold()


def validate_image(*, content_type: str, size_bytes: int) -> list[str]:
    errors: list[str] = []
    if content_type.casefold() not in ALLOWED_IMAGE_TYPES:
        errors.append("A imagem deve ser PNG, JPEG ou WebP.")
    if size_bytes <= 0:
        errors.append("A imagem está vazia.")
    elif size_bytes > MAX_IMAGE_BYTES:
        errors.append("A imagem excede o limite de 8 MiB.")
    return errors


def can_transition(current: ParceriaStatus, target: ParceriaStatus) -> bool:
    return target in {
        ParceriaStatus.active: {
            ParceriaStatus.inactive,
            ParceriaStatus.publication_pending,
        },
        ParceriaStatus.inactive: {ParceriaStatus.publication_pending},
        ParceriaStatus.publication_pending: {
            ParceriaStatus.active,
            ParceriaStatus.degraded,
            ParceriaStatus.inactive,
        },
        ParceriaStatus.degraded: {
            ParceriaStatus.publication_pending,
            ParceriaStatus.inactive,
        },
    }[current]
