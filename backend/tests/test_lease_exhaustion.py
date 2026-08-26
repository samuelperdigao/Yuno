"""Lease vencido nao pode reclamar trabalho indefinidamente.

Os dois claims aceitam de volta item `claimed` com lease vencido -- e assim que
o trabalho retoma quando um worker morre no meio. Mas esse retorno somava `+1`
em `attempts` sem passar pela conferencia de `max_attempts`, que so existia no
caminho de falha. Worker que morre toda vez repetia o job para sempre.

Observado em producao: `farm_tickets.proof.process` com `attempts = 15` contra
`max_attempts = 10`.
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import app.models  # noqa: E402,F401 -- registra todas as tabelas em Base.metadata
from app.db import Base  # noqa: E402
from app.platform.automation import claim_tasks  # noqa: E402
from app.platform.models import (  # noqa: E402
    AutomationTask,
    DeliveryOutbox,
    ModuleInstance,
    ModuleLifecycle,
    WorkState,
)
from app.platform.outbox import claim_deliveries  # noqa: E402

GUILD = "guild-lease"
MODULE = "farm_tickets"


def _sessions():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _vencido() -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=5)


@pytest.mark.parametrize("tentativas_usadas", [3, 5])
def test_job_com_lease_vencido_e_tentativas_esgotadas_vira_failed(
    tentativas_usadas: int,
) -> None:
    async def scenario() -> None:
        engine, sessions = _sessions()
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(
                ModuleInstance(
                    guild_id=GUILD,
                    module_key=MODULE,
                    lifecycle=ModuleLifecycle.active,
                )
            )
            # Worker morreu segurando o lease, sem nunca chamar fail_task.
            session.add(
                AutomationTask(
                    guild_id=GUILD,
                    module_key=MODULE,
                    job_key="farm_tickets.proof.process",
                    resource_type="farm_ticket",
                    resource_id="ticket-1",
                    due_at=_vencido(),
                    state=WorkState.claimed,
                    attempts=tentativas_usadas,
                    max_attempts=tentativas_usadas,
                    lease_owner="worker-morto",
                    lease_until=_vencido(),
                    idempotency_key=f"esgotado-{tentativas_usadas}",
                    correlation_id="lease-test",
                )
            )
            await session.commit()

            reclamados = await claim_tasks(
                session, worker_id="worker-novo", limit=10, lease_seconds=60
            )
            assert reclamados == [], "job sem tentativa nao pode voltar para a fila"

            task = (await session.execute(AutomationTask.__table__.select())).one()
            assert task.state == WorkState.failed
            assert task.attempts == tentativas_usadas, (
                "reclamar um job esgotado inflava attempts acima de max_attempts"
            )
            assert task.lease_owner is None
            assert task.last_error is not None
        await engine.dispose()

    asyncio.run(scenario())


def test_job_com_lease_vencido_e_tentativa_sobrando_continua_retomavel() -> None:
    """A retomada por lease perdido nao pode ser sacrificada pela correcao."""

    async def scenario() -> None:
        engine, sessions = _sessions()
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(
                ModuleInstance(
                    guild_id=GUILD,
                    module_key=MODULE,
                    lifecycle=ModuleLifecycle.active,
                )
            )
            session.add(
                AutomationTask(
                    guild_id=GUILD,
                    module_key=MODULE,
                    job_key="farm_tickets.provision",
                    resource_type="farm_ticket",
                    resource_id="ticket-2",
                    due_at=_vencido(),
                    state=WorkState.claimed,
                    attempts=2,
                    max_attempts=10,
                    lease_owner="worker-morto",
                    lease_until=_vencido(),
                    idempotency_key="ainda-tem-tentativa",
                    correlation_id="lease-test",
                )
            )
            await session.commit()

            reclamados = await claim_tasks(
                session, worker_id="worker-novo", limit=10, lease_seconds=60
            )
            assert len(reclamados) == 1
            assert reclamados[0].attempts == 3
            assert reclamados[0].lease_owner == "worker-novo"
        await engine.dispose()

    asyncio.run(scenario())


def test_entrega_com_lease_vencido_e_tentativas_esgotadas_vira_failed() -> None:
    """O outbox tinha exatamente o mesmo furo do claim de jobs."""

    async def scenario() -> None:
        engine, sessions = _sessions()
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(
                DeliveryOutbox(
                    guild_id=GUILD,
                    module_key=MODULE,
                    renderer_key="farm_tickets.panel",
                    destination_type="channel",
                    destination_id="123",
                    available_at=_vencido(),
                    state=WorkState.claimed,
                    attempts=5,
                    max_attempts=5,
                    lease_owner="worker-morto",
                    lease_until=_vencido(),
                    idempotency_key="entrega-esgotada",
                    correlation_id="lease-test",
                )
            )
            await session.commit()

            reclamadas = await claim_deliveries(
                session, worker_id="worker-novo", limit=10, lease_seconds=60
            )
            assert reclamadas == []

            entrega = (await session.execute(DeliveryOutbox.__table__.select())).one()
            assert entrega.state == WorkState.failed
            assert entrega.attempts == 5
            assert entrega.lease_owner is None
        await engine.dispose()

    asyncio.run(scenario())


def test_erro_real_do_handler_sobrevive_ao_encerramento_por_lease() -> None:
    """Quem ja tem last_error nao perde o diagnostico para a frase do lease."""

    async def scenario() -> None:
        engine, sessions = _sessions()
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(
                ModuleInstance(
                    guild_id=GUILD,
                    module_key=MODULE,
                    lifecycle=ModuleLifecycle.active,
                )
            )
            session.add(
                AutomationTask(
                    guild_id=GUILD,
                    module_key=MODULE,
                    job_key="farm_tickets.reconcile",
                    resource_type="guild",
                    resource_id=GUILD,
                    due_at=_vencido(),
                    state=WorkState.claimed,
                    attempts=10,
                    max_attempts=10,
                    lease_owner="worker-morto",
                    lease_until=_vencido(),
                    idempotency_key="com-erro-real",
                    correlation_id="lease-test",
                    last_error="HTTPStatusError: 422 | corpo: {...}",
                )
            )
            await session.commit()

            await claim_tasks(session, worker_id="worker-novo", limit=10, lease_seconds=60)

            task = (await session.execute(AutomationTask.__table__.select())).one()
            assert task.state == WorkState.failed
            assert task.last_error == "HTTPStatusError: 422 | corpo: {...}"
        await engine.dispose()

    asyncio.run(scenario())
