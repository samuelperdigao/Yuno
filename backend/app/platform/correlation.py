"""Tamanho canonico do `correlation_id` e clamp defensivo.

Toda tabela que guarda `correlation_id` usa `String(CORRELATION_ID_MAX_LENGTH)`.
O valor comecou em 80, que nao cabia `meta:{event_id}:ticket:{ticket_id}` (85
caracteres fixos) -- e como o SQLite ignora o tamanho declarado de VARCHAR e o
PostgreSQL nao, a suite passava verde enquanto o `POST .../meta-events/consume`
devolvia 500 em producao a cada boot do bot, travando o cursor de eventos da
Meta.

`correlation_id` e campo de rastreio, nunca chave de deduplicacao (quem
deduplica e `idempotency_key`). Por isso o clamp e aceitavel como ultima
barreira: um id truncado atrapalha a leitura de log, mas um id longo demais
derruba a requisicao inteira. Com 160 nenhum formato atual chega perto do
limite -- o clamp existe para o formato que alguem inventar depois.
"""

from __future__ import annotations

CORRELATION_ID_MAX_LENGTH = 160


def clamp_correlation_id(value: str) -> str:
    """Garante que `value` cabe na coluna de `correlation_id`."""
    return value[:CORRELATION_ID_MAX_LENGTH]
