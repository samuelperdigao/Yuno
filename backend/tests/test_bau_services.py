import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import app.models  # noqa: E402,F401
from app.db import Base  # noqa: E402
from app.domain_modules.bau import services  # noqa: E402
from app.domain_modules.bau.models import BauCategory, BauItem, BauStock  # noqa: E402
from app.domain_modules.bau.schemas import BauConfig  # noqa: E402
from app.platform.models import (  # noqa: E402
    ModuleConfigVersion,
    ModuleInstance,
    ModuleLifecycle,
    RuntimeMode,
)
from app.platform.registry import discover_domain_modules  # noqa: E402


async def _database():
    discover_domain_modules()
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    return engine, sessions


async def _configure(session, guild_id: str = "100", *, log_channel_id: str = "1002") -> None:
    config = BauConfig(panel_channel_id="1001", log_channel_id=log_channel_id).model_dump(mode="json")
    instance = ModuleInstance(
        guild_id=guild_id,
        module_key="bau",
        lifecycle=ModuleLifecycle.active,
        runtime_mode=RuntimeMode.domain,
        contract_version=1,
        domain_version="1.0.0",
    )
    session.add(instance)
    await session.flush()
    version = ModuleConfigVersion(
        module_instance_id=instance.id,
        guild_id=guild_id,
        module_key="bau",
        version=1,
        schema_version=1,
        data=config,
        content_hash="x",
        published_by="1",
    )
    session.add(version)
    await session.flush()
    instance.published_config_version_id = version.id
    await session.commit()


async def _seeded_item(session, guild_id: str = "100") -> str:
    await services.seed_default_catalog_if_empty(
        session, guild_id=guild_id, actor_id="1", correlation_id="seed-1"
    )
    item = (
        await session.execute(select(BauItem).where(BauItem.guild_id == guild_id))
    ).scalars().first()
    return item.id


def test_seed_default_catalog_is_idempotent() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                created_first = await services.seed_default_catalog_if_empty(
                    session, guild_id="100", actor_id="1", correlation_id="c1"
                )
                assert created_first > 0
                categories_after_first = (
                    await session.execute(select(BauCategory).where(BauCategory.guild_id == "100"))
                ).scalars().all()
                # remove one category to prove seeding never overwrites existing data
                await session.delete(categories_after_first[0])
                await session.commit()

                created_second = await services.seed_default_catalog_if_empty(
                    session, guild_id="100", actor_id="1", correlation_id="c2"
                )
                assert created_second == 0
                remaining = (
                    await session.execute(select(BauCategory).where(BauCategory.guild_id == "100"))
                ).scalars().all()
                assert len(remaining) == len(categories_after_first) - 1
        finally:
            await engine.dispose()

    import asyncio

    asyncio.run(run())


def test_add_rename_remove_category_and_item() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                category = await services.add_category(
                    session, guild_id="100", actor_id="1", correlation_id="c1", name="  Materiais  "
                )
                assert category.name == "Materiais"

                with pytest.raises(HTTPException) as exc:
                    await services.add_category(
                        session, guild_id="100", actor_id="1", correlation_id="c2", name="Materiais"
                    )
                assert exc.value.status_code == 409

                renamed = await services.rename_category(
                    session,
                    guild_id="100",
                    actor_id="1",
                    correlation_id="c3",
                    name="Materiais",
                    new_name="Recursos",
                )
                assert renamed.name == "Recursos"

                item = await services.add_item(
                    session,
                    guild_id="100",
                    actor_id="1",
                    correlation_id="c4",
                    category_name="Recursos",
                    name="Ferro",
                )
                stock = (
                    await session.execute(select(BauStock).where(BauStock.item_id == item.id))
                ).scalar_one()
                assert stock.quantity == 0

                renamed_item = await services.rename_item(
                    session,
                    guild_id="100",
                    actor_id="1",
                    correlation_id="c5",
                    name="Ferro",
                    new_name="Ferro Bruto",
                )
                assert renamed_item.name == "Ferro Bruto"

                await services.remove_item(
                    session, guild_id="100", actor_id="1", correlation_id="c6", name="Ferro Bruto"
                )
                remaining_items = (
                    await session.execute(select(BauItem).where(BauItem.guild_id == "100"))
                ).scalars().all()
                assert remaining_items == []

                await services.remove_category(
                    session, guild_id="100", actor_id="1", correlation_id="c7", name="Recursos"
                )
                remaining_categories = (
                    await session.execute(select(BauCategory).where(BauCategory.guild_id == "100"))
                ).scalars().all()
                assert remaining_categories == []
        finally:
            await engine.dispose()

    import asyncio

    asyncio.run(run())


def test_apply_movements_updates_stock_and_bumps_generation() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session)
                item_id = await _seeded_item(session)
                changes = await services.apply_movements(
                    session,
                    guild_id="100",
                    actor_id="500",
                    correlation_id="corr-1",
                    items=[(item_id, "10")],
                )
                assert changes[0]["before"] == 0
                assert changes[0]["after"] == 10

                stock = (
                    await session.execute(select(BauStock).where(BauStock.item_id == item_id))
                ).scalar_one()
                assert stock.quantity == 10
                assert stock.generation == 1

                await services.apply_movements(
                    session,
                    guild_id="100",
                    actor_id="500",
                    correlation_id="corr-2",
                    items=[(item_id, "-4")],
                )
                await session.refresh(stock)
                assert stock.quantity == 6
                assert stock.generation == 2
        finally:
            await engine.dispose()

    import asyncio

    asyncio.run(run())


def test_apply_movements_rejects_negative_stock() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session)
                item_id = await _seeded_item(session)
                with pytest.raises(HTTPException) as exc:
                    await services.apply_movements(
                        session,
                        guild_id="100",
                        actor_id="500",
                        correlation_id="corr-1",
                        items=[(item_id, "-1")],
                    )
                assert exc.value.status_code == 422
        finally:
            await engine.dispose()

    import asyncio

    asyncio.run(run())


def test_apply_movements_requires_at_least_one_effective_change() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session)
                item_id = await _seeded_item(session)
                with pytest.raises(HTTPException) as exc:
                    await services.apply_movements(
                        session,
                        guild_id="100",
                        actor_id="500",
                        correlation_id="corr-1",
                        items=[(item_id, "")],
                    )
                assert exc.value.status_code == 422
        finally:
            await engine.dispose()

    import asyncio

    asyncio.run(run())


def test_clear_stock_resets_all_quantities() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session)
                item_id = await _seeded_item(session)
                await services.apply_movements(
                    session, guild_id="100", actor_id="500", correlation_id="corr-1",
                    items=[(item_id, "25")],
                )
                reset_count = await services.clear_stock(
                    session, guild_id="100", actor_id="1", correlation_id="corr-2"
                )
                assert reset_count == 1
                stock = (
                    await session.execute(select(BauStock).where(BauStock.item_id == item_id))
                ).scalar_one()
                assert stock.quantity == 0
                assert stock.generation == 2

                # nada para limpar na segunda chamada
                assert await services.clear_stock(
                    session, guild_id="100", actor_id="1", correlation_id="corr-3"
                ) == 0
        finally:
            await engine.dispose()

    import asyncio

    asyncio.run(run())


def test_list_catalog_and_stock_summary() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await services.seed_default_catalog_if_empty(
                    session, guild_id="100", actor_id="1", correlation_id="c1"
                )
                catalog = await services.list_catalog(session, guild_id="100")
                assert len(catalog) >= 10
                assert all("items" in category for category in catalog)

                summary = await services.stock_summary(session, guild_id="100")
                assert len(summary) == len(catalog)
                assert all(item["total_quantity"] == 0 for item in summary)
        finally:
            await engine.dispose()

    import asyncio

    asyncio.run(run())
