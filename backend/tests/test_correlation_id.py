"""Trava o tamanho de `correlation_id` contra o formato que o derrubou.

`meta:{event_id}:ticket:{ticket_id}` tem 85 caracteres fixos (5 + 36 + 8 + 36).
Com a coluna em `VARCHAR(80)`, o PostgreSQL recusava o INSERT em
`automation_tasks` e o `POST .../farm_tickets/meta-events/consume` devolvia 500
a cada boot do bot, travando o cursor de eventos da Meta no servidor de teste
desde 2026-08-22. O SQLite aceita silenciosamente, entao a suite inteira passava.

Ver tambem `conftest.py`, que faz toda a suite cobrar tamanho de VARCHAR.
"""

import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import app.models  # noqa: E402,F401 -- registra todas as tabelas em Base.metadata
from app.db import Base  # noqa: E402
from app.platform.correlation import (  # noqa: E402
    CORRELATION_ID_MAX_LENGTH,
    clamp_correlation_id,
)


def _correlation_columns():
    for table in Base.metadata.tables.values():
        column = table.columns.get("correlation_id")
        if column is not None:
            yield table.name, column


def test_toda_coluna_de_correlacao_usa_o_tamanho_canonico() -> None:
    columns = dict(_correlation_columns())
    assert columns, "nenhuma coluna correlation_id encontrada"
    divergentes = {
        name: column.type.length
        for name, column in columns.items()
        if column.type.length != CORRELATION_ID_MAX_LENGTH
    }
    assert not divergentes, (
        "correlation_id precisa ter o mesmo tamanho em toda tabela, senao a "
        f"correlacao cabe numa e estoura na outra: {divergentes}"
    )


def test_correlacao_de_fim_de_ciclo_cabe_na_coluna() -> None:
    # Formato real de `freeze_and_close_for_cycle`, com dois UUIDs de verdade.
    correlation = f"meta:{uuid4()}:ticket:{uuid4()}"
    assert len(correlation) == 85, "o formato mudou; revise o tamanho da coluna"
    assert len(correlation) <= CORRELATION_ID_MAX_LENGTH


def test_schema_de_transporte_acompanha_a_coluna() -> None:
    """Coluna larga e schema estreito = 422 antes de chegar ao dominio.

    Alargar so a coluna nao resolve: a correlacao de 85 caracteres passou a ser
    aceita pelo banco e continuou sendo recusada pelo `ActorContextIn`, entao
    todo job de limpeza terminal levava 422 no `POST .../bindings`. Os dois
    limites precisam andar juntos.
    """
    from app.api.platform.dependencies import CorrelationHeader
    from app.platform import schemas

    def _max_length(constraints) -> int | None:
        for item in constraints:
            limite = getattr(item, "max_length", None)
            if limite is not None:
                return limite
            # `fastapi.params.Header` guarda a restricao um nivel abaixo.
            aninhado = _max_length(getattr(item, "metadata", ()))
            if aninhado is not None:
                return aninhado
        return None

    # `None` = campo sem limite declarado (tipico dos modelos de saida), o que
    # nao restringe nada. So um limite MENOR que a coluna e defeito.
    estreitos: dict[str, int] = {}
    for name in dir(schemas):
        fields = getattr(getattr(schemas, name), "model_fields", None)
        if not isinstance(fields, dict) or "correlation_id" not in fields:
            continue
        limite = _max_length(fields["correlation_id"].metadata)
        if limite is not None and limite < CORRELATION_ID_MAX_LENGTH:
            estreitos[f"{name}.correlation_id"] = limite

    header = _max_length(CorrelationHeader.__metadata__)
    assert header is not None, "CorrelationHeader perdeu o limite declarado"
    if header < CORRELATION_ID_MAX_LENGTH:
        estreitos["CorrelationHeader"] = header

    assert not estreitos, (
        "schema de entrada capa correlation_id abaixo do tamanho da coluna "
        f"({CORRELATION_ID_MAX_LENGTH}): {estreitos}"
    )


def test_clamp_garante_o_limite_da_coluna() -> None:
    assert clamp_correlation_id("x" * 500) == "x" * CORRELATION_ID_MAX_LENGTH
    curto = "meta:abc:ticket:def"
    assert clamp_correlation_id(curto) == curto
