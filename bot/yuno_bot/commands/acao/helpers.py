"""Logica pura do sistema de acoes: catalogo, datas, pagamento.

Sem dependencia de discord.py (exceto `acao_id_from_message`, que so le um
`discord.Message`) -- e o que torna tudo aqui testavel sem mock de Discord.
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

DATE_BR_EXAMPLE = "08/06/2026"
_DATE_BR_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_DATE_BR_FORMAT = "%d/%m/%Y"


def normalize_date_br(value: str) -> str:
    normalized = value.strip()
    if not _DATE_BR_RE.fullmatch(normalized):
        raise ValueError("Use o formato DD/MM/AAAA.")
    try:
        return datetime.strptime(normalized, _DATE_BR_FORMAT).strftime(_DATE_BR_FORMAT)
    except ValueError as exc:
        raise ValueError("Informe uma data valida no formato DD/MM/AAAA.") from exc


def normalizar_horario(value: str) -> str:
    raw = value.strip()
    if not re.fullmatch(r"\d{2}:\d{2}", raw):
        raise ValueError("Use o formato HH:MM.")
    hora, minuto = (int(part) for part in raw.split(":"))
    if hora > 23 or minuto > 59:
        raise ValueError("Informe um horario valido entre 00:00 e 23:59.")
    return f"{hora:02d}:{minuto:02d}"


def parse_money_centavos(value: str) -> int:
    raw = value.strip().lower().replace("r$", "").replace(" ", "")
    if not raw:
        raise ValueError("Informe o valor total da acao.")
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(".", "")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("Informe um valor em dinheiro valido.") from exc
    if amount <= 0:
        raise ValueError("O valor total precisa ser maior que zero.")
    return int((amount * 100).to_integral_value())


def calcular_pagamento(valor_total_centavos: int, participantes_count: int) -> dict[str, int]:
    """Metade pra faccao, metade dividida entre participantes. Sobra de
    arredondamento (centavos que nao dividem igual) fica com a faccao."""
    if participantes_count <= 0:
        raise ValueError("Vitoria precisa ter pelo menos um participante.")
    valor_participantes = valor_total_centavos // 2
    valor_por_participante = valor_participantes // participantes_count
    valor_participantes_distribuido = valor_por_participante * participantes_count
    valor_faccao = valor_total_centavos - valor_participantes_distribuido
    return {
        "valor_total_centavos": valor_total_centavos,
        "valor_faccao_centavos": valor_faccao,
        "valor_participantes_centavos": valor_participantes_distribuido,
        "valor_por_participante_centavos": valor_por_participante,
    }


def format_money_centavos(value: int | None) -> str:
    value = int(value or 0)
    reais, centavos = divmod(value, 100)
    inteiro = f"{reais:,}".replace(",", ".")
    return f"R$ {inteiro},{centavos:02d}"


def normalize_resultado(value: str) -> str:
    raw = value.strip().lower().replace("í", "i").replace("ó", "o")
    if raw in {"vitoria", "ganha", "ganhou"}:
        return "ganha"
    if raw in {"derrota", "perdida", "perdeu"}:
        return "perdida"
    raise ValueError("Resultado invalido. Use vitoria/ganha ou derrota/perdida.")


def upsert_tipo(tipos: list[dict], *, key: str, nome: str, emoji: str, max_participantes: int | None, regras: str) -> list[dict]:
    novo = {"key": key, "nome": nome, "emoji": emoji, "max_participantes": max_participantes, "regras": regras}
    if any(tipo["key"] == key for tipo in tipos):
        return [novo if tipo["key"] == key else tipo for tipo in tipos]
    return [*tipos, novo]


def remove_tipo(tipos: list[dict], key: str) -> list[dict]:
    return [tipo for tipo in tipos if tipo["key"] != key]


def find_tipo(tipos: list[dict], key: str) -> dict | None:
    return next((tipo for tipo in tipos if tipo["key"] == key), None)


def acao_id_from_message(message) -> int | None:
    if not message or not message.embeds:
        return None
    footer = message.embeds[0].footer.text or ""
    if "#" not in footer:
        return None
    digits = "".join(char for char in footer.rsplit("#", 1)[-1] if char.isdigit())
    return int(digits) if digits else None
