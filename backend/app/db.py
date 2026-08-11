import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import JSON

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


JsonType = JSON().with_variant(JSONB, "postgresql")


settings = get_settings()
engine = create_async_engine(settings.database_url, echo=settings.app_env == "development")
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
# Revisao da migracao "baseline schema": reflete o schema criado por
# Base.metadata.create_all antes do Alembic existir (sem as colunas de
# pasta de membro do farm ticket, adicionadas depois via migracao separada).
LEGACY_BASELINE_REVISION = "b83c59e0158e"


def _alembic_config() -> Config:
    return Config(str(BACKEND_ROOT / "alembic.ini"))


def _inspect_current_state(sync_conn) -> tuple[str | None, bool]:
    current_revision = MigrationContext.configure(sync_conn).get_current_revision()
    has_legacy_tables = inspect(sync_conn).has_table("licenses")
    return current_revision, has_legacy_tables


async def create_database() -> None:
    """Coloca o banco em dia com as migracoes do Alembic (`backend/migrations/`).

    Bancos sem `alembic_version` mas com tabelas ja existentes vieram do antigo
    `Base.metadata.create_all` e sao adotados via `stamp` na baseline, sem
    reexecutar o CREATE TABLE de algo que ja existe em producao. Dali em diante
    e so `upgrade head`, igual a qualquer banco novo.
    """
    async with engine.connect() as conn:
        current_revision, has_legacy_tables = await conn.run_sync(_inspect_current_state)

    config = _alembic_config()
    if current_revision is None and has_legacy_tables:
        await asyncio.to_thread(command.stamp, config, LEGACY_BASELINE_REVISION)
    await asyncio.to_thread(command.upgrade, config, "head")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
