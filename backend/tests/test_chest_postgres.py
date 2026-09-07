"""Gates do Chest que exigem locks e trigger reais do PostgreSQL."""

import asyncio
import os
from decimal import Decimal
from uuid import uuid4

import app.models  # noqa: F401
import pytest
from app.db import Base
from app.domain_modules.chest import services
from app.domain_modules.chest.domain import MovementType
from app.domain_modules.chest.models import (
    ChestBalance,
    ChestMovement,
    ChestVersionLink,
)
from app.platform.registry import discover_domain_modules
from app.platform.schemas import ActorContextIn
from fastapi import HTTPException
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

POSTGRES_URL = os.getenv("YUNO_TEST_POSTGRES_URL")


def actor(correlation: str) -> ActorContextIn:
    return ActorContextIn(
        guild_id="100",
        user_id="900",
        discord_permissions=["administrator"],
        correlation_id=correlation,
    )


async def seed(session):
    draft = await services.catalog_draft(session, guild_id="100")
    settings = await services.save_settings(
        session,
        guild_id="100",
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
            "panel_description": "Teste PostgreSQL.",
        },
        idempotency_key="pg-settings",
        actor=actor("pg-settings"),
    )
    chest = await services.upsert_draft_chest(
        session,
        guild_id="100",
        chest_id=None,
        name="Central",
        active=True,
        position=0,
        expected_revision=settings["revision"],
        idempotency_key="pg-chest",
        actor=actor("pg-chest"),
    )
    item = await services.upsert_draft_item(
        session,
        guild_id="100",
        item_id=None,
        name="Ferro",
        unit="kg",
        active=True,
        position=0,
        expected_revision=chest["revision"],
        idempotency_key="pg-item",
        actor=actor("pg-item"),
    )
    link = await services.upsert_draft_link(
        session,
        guild_id="100",
        chest_id=chest["id"],
        item_id=item["id"],
        active=True,
        expected_revision=item["revision"],
        idempotency_key="pg-link",
        actor=actor("pg-link"),
    )
    await services.publish_catalog(
        session,
        guild_id="100",
        expected_revision=link["revision"],
        expected_published_version=0,
        grants=[],
        idempotency_key="pg-publish",
        actor=actor("pg-publish"),
    )
    await services.record_movement(
        session,
        guild_id="100",
        chest_id=chest["id"],
        item_id=item["id"],
        movement_type=MovementType.DEPOSIT,
        amount=Decimal("5"),
        observation=None,
        idempotency_key="pg-deposit",
        origin="test",
        actor=actor("pg-deposit"),
    )
    return chest, item


@pytest.mark.skipif(
    not POSTGRES_URL,
    reason="Defina YUNO_TEST_POSTGRES_URL para o gate concorrente do Chest.",
)
def test_chest_postgres_concurrent_withdrawal_and_append_only_trigger():
    async def scenario():
        assert POSTGRES_URL is not None
        discover_domain_modules()
        schema = f"yuno_chest_test_{uuid4().hex}"
        admin_engine = create_async_engine(POSTGRES_URL)
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(
            POSTGRES_URL, connect_args={"server_settings": {"search_path": schema}}
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
                await connection.execute(
                    text("""
                    CREATE FUNCTION yuno_chest_movement_immutable() RETURNS trigger AS $$
                    BEGIN RAISE EXCEPTION 'chest_movements is append-only'; END;
                    $$ LANGUAGE plpgsql
                """)
                )
                await connection.execute(
                    text("""
                    CREATE TRIGGER trg_chest_movements_immutable
                    BEFORE UPDATE OR DELETE ON chest_movements
                    FOR EACH ROW EXECUTE FUNCTION yuno_chest_movement_immutable()
                """)
                )
            async with sessions() as session:
                chest, item = await seed(session)

            async def withdraw(index: int):
                async with sessions() as session:
                    return await services.record_movement(
                        session,
                        guild_id="100",
                        chest_id=chest["id"],
                        item_id=item["id"],
                        movement_type=MovementType.WITHDRAWAL,
                        amount=Decimal("5"),
                        observation="Concorrencia",
                        idempotency_key=f"pg-withdraw-{index}",
                        origin="test",
                        actor=actor(f"pg-withdraw-{index}"),
                    )

            outcomes = await asyncio.gather(
                withdraw(1), withdraw(2), return_exceptions=True
            )
            assert (
                len([value for value in outcomes if isinstance(value, ChestMovement)])
                == 1
            )
            failures = [value for value in outcomes if isinstance(value, HTTPException)]
            assert len(failures) == 1 and failures[0].status_code == 409
            async with sessions() as session:
                await services.record_movement(
                    session,
                    guild_id="100",
                    chest_id=chest["id"],
                    item_id=item["id"],
                    movement_type=MovementType.ADJUSTMENT_CREDIT,
                    amount=Decimal("3"),
                    observation="Preparar corrida",
                    idempotency_key="pg-race-credit",
                    origin="test",
                    actor=actor("pg-race-credit"),
                )
                draft = await services.catalog_draft(session, guild_id="100")
                changed = await services.upsert_draft_link(
                    session,
                    guild_id="100",
                    chest_id=chest["id"],
                    item_id=item["id"],
                    active=False,
                    expected_revision=draft["revision"],
                    idempotency_key="pg-race-unlink",
                    actor=actor("pg-race-unlink"),
                )

            async def publish_removed():
                async with sessions() as session:
                    return await services.publish_catalog(
                        session,
                        guild_id="100",
                        expected_revision=changed["revision"],
                        expected_published_version=1,
                        grants=[],
                        idempotency_key="pg-race-publish",
                        actor=actor("pg-race-publish"),
                    )

            async def withdraw_during_publish():
                async with sessions() as session:
                    return await services.record_movement(
                        session,
                        guild_id="100",
                        chest_id=chest["id"],
                        item_id=item["id"],
                        movement_type=MovementType.WITHDRAWAL,
                        amount=Decimal("3"),
                        observation="Corrida com publicacao",
                        idempotency_key="pg-race-withdraw",
                        origin="test",
                        actor=actor("pg-race-withdraw"),
                    )

            race = await asyncio.gather(
                publish_removed(), withdraw_during_publish(), return_exceptions=True
            )
            assert any(isinstance(value, ChestMovement) for value in race)
            async with sessions() as session:
                balance = (await session.execute(select(ChestBalance))).scalar_one()
                assert balance.quantity == 0
                links = list(
                    (
                        await session.execute(
                            select(ChestVersionLink).order_by(
                                ChestVersionLink.config_version_id
                            )
                        )
                    ).scalars()
                )
                assert links[0].active is True
                if len(links) > 1:
                    assert links[-1].active is False
                movement = (
                    (
                        await session.execute(
                            select(ChestMovement).order_by(ChestMovement.sequence)
                        )
                    )
                    .scalars()
                    .first()
                )
                with pytest.raises(DBAPIError):
                    await session.execute(
                        update(ChestMovement)
                        .where(ChestMovement.id == movement.id)
                        .values(observation="alterado")
                    )
                    await session.commit()
                await session.rollback()
                with pytest.raises(DBAPIError):
                    await session.execute(
                        delete(ChestMovement).where(ChestMovement.id == movement.id)
                    )
                    await session.commit()
        finally:
            await engine.dispose()
            async with admin_engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin_engine.dispose()

    asyncio.run(scenario())
