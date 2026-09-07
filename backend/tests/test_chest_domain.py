import asyncio
from decimal import Decimal

import app.models  # noqa: F401
import pytest
from app.db import Base
from app.domain_modules.chest import services
from app.domain_modules.chest.domain import (
    InsufficientBalance,
    MovementType,
    apply_movement,
    normalize_name,
    quantity,
)
from app.domain_modules.chest.models import (
    ChestBalance,
    ChestMovement,
    ChestVersionLink,
)
from app.platform.models import AuditEntry, DeliveryOutbox
from app.platform.registry import discover_domain_modules
from app.platform.schemas import ActorContextIn
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


def admin(guild_id: str = "100", correlation: str = "corr") -> ActorContextIn:
    return ActorContextIn(
        guild_id=guild_id,
        user_id="900",
        discord_permissions=["administrator"],
        correlation_id=correlation,
    )


async def database():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def published_fixture(session, guild_id: str = "100"):
    actor = admin(guild_id)
    draft = await services.catalog_draft(session, guild_id=guild_id)
    saved = await services.save_settings(
        session,
        guild_id=guild_id,
        expected_revision=draft["revision"],
        expected_published_version=0,
        schema_version=1,
        data={
            "panel_channel_id": "10",
            "log_channel_id": "20",
            "show_balances_to_members": True,
            "allow_personal_history": True,
            "withdrawal_reason_required": True,
            "operator_role_ids": [],
            "panel_title": "Sistema de Bau",
            "panel_description": "Estoque operacional.",
        },
        idempotency_key=f"settings-{guild_id}",
        actor=actor,
    )
    chest = await services.upsert_draft_chest(
        session,
        guild_id=guild_id,
        chest_id=None,
        name="  Bau   Central ",
        active=True,
        position=0,
        expected_revision=saved["revision"],
        idempotency_key=f"chest-{guild_id}",
        actor=actor,
    )
    item = await services.upsert_draft_item(
        session,
        guild_id=guild_id,
        item_id=None,
        name="Minério de Ferro",
        unit="kg",
        active=True,
        position=0,
        expected_revision=chest["revision"],
        idempotency_key=f"item-{guild_id}",
        actor=actor,
    )
    link = await services.upsert_draft_link(
        session,
        guild_id=guild_id,
        chest_id=chest["id"],
        item_id=item["id"],
        active=True,
        expected_revision=item["revision"],
        idempotency_key=f"link-{guild_id}",
        actor=actor,
    )
    version = await services.publish_catalog(
        session,
        guild_id=guild_id,
        expected_revision=link["revision"],
        expected_published_version=0,
        grants=[],
        idempotency_key=f"publish-{guild_id}",
        actor=actor,
    )
    return actor, chest, item, version


def test_chest_domain_normalization_quantity_and_signs():
    assert normalize_name("  Baú   SÃO José ") == "bau sao jose"
    assert quantity("1.250") == Decimal("1.250")
    with pytest.raises(ValueError):
        quantity(0)
    with pytest.raises(ValueError):
        quantity("1.0001")
    assert apply_movement("2", MovementType.DEPOSIT, "3") == Decimal("5.000")
    assert apply_movement("5", MovementType.WITHDRAWAL, "2") == Decimal("3.000")
    assert apply_movement("2", MovementType.ADJUSTMENT_CREDIT, "1") == Decimal("3.000")
    assert apply_movement("2", MovementType.ADJUSTMENT_DEBIT, "1") == Decimal("1.000")
    with pytest.raises(InsufficientBalance):
        apply_movement("1", MovementType.WITHDRAWAL, "2")


def test_chest_catalog_publish_movements_ledger_and_idempotency():
    async def scenario():
        discover_domain_modules()
        engine, sessions = await database()
        try:
            async with sessions() as session:
                actor, chest, item, version = await published_fixture(session)
                assert version["version"] == 1
                balance = (
                    await session.execute(
                        select(ChestBalance).where(ChestBalance.guild_id == "100")
                    )
                ).scalar_one()
                assert balance.quantity == 0
                deposit = await services.record_movement(
                    session,
                    guild_id="100",
                    chest_id=chest["id"],
                    item_id=item["id"],
                    movement_type=MovementType.DEPOSIT,
                    amount=Decimal("10"),
                    observation="Carga inicial",
                    idempotency_key="move-1",
                    origin="test",
                    actor=actor,
                )
                replay = await services.record_movement(
                    session,
                    guild_id="100",
                    chest_id=chest["id"],
                    item_id=item["id"],
                    movement_type=MovementType.DEPOSIT,
                    amount=Decimal("10"),
                    observation="Carga inicial",
                    idempotency_key="move-1",
                    origin="test",
                    actor=actor,
                )
                assert replay.id == deposit.id
                withdrawal = await services.record_movement(
                    session,
                    guild_id="100",
                    chest_id=chest["id"],
                    item_id=item["id"],
                    movement_type=MovementType.WITHDRAWAL,
                    amount=Decimal("4"),
                    observation="Uso operacional",
                    idempotency_key="move-2",
                    origin="test",
                    actor=actor,
                )
                credit = await services.record_movement(
                    session,
                    guild_id="100",
                    chest_id=chest["id"],
                    item_id=item["id"],
                    movement_type=MovementType.ADJUSTMENT_CREDIT,
                    amount=Decimal("1"),
                    observation="Correcao de contagem",
                    idempotency_key="move-3",
                    origin="test",
                    actor=actor,
                )
                debit = await services.record_movement(
                    session,
                    guild_id="100",
                    chest_id=chest["id"],
                    item_id=item["id"],
                    movement_type=MovementType.ADJUSTMENT_DEBIT,
                    amount=Decimal("2"),
                    observation="Correcao de contagem",
                    idempotency_key="move-4",
                    origin="test",
                    actor=actor,
                )
                assert [
                    deposit.sequence,
                    withdrawal.sequence,
                    credit.sequence,
                    debit.sequence,
                ] == [1, 2, 3, 4]
                assert debit.balance_after == Decimal("5.000")
                assert deposit.chest_name_snapshot == "Bau Central"
                assert deposit.item_name_snapshot == "Minério de Ferro"
                assert deposit.unit_snapshot == "kg"
                assert (
                    len((await session.execute(select(ChestMovement))).scalars().all())
                    == 4
                )
                assert (
                    len((await session.execute(select(DeliveryOutbox))).scalars().all())
                    == 5
                )
                assert (
                    len(
                        (
                            await session.execute(
                                select(AuditEntry).where(
                                    AuditEntry.module_key == "chest"
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    >= 9
                )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_chest_insufficient_balance_is_atomic_and_withdrawal_reason_is_required():
    async def scenario():
        discover_domain_modules()
        engine, sessions = await database()
        try:
            async with sessions() as session:
                actor, chest, item, _ = await published_fixture(session)
                with pytest.raises(HTTPException) as missing_reason:
                    await services.record_movement(
                        session,
                        guild_id="100",
                        chest_id=chest["id"],
                        item_id=item["id"],
                        movement_type=MovementType.WITHDRAWAL,
                        amount=Decimal("1"),
                        observation=None,
                        idempotency_key="no-reason",
                        origin="test",
                        actor=actor,
                    )
                assert missing_reason.value.status_code == 422
                await session.rollback()
                with pytest.raises(HTTPException) as insufficient:
                    await services.record_movement(
                        session,
                        guild_id="100",
                        chest_id=chest["id"],
                        item_id=item["id"],
                        movement_type=MovementType.WITHDRAWAL,
                        amount=Decimal("1"),
                        observation="teste",
                        idempotency_key="insufficient",
                        origin="test",
                        actor=actor,
                    )
                assert insufficient.value.status_code == 409
                await session.rollback()
                balance = (await session.execute(select(ChestBalance))).scalar_one()
                assert balance.quantity == 0
                assert balance.sequence == 0
                assert (
                    await session.execute(select(ChestMovement))
                ).scalars().all() == []
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_chest_publication_cannot_remove_nonzero_link_and_versions_are_immutable():
    async def scenario():
        discover_domain_modules()
        engine, sessions = await database()
        try:
            async with sessions() as session:
                actor, chest, item, _ = await published_fixture(session)
                await services.record_movement(
                    session,
                    guild_id="100",
                    chest_id=chest["id"],
                    item_id=item["id"],
                    movement_type=MovementType.DEPOSIT,
                    amount=Decimal("1"),
                    observation=None,
                    idempotency_key="deposit",
                    origin="test",
                    actor=actor,
                )
                draft = await services.catalog_draft(session, guild_id="100")
                changed = await services.upsert_draft_link(
                    session,
                    guild_id="100",
                    chest_id=chest["id"],
                    item_id=item["id"],
                    active=False,
                    expected_revision=draft["revision"],
                    idempotency_key="unlink",
                    actor=actor,
                )
                with pytest.raises(HTTPException) as blocked:
                    await services.publish_catalog(
                        session,
                        guild_id="100",
                        expected_revision=changed["revision"],
                        expected_published_version=1,
                        grants=[],
                        idempotency_key="publish-2",
                        actor=actor,
                    )
                assert blocked.value.status_code == 422
                await session.rollback()
                version_one = (
                    await session.execute(select(ChestVersionLink))
                ).scalar_one()
                assert version_one.active is True
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_chest_tenant_isolation_rejects_cross_guild_resources():
    async def scenario():
        discover_domain_modules()
        engine, sessions = await database()
        try:
            async with sessions() as session:
                _, chest, item, _ = await published_fixture(session, "100")
                other = admin("200")
                draft = await services.catalog_draft(session, guild_id="200")
                with pytest.raises(HTTPException) as isolated:
                    await services.upsert_draft_link(
                        session,
                        guild_id="200",
                        chest_id=chest["id"],
                        item_id=item["id"],
                        active=True,
                        expected_revision=draft["revision"],
                        idempotency_key="cross",
                        actor=other,
                    )
                assert isolated.value.status_code == 422
        finally:
            await engine.dispose()

    asyncio.run(scenario())
