from __future__ import annotations

MAX_TITLE_LENGTH = 256
MAX_CONTENT_LENGTH = 4000


class AnuncioDomainError(ValueError):
    pass


def normalize_title(value: str) -> str:
    text = (value or "").strip()
    if not text:
        raise AnuncioDomainError("O título do anúncio não pode ficar vazio.")
    if len(text) > MAX_TITLE_LENGTH:
        raise AnuncioDomainError(f"O título deve ter no máximo {MAX_TITLE_LENGTH} caracteres.")
    return text


def normalize_content(value: str) -> str:
    text = (value or "").strip()
    if not text:
        raise AnuncioDomainError("O conteúdo do anúncio não pode ficar vazio.")
    if len(text) > MAX_CONTENT_LENGTH:
        raise AnuncioDomainError(f"O conteúdo deve ter no máximo {MAX_CONTENT_LENGTH} caracteres.")
    return text
