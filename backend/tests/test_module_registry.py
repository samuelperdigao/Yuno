"""Testes do registry de modulos.

O registry existe para que a lista de modulos tenha uma fonte unica. Estes
testes travam as invariantes que, quando quebradas, so aparecem no servidor do
cliente depois da venda: modulo que existe no backend e nao no bot, canal
duplicado entre dois modulos, view que nao consegue ser reconstruida no boot.
"""

import ast
import asyncio
import inspect
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "bot"))

from yuno_bot import modules, server_setup  # noqa: E402


@pytest.fixture(scope="module")
def registry():
    return modules.discover_modules(force=True)


def _backend_modules() -> list[str]:
    """Le `MODULES` de schemas.py por AST.

    Parsear em vez de importar mantem o teste rodando mesmo sem SQLAlchemy
    instalado, e o objetivo aqui e comparar duas listas, nao exercitar o ORM.
    """
    fonte = (ROOT / "backend" / "app" / "schemas.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(fonte)):
        if isinstance(node, ast.Assign) and any(
            isinstance(alvo, ast.Name) and alvo.id == "MODULES" for alvo in node.targets
        ):
            return [elemento.value for elemento in node.value.elts]
    raise AssertionError("MODULES nao encontrado em backend/app/schemas.py")


def test_bot_e_backend_declaram_os_mesmos_modulos(registry):
    """Foi exatamente essa divergencia que deixou farm_tickets fora do setup."""
    assert set(registry) == set(_backend_modules())


def test_modulos_tem_pelo_menos_um_cog(registry):
    sem_cog = [key for key, spec in registry.items() if not spec.cogs]
    assert not sem_cog, f"Modulos sem cog registrado: {sem_cog}"


def test_command_keys_usam_o_prefixo_do_proprio_modulo(registry):
    """`command_permissions` e indexado por `<modulo>.<comando>`.

    Um prefixo errado faz a regra de permissao nunca casar, e o sintoma para o
    cliente e "o comando esta liberado para todo mundo" — silencioso e grave.
    """
    erros = []
    for key, spec in registry.items():
        for command_key in spec.command_keys:
            if not command_key.startswith(f"{key}."):
                erros.append(f"{key}: '{command_key}'")
    assert not erros, f"command_keys com prefixo errado: {erros}"


def test_nao_ha_colisao_de_canal(registry):
    nomes = [canal.name for spec in registry.values() for canal in spec.setup_channels]
    nomes += [spec.log_channel for spec in registry.values() if spec.log_channel]
    duplicados = {nome for nome in nomes if nomes.count(nome) > 1}
    assert not duplicados, f"Canais declarados por mais de um modulo: {duplicados}"


def test_canais_de_setup_apontam_para_categoria_existente(registry):
    for canal in server_setup.setup_channels():
        assert canal.category in server_setup.SETUP_CATEGORIES, (
            f"Canal '{canal.key}' aponta para categoria '{canal.category}', "
            f"que nao existe em SETUP_CATEGORIES."
        )


async def _construir_views(registry) -> list[tuple[str, object]]:
    """Instancia cogs e views como o boot faz, dentro de um event loop.

    Precisa de loop porque alguns cogs sobem `tasks.loop` no __init__
    (FarmTicketsCog, por exemplo). Os cogs sao descarregados no fim para nao
    deixar task pendente vazando entre testes.
    """
    context = modules.ModuleContext(
        SimpleNamespace(api=SimpleNamespace(), parcerias_repository=SimpleNamespace())
    )
    cogs = []
    for spec in registry.values():
        for fabrica in spec.cogs:
            cog = fabrica(context)
            context.remember(cog)
            cogs.append(cog)

    views = [
        (spec.key, fabrica(context))
        for spec in registry.values()
        for fabrica in spec.views
    ]

    for cog in cogs:
        descarregar = getattr(cog, "cog_unload", None)
        if descarregar is None:
            continue
        resultado = descarregar()
        if inspect.isawaitable(resultado):
            await resultado

    return views


@pytest.fixture(scope="module")
def views(registry):
    return asyncio.run(_construir_views(registry))


def test_fabricas_de_view_constroem_sem_erro(views):
    """Toda view persistente e reconstruida a cada boot.

    Se uma fabrica quebra, os botoes do painel morrem no servidor do cliente no
    primeiro deploy e a falha so aparece quando alguem clica.
    """
    assert views, "Nenhuma view foi construida; o registry provavelmente nao descobriu os modulos."
    for key, view in views:
        assert view.timeout is None, (
            f"View de '{key}' tem timeout. View de painel fixo precisa de timeout=None, "
            f"senao para de responder depois de alguns minutos."
        )


def test_views_persistentes_tem_custom_id_estavel(views):
    """Sem custom_id, discord.py recusa registrar a view como persistente."""
    for key, view in views:
        for item in view.children:
            assert getattr(item, "custom_id", None), f"Item sem custom_id na view de '{key}'."


def test_ordem_do_registry_e_deterministica():
    primeira = list(modules.discover_modules(force=True))
    segunda = list(modules.discover_modules(force=True))
    assert primeira == segunda
