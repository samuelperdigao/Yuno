"""Encerra trabalho durável que esgotou as tentativas sem passar pela falha.

`max_attempts` só era conferido no caminho de falha -- `fail_task` em
`automation.py` e `fail_delivery` em `outbox.py`. Os dois claims aceitam de
volta item `claimed` com lease vencido, que é o que garante retomada quando um
worker morre no meio do trabalho. O problema é que esse retorno soma `+1` em
`attempts` sem nunca passar pela conferência de esgotamento: se o worker morre
toda vez -- ou se a própria chamada de falha não chega até a API -- o item
repete para sempre.

Foi o que aconteceu em produção: um job de módulo de domínio chegou a
`attempts = 15` contra `max_attempts = 10`, repetindo trabalho que já deveria
estar encerrado havia cinco tentativas. O caso concreto está em
`docs/incidente-consume-meta-500.md`; esta camada é genérica de propósito e não
cita módulo.

A retomada por lease vencido continua valendo; o que muda é que ela para de
valer quando as tentativas acabaram.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.models import WorkState

LEASE_LOST_ERROR = "Lease expirou sem resposta do worker e as tentativas acabaram."


async def reap_exhausted_leases(
    session: AsyncSession, model: Any, *, now: datetime | None = None
) -> int:
    """Marca como `failed` todo item de `model` preso em lease vencido e sem tentativa.

    Serve tanto para `AutomationTask` quanto para `DeliveryOutbox` -- os dois
    têm `state`, `attempts`, `max_attempts`, `lease_owner`, `lease_until` e
    `last_error` com o mesmo significado. Devolve quantos foram encerrados.

    Não sobrescreve `last_error` já preenchido: o erro real do handler explica
    mais do que a perda do lease.
    """
    momento = now or datetime.now(timezone.utc)
    presos = (
        await session.execute(
            select(model)
            .where(
                model.state == WorkState.claimed,
                model.lease_until < momento,
                model.attempts >= model.max_attempts,
            )
            .with_for_update(skip_locked=True)
        )
    ).scalars()
    total = 0
    for item in presos:
        item.state = WorkState.failed
        item.lease_owner = None
        item.lease_until = None
        item.last_error = item.last_error or LEASE_LOST_ERROR
        total += 1
    return total
