from __future__ import annotations

_YES = {"sim", "s", "yes", "y"}
_NO = {"não", "nao", "n", "no"}


class AnuncioUIError(ValueError):
    pass


def parse_yes_no(value: str) -> bool:
    """Modais do Discord só têm campos de texto: sim/não chega como texto livre."""
    text = (value or "").strip().casefold()
    if text in _YES:
        return True
    if text in _NO:
        return False
    raise AnuncioUIError('Responda apenas "sim" ou "não".')
