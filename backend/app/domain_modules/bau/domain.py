from __future__ import annotations

import re

PAGE_SIZE = 5
MAX_QUANTITY = 1_000_000
MAX_NAME_LENGTH = 80
MAX_CATEGORY_NAME_LENGTH = 60

_DELTA_PATTERN = re.compile(r"^[+-]?\d+$")


class BauDomainError(ValueError):
    pass


def normalize_name(value: str | None, *, max_length: int, label: str = "Nome") -> str:
    text = " ".join(str(value or "").split())
    if not text:
        raise BauDomainError(f"{label} não pode ficar vazio.")
    if len(text) > max_length:
        raise BauDomainError(f"{label} deve ter no máximo {max_length} caracteres.")
    return text


def parse_delta(raw: str | None) -> int | None:
    """Interpreta o texto de um campo de movimentação: vazio significa 'sem alteração'."""

    text = str(raw or "").strip()
    if not text:
        return None
    if not _DELTA_PATTERN.fullmatch(text):
        raise BauDomainError(f"Valor inválido: '{text}'. Use um número inteiro, ex: 10 ou -5.")
    delta = int(text)
    if delta == 0:
        return None
    return delta


def apply_delta(before: int, delta: int, *, item_name: str) -> int:
    after = before + delta
    if after < 0:
        raise BauDomainError(
            f"Estoque insuficiente de {item_name}: disponível {before}, tentativa de remover {-delta}."
        )
    if after > MAX_QUANTITY:
        raise BauDomainError(f"Estoque de {item_name} ultrapassaria o limite de {MAX_QUANTITY}.")
    return after


def page_count(total_items: int, *, page_size: int = PAGE_SIZE) -> int:
    if total_items <= 0:
        return 1
    return (total_items + page_size - 1) // page_size


def clamp_page(page: int, *, total_items: int, page_size: int = PAGE_SIZE) -> int:
    return max(0, min(page, page_count(total_items, page_size=page_size) - 1))


# Catálogo padrão de uma cidade FiveM genérica, usado apenas para popular a
# guild na primeira publicação. Todo o conteúdo é editável depois pela Central;
# isto é só um ponto de partida razoável, não uma lista fixa do produto.
DEFAULT_CATALOG: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Materiais",
        (
            "Ferro",
            "Aço",
            "Alumínio",
            "Cobre",
            "Vidro",
            "Plástico",
            "Borracha",
            "Tecido",
            "Madeira",
            "Componente Eletrônico",
        ),
    ),
    (
        "Munições",
        ("Munição 9mm", "Munição .45", "Munição .50", "Munição de Rifle", "Munição de Shotgun"),
    ),
    (
        "Armas",
        ("Pistola", "Rifle", "Shotgun", "Faca", "Taser"),
    ),
    (
        "Drogas",
        ("Maconha", "Cocaína", "Metanfetamina", "Erva Processada", "Ecstasy"),
    ),
    (
        "Dinheiro",
        ("Dinheiro Sujo", "Dinheiro Limpo", "Ficha de Cassino"),
    ),
    (
        "Comida e Bebida",
        ("Água", "Refrigerante", "Sanduíche", "Energético", "Café"),
    ),
    (
        "Ferramentas",
        ("Chave de Fenda", "Martelo", "Furadeira", "Maçarico", "Kit de Reparo"),
    ),
    (
        "Documentos",
        ("Identidade Falsa", "Placa Falsa", "Passaporte Falso"),
    ),
    (
        "Eletrônicos",
        ("Celular", "Rádio Comunicador", "Notebook", "GPS", "Câmera"),
    ),
    (
        "Joias e Valores",
        ("Ouro", "Prata", "Diamante", "Relógio", "Colar"),
    ),
    (
        "Combustíveis",
        ("Gasolina", "Diesel", "Gás", "Óleo"),
    ),
    (
        "Medicamentos",
        ("Bandagem", "Kit Médico", "Analgésico", "Colete Balístico"),
    ),
    (
        "Diversos",
        ("Corda", "Lanterna", "Mochila", "Algemas"),
    ),
)
