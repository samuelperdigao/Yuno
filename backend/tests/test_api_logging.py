"""Trava a visibilidade de erro da API em producao.

`create_database()` roda o Alembic dentro do lifespan do FastAPI, e o
`migrations/env.py` chama `logging.config.fileConfig`. Com o padrao
`disable_existing_loggers=True`, esse fileConfig desliga todos os loggers que o
uvicorn ja tinha criado no boot -- inclusive `uvicorn.error`, que e por onde o
uvicorn emite "Exception in ASGI application" com o traceback de todo 500.

Foi exatamente isso que deixou o `yuno-api` cego no servidor de teste: o journal
mostrava as linhas do alembic e depois nada, nem access log nem traceback, o que
transformou o 500 de `farm_tickets/meta-events/consume` em erro sem diagnostico.

O teste roda num subprocesso porque o estado do `logging` e global do processo:
so um processo limpo reproduz a ordem real de boot (uvicorn cria os loggers ->
lifespan roda o Alembic).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"

WATCHED_LOGGERS = ("uvicorn.error", "uvicorn.access", "httpx")

BOOT_SCRIPT = """
import asyncio
import json
import logging

# Ordem real do boot: o uvicorn cria os loggers dele antes do lifespan.
for name in {watched!r}:
    logging.getLogger(name)

from app.db import create_database

asyncio.run(create_database())

print(json.dumps({{name: logging.getLogger(name).disabled for name in {watched!r}}}))
"""


def test_alembic_no_lifespan_nao_desliga_os_loggers_do_uvicorn(tmp_path: Path) -> None:
    database = tmp_path / "boot.db"
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{database.as_posix()}"

    result = subprocess.run(
        [sys.executable, "-c", BOOT_SCRIPT.format(watched=WATCHED_LOGGERS)],
        cwd=BACKEND,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    disabled = json.loads(result.stdout.strip().splitlines()[-1])
    assert disabled == {name: False for name in WATCHED_LOGGERS}, (
        "fileConfig do Alembic desligou loggers ja existentes; a API volta a "
        "engolir o traceback de todo 500. Ver migrations/env.py."
    )
