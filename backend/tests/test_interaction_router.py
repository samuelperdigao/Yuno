"""O dispatcher bruto precisa atender os dois formatos de `custom_id`.

Convivem dois esquemas: `yuno:v1:<modulo>:<superficie>:<acao>` (version-first,
usado pelo Registro) e `yuno:<modulo>:v2:<superficie>:<acao>` (module-first,
usado pelos Tickets de Farm).

O dispatcher so aceitava o module-first, apostando que o DynamicItem do
discord.py cobriria o resto. A aposta e falsa onde os paineis vivem: o
discord.py 2.4 nao reconstroi filhos aninhados dentro de um container
Components V2 e descarta a interacao em silencio. Com isso os tres botoes do
Registro -- abrir formulario, aprovar e rejeitar -- ficaram sem handler nenhum:
no servidor de teste a interacao chegava, era logada, e nenhuma chamada de API
acontecia depois. O membro so via "Esta interacao falhou".
"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bot"))

import discord  # noqa: E402

from yuno_bot.main import _interaction_expired  # noqa: E402
from yuno_bot.platform.router import InteractionRouter  # noqa: E402


class _FakeInteraction:
    def __init__(self, custom_id: str) -> None:
        self.data = {"custom_id": custom_id}


def _router_capturando(monkeypatch) -> tuple[InteractionRouter, list[dict]]:
    router = InteractionRouter(api=object())
    despachados: list[dict] = []

    async def dispatch(interaction, *, module_key, surface, action_key, **kwargs):
        despachados.append(
            {"module_key": module_key, "surface": surface, "action_key": action_key}
        )

    monkeypatch.setattr(router, "dispatch", dispatch)
    return router, despachados


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("custom_id", "esperado"),
    [
        (
            # Painel publico do Registro: e este que estava mudo em producao.
            "yuno:v1:registration:public:open_form",
            {"module_key": "registration", "surface": "public", "action_key": "open_form"},
        ),
        (
            "yuno:v1:registration:review:approve",
            {"module_key": "registration", "surface": "review", "action_key": "approve"},
        ),
        (
            # Module-first ja funcionava; entra aqui para travar a nao-regressao.
            "yuno:farm_tickets:v2:global:open_ticket",
            {"module_key": "farm_tickets", "surface": "global", "action_key": "open_ticket"},
        ),
    ],
    ids=["registro-abrir", "registro-aprovar", "farm-tickets"],
)
async def test_dispatcher_atende_os_dois_formatos(monkeypatch, custom_id, esperado) -> None:
    router, despachados = _router_capturando(monkeypatch)

    assert await router.dispatch_components_v2(_FakeInteraction(custom_id)) is True
    assert despachados == [esperado]


@pytest.mark.asyncio
async def test_dispatcher_ignora_id_fora_do_formato(monkeypatch) -> None:
    """Devolver False e o contrato: quem chama tenta o proximo dispatcher."""

    router, despachados = _router_capturando(monkeypatch)

    for custom_id in ("outra-coisa", "yuno:", "yuno:v1:registration:public"):
        assert await router.dispatch_components_v2(_FakeInteraction(custom_id)) is False
    assert despachados == []


@pytest.mark.asyncio
async def test_id_da_central_casa_com_module_first_e_depende_da_ordem(monkeypatch) -> None:
    """A Central precisa ser despachada ANTES deste router.

    `yuno:central:v1:core:select_module` casa com o padrao module-first lendo
    "central" como nome de modulo. Nao ha nada no router que impeca isso -- o
    que protege e a ordem em `main.on_interaction`, que tenta
    `dashboard.dispatch_components_v2` primeiro e so cai aqui se aquele
    devolver False. Este teste existe para que inverter essa ordem quebre um
    teste em vez de quebrar a Central em producao.
    """

    router, despachados = _router_capturando(monkeypatch)

    handled = await router.dispatch_components_v2(
        _FakeInteraction("yuno:central:v1:core:select_module")
    )

    assert handled is True
    assert despachados == [
        {"module_key": "central", "surface": "core", "action_key": "select_module"}
    ]


def _erro_http(code: int) -> discord.HTTPException:
    resposta = type("R", (), {"status": 404, "reason": "Not Found"})()
    return discord.NotFound(resposta, {"code": code, "message": "Unknown interaction"})


def test_interacao_expirada_e_reconhecida_pelo_codigo() -> None:
    """10062 e terminal: insistir em responder so empilha traceback.

    Em producao um unico clique gerou tres tracebacks encadeados -- o handler,
    o aviso de erro do modulo e o aviso de erro do bot, cada um tentando falar
    com um token ja vencido e recebendo 10062 de volta.
    """

    assert _interaction_expired(_erro_http(10062)) is True
    # 40060 e "ja reconhecida", situacao diferente: nao pode ser silenciada.
    assert _interaction_expired(_erro_http(40060)) is False
    assert _interaction_expired(RuntimeError("outra coisa")) is False
