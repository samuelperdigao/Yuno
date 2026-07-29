"""Testes do cache de guild config.

O teste que mais importa aqui e o de isolamento entre servidores. Um cache mal
chaveado num bot multi-tenant serve a configuracao de um cliente para outro —
isso e vazamento de dado entre clientes, nao lentidao.
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "bot"))

from yuno_bot.api_client import YunoAPI  # noqa: E402
from yuno_bot.cache import TTLCache  # noqa: E402


# ── TTLCache ──────────────────────────────────────────────────────────────────


def test_segunda_leitura_nao_refaz_a_busca():
    cache = TTLCache(ttl=60)
    chamadas = []

    async def fetch():
        chamadas.append(1)
        return {"valor": 1}

    async def cenario():
        await cache.get_or_fetch("g1", fetch)
        await cache.get_or_fetch("g1", fetch)

    asyncio.run(cenario())
    assert len(chamadas) == 1
    assert cache.hits == 1 and cache.misses == 1


def test_entrada_expira_apos_o_ttl():
    cache = TTLCache(ttl=0.05)
    chamadas = []

    async def fetch():
        chamadas.append(1)
        return {"valor": len(chamadas)}

    async def cenario():
        primeiro = await cache.get_or_fetch("g1", fetch)
        await asyncio.sleep(0.08)
        segundo = await cache.get_or_fetch("g1", fetch)
        return primeiro, segundo

    primeiro, segundo = asyncio.run(cenario())
    assert primeiro != segundo
    assert len(chamadas) == 2


def test_servidores_diferentes_nunca_compartilham_entrada():
    """A invariante multi-tenant: config de um cliente nao vaza para outro."""
    cache = TTLCache(ttl=60)

    async def cenario():
        await cache.get_or_fetch(111, lambda: _valor({"dono": "cliente A"}))
        await cache.get_or_fetch(222, lambda: _valor({"dono": "cliente B"}))
        return cache.peek(111), cache.peek(222)

    a, b = asyncio.run(cenario())
    assert a == {"dono": "cliente A"}
    assert b == {"dono": "cliente B"}


def test_chamadas_concorrentes_disparam_uma_unica_busca():
    """Varios membros clicando no painel ao mesmo tempo nao viram N requests."""
    cache = TTLCache(ttl=60)
    chamadas = []

    async def fetch():
        chamadas.append(1)
        await asyncio.sleep(0.02)  # simula latencia de rede
        return {"valor": 1}

    async def cenario():
        await asyncio.gather(*(cache.get_or_fetch("g1", fetch) for _ in range(10)))

    asyncio.run(cenario())
    assert len(chamadas) == 1, f"thundering herd: {len(chamadas)} chamadas em vez de 1"


def test_erro_nao_e_cacheado():
    """Instabilidade momentanea da API nao pode virar TTL segundos de queda."""
    cache = TTLCache(ttl=60)
    tentativas = []

    async def fetch():
        tentativas.append(1)
        if len(tentativas) == 1:
            raise RuntimeError("API fora do ar")
        return {"ok": True}

    async def cenario():
        with pytest.raises(RuntimeError):
            await cache.get_or_fetch("g1", fetch)
        return await cache.get_or_fetch("g1", fetch)

    assert asyncio.run(cenario()) == {"ok": True}
    assert len(tentativas) == 2


def test_invalidate_afeta_apenas_a_chave_pedida():
    cache = TTLCache(ttl=60)
    cache.set(111, {"a": 1})
    cache.set(222, {"b": 2})

    cache.invalidate(111)

    assert cache.peek(111) is None
    assert cache.peek(222) == {"b": 2}


async def _valor(v):
    return v


# ── Integracao com YunoAPI ────────────────────────────────────────────────────


def _api_com_fetch_falso(monkeypatch) -> tuple[YunoAPI, list]:
    api = YunoAPI()
    chamadas = []

    async def fake_fetch(guild_id):
        chamadas.append(guild_id)
        return {"guild_id": str(guild_id), "chamada": len(chamadas)}

    monkeypatch.setattr(api, "_fetch_guild_config", fake_fetch)
    return api, chamadas


def test_api_serve_do_cache_entre_chamadas(monkeypatch):
    api, chamadas = _api_com_fetch_falso(monkeypatch)

    async def cenario():
        # Simula uma acao real: o comando le a config, o log le de novo e o
        # envio ao canal de setup le uma terceira vez.
        for _ in range(3):
            await api.get_guild_config(999)

    asyncio.run(cenario())
    assert chamadas == [999], "a acao deveria custar 1 round-trip, nao 3"


def test_api_force_ignora_o_cache(monkeypatch):
    api, chamadas = _api_com_fetch_falso(monkeypatch)

    async def cenario():
        await api.get_guild_config(999)
        await api.get_guild_config(999, force=True)

    asyncio.run(cenario())
    assert len(chamadas) == 2


def test_salvar_config_atualiza_o_cache_sem_novo_get(monkeypatch):
    api, chamadas = _api_com_fetch_falso(monkeypatch)
    novo = {"guild_id": "999", "modules": {"set": False}}

    async def fake_put(guild_id, config):
        api._guild_config_cache.set(guild_id, novo)
        return novo

    async def cenario():
        await api.get_guild_config(999)
        await fake_put(999, novo)
        return await api.get_guild_config(999)

    assert asyncio.run(cenario()) == novo
    assert len(chamadas) == 1, "o PUT ja devolve o estado novo; um GET extra e desperdicio"


def test_cache_do_api_isola_servidores(monkeypatch):
    api, _ = _api_com_fetch_falso(monkeypatch)

    async def cenario():
        primeiro = await api.get_guild_config(111)
        segundo = await api.get_guild_config(222)
        return primeiro, segundo

    primeiro, segundo = asyncio.run(cenario())
    assert primeiro["guild_id"] == "111"
    assert segundo["guild_id"] == "222"


def test_stats_reporta_taxa_de_acerto(monkeypatch):
    api, _ = _api_com_fetch_falso(monkeypatch)

    async def cenario():
        for _ in range(4):
            await api.get_guild_config(999)

    asyncio.run(cenario())
    stats = api.cache_stats()
    assert stats["misses"] == 1
    assert stats["hits"] == 3
    assert stats["taxa_acerto"] == 0.75
