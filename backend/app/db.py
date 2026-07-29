from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_async_engine(settings.database_url, echo=settings.app_env == "development")
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def create_database() -> None:
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_compat_columns(conn)


async def _ensure_compat_columns(conn) -> None:
    columns = {
        "folder_channel_id": "VARCHAR(32)",
        "folder_slot": "INTEGER",
        "game_id": "VARCHAR(32)",
        "folder_nickname": "VARCHAR(120)",
    }
    if conn.dialect.name == "sqlite":
        result = await conn.execute(text("PRAGMA table_info(farm_tickets)"))
        existing = {row[1] for row in result.fetchall()}
        for name, definition in columns.items():
            if name not in existing:
                await conn.execute(text(f"ALTER TABLE farm_tickets ADD COLUMN {name} {definition}"))
        return
    if conn.dialect.name == "postgresql":
        for name, definition in columns.items():
            await conn.execute(text(f"ALTER TABLE farm_tickets ADD COLUMN IF NOT EXISTS {name} {definition}"))
