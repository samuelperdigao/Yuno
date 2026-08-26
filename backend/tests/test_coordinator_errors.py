"""`last_error` precisa dizer o que aconteceu.

O coordinator gravava "Falha no handler do job." para qualquer excecao. O
traceback ia para o journal do bot, mas quem consulta `automation_tasks` --
que e por onde se descobre que a fila esta travada -- via so a frase generica.
Cinco jobs ficaram assim, e so reproduzindo a chamada a mao apareceu que o
backend respondia 422 por causa do `max_length` de `correlation_id`.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bot"))

from yuno_bot.platform.coordinator import (  # noqa: E402
    ERROR_MAX_LENGTH,
    describe_error,
)


class _FakeResponse:
    text = '{"detail":"String should have at most 80 characters"}'


class _FakeHTTPError(Exception):
    response = _FakeResponse()


def test_descreve_tipo_e_mensagem() -> None:
    assert describe_error(ValueError("cargo removido")) == (
        "ValueError: cargo removido"
    )


def test_inclui_o_corpo_da_resposta_http() -> None:
    detalhe = describe_error(_FakeHTTPError("422 Unprocessable Entity"))
    assert detalhe.startswith("_FakeHTTPError: 422 Unprocessable Entity")
    # O corpo e a unica parte que diz QUAL campo o backend recusou.
    assert "at most 80 characters" in detalhe


def test_respeita_o_limite_do_backend() -> None:
    class _Gigante(Exception):
        response = type("R", (), {"text": "x" * 5000})()

    assert len(describe_error(_Gigante("y" * 5000))) == ERROR_MAX_LENGTH


def test_excecao_sem_resposta_nao_quebra() -> None:
    assert describe_error(RuntimeError("sem response")) == (
        "RuntimeError: sem response"
    )
