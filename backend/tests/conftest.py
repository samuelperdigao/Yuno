"""Faz a suite em SQLite cobrar a semantica de VARCHAR do PostgreSQL.

O SQLite ignora o tamanho declarado de `VARCHAR(n)`: grava 85 caracteres numa
coluna de 80 sem reclamar. O PostgreSQL levanta `StringDataRightTruncationError`
e a requisicao vira 500. Foi assim que
`meta:{event_id}:ticket:{ticket_id}` (85 caracteres fixos) passou verde em 248
testes enquanto derrubava o `meta-events/consume` em producao a cada boot do
bot -- primo do bug do `enum.StrEnum`, em que o venv local (3.12) escondia o que
o servidor (3.10) nao aceitava.

Este listener e global: `AsyncSession` delega para a `Session` sincrona, entao
registrar em `Session` cobre toda sessao criada em qualquer teste, sem que os
arquivos de teste precisem saber que ele existe.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import Enum, String, event, inspect
from sqlalchemy.orm import Session

# `get_settings()` tem cache por processo: o primeiro import de `app.db` (direto
# ou via `app.domain_modules.*`/`app.platform.*`) trava esses valores. Antes só
# `test_api.py` setava isso, e como nada era coletado antes dele em ordem
# alfabética, funcionava por acidente. Um novo arquivo de teste que ordene antes
# (ex.: `test_anuncio_domain.py`) e importe a cadeia do backend faz o cache
# travar sem esses valores, e os testes de `test_api.py` voltam 401/503.
# `conftest.py` é sempre importado antes de qualquer `test_*.py` da pasta, então
# fixar os defaults aqui independe da ordem de coleta.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-yuno.db")
os.environ.setdefault("ADMIN_TOKEN", "admin-test")
os.environ.setdefault("BOT_INTERNAL_TOKEN", "bot-test")
os.environ.setdefault("MERCADO_PAGO_WEBHOOK_SECRET", "webhook-test")

ROOT = Path(__file__).resolve().parents[2]
# `backend` e `bot` no path a partir daqui: varios arquivos de teste importam
# `yuno_bot` sem inserir o caminho, e so funcionavam porque algum arquivo
# coletado antes tinha inserido. Isso torna cada arquivo executavel sozinho.
for _package_root in ("backend", "bot"):
    _path = str(ROOT / _package_root)
    if _path not in sys.path:
        sys.path.insert(0, _path)


def _overflows(instance: object) -> list[str]:
    problems: list[str] = []
    mapper = inspect(type(instance))
    for attribute in mapper.column_attrs:
        column = attribute.columns[0]
        column_type = column.type
        # `Enum` herda de `String`, mas o atributo carrega o membro do enum, nao
        # a string gravada -- e o tamanho ja e derivado dos membros.
        if isinstance(column_type, Enum) or not isinstance(column_type, String):
            continue
        length = column_type.length
        if length is None:
            continue
        value = getattr(instance, attribute.key, None)
        if isinstance(value, str) and len(value) > length:
            problems.append(
                f"{mapper.class_.__name__}.{attribute.key} "
                f"({column.table.name}.{column.name}) tem {len(value)} caracteres "
                f"e a coluna e VARCHAR({length}): {value!r}"
            )
    return problems


@event.listens_for(Session, "before_flush")
def _reject_varchar_overflow(session: Session, flush_context, instances) -> None:
    problems: list[str] = []
    for instance in list(session.new) + list(session.dirty):
        problems.extend(_overflows(instance))
    if problems:
        raise AssertionError(
            "Valor maior que a coluna VARCHAR declarada. O SQLite aceitaria, o "
            "PostgreSQL devolveria 500:\n  " + "\n  ".join(problems)
        )
