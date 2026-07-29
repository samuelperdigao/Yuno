"""Cache em memoria com TTL, chaveado por servidor.

Motivacao: uma unica acao do usuario disparava 2-3 chamadas HTTP a API, porque
`send_module_log` e `send_to_setup_channel` buscam a guild config cada um. O
Discord da 3 segundos para a primeira resposta de uma interacao — gastar boa
parte disso em round-trip para buscar o mesmo JSON tres vezes e desperdicio que
aparece como lentidao para todos os clientes ao mesmo tempo, ja que o bot e
unico e o event loop e compartilhado.

Regra inegociavel deste modulo: **tudo e chaveado por guild_id**. Um cache
global aqui vazaria configuracao de um cliente para outro, o que num produto
multi-tenant e incidente de seguranca, nao bug de performance.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Generic, Hashable, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class _Entrada(Generic[T]):
    valor: T
    expira_em: float


class TTLCache(Generic[T]):
    """Cache com expiracao por tempo e uma busca unica por chave concorrente.

    O lock por chave existe para o caso de varios membros do mesmo servidor
    clicarem no painel ao mesmo tempo: sem ele, N interacoes simultaneas viram N
    chamadas identicas a API justamente no pico de uso.
    """

    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self._store: dict[Hashable, _Entrada[T]] = {}
        self._locks: dict[Hashable, asyncio.Lock] = {}
        self.hits = 0
        self.misses = 0

    def _vigente(self, chave: Hashable) -> _Entrada[T] | None:
        entrada = self._store.get(chave)
        if entrada is None:
            return None
        if entrada.expira_em <= time.monotonic():
            self._store.pop(chave, None)
            return None
        return entrada

    def _lock(self, chave: Hashable) -> asyncio.Lock:
        lock = self._locks.get(chave)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[chave] = lock
        return lock

    def peek(self, chave: Hashable) -> T | None:
        entrada = self._vigente(chave)
        return entrada.valor if entrada else None

    def set(self, chave: Hashable, valor: T) -> None:
        self._store[chave] = _Entrada(valor, time.monotonic() + self.ttl)

    def invalidate(self, chave: Hashable) -> None:
        self._store.pop(chave, None)

    def clear(self) -> None:
        self._store.clear()

    async def get_or_fetch(self, chave: Hashable, fetch: Callable[[], Awaitable[T]]) -> T:
        entrada = self._vigente(chave)
        if entrada is not None:
            self.hits += 1
            return entrada.valor

        async with self._lock(chave):
            # Outra corrotina pode ter preenchido enquanto esperavamos o lock.
            entrada = self._vigente(chave)
            if entrada is not None:
                self.hits += 1
                return entrada.valor

            self.misses += 1
            # Falha nao e cacheada de proposito: instabilidade momentanea da API
            # nao pode virar TTL segundos de indisponibilidade para o cliente.
            valor = await fetch()
            self.set(chave, valor)
            return valor

    def stats(self) -> dict[str, Any]:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "entradas": len(self._store),
            "taxa_acerto": round(self.hits / total, 3) if total else 0.0,
        }
