"""Copia verificavel do banco SQLite de teste para um PostgreSQL vazio.

O destino deve estar migrado para o mesmo Alembic head da origem. URLs ficam
somente nas variaveis YUNO_SOURCE_DATABASE_URL e YUNO_TARGET_DATABASE_URL.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import MetaData, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

SKIPPED_TABLES = frozenset({"alembic_version"})
BATCH_SIZE = 500


def _normalized(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(key): _normalized(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_normalized(item) for item in value]
    return value


def _digest(rows: list[dict[str, Any]]) -> str:
    checksum = hashlib.sha256()
    for row in rows:
        encoded = json.dumps(
            _normalized(row),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        checksum.update(encoded)
        checksum.update(b"\n")
    return checksum.hexdigest()


async def _metadata(connection: AsyncConnection) -> MetaData:
    metadata = MetaData()
    await connection.run_sync(metadata.reflect)
    return metadata


async def _rows(connection: AsyncConnection, table) -> list[dict[str, Any]]:
    primary_keys = list(table.primary_key.columns)
    query = select(table)
    if primary_keys:
        query = query.order_by(*primary_keys)
    return [dict(row) for row in (await connection.execute(query)).mappings().all()]


async def _reset_sequences(connection: AsyncConnection, metadata: MetaData) -> None:
    for table in metadata.sorted_tables:
        for column in table.primary_key.columns:
            try:
                python_type = column.type.python_type
            except (AttributeError, NotImplementedError):
                continue
            if python_type is not int:
                continue
            sequence = await connection.scalar(
                text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
                {"table_name": table.name, "column_name": column.name},
            )
            if not sequence:
                continue
            maximum = await connection.scalar(select(func.max(column)))
            value = int(maximum or 1)
            await connection.execute(
                text("SELECT setval(CAST(:sequence AS regclass), :value, :called)"),
                {"sequence": sequence, "value": value, "called": maximum is not None},
            )


async def copy_database(source_url: str, target_url: str) -> dict[str, dict[str, Any]]:
    source_engine = create_async_engine(source_url)
    target_engine = create_async_engine(target_url)
    report: dict[str, dict[str, Any]] = {}
    try:
        async with source_engine.connect() as source, target_engine.begin() as target:
            source_metadata = await _metadata(source)
            target_metadata = await _metadata(target)
            for source_table in source_metadata.sorted_tables:
                if source_table.name in SKIPPED_TABLES:
                    continue
                target_table = target_metadata.tables.get(source_table.name)
                if target_table is None:
                    raise RuntimeError(
                        f"Tabela ausente no PostgreSQL: {source_table.name}"
                    )
                source_columns = tuple(source_table.columns.keys())
                target_columns = tuple(target_table.columns.keys())
                if set(source_columns) != set(target_columns):
                    raise RuntimeError(
                        f"Colunas divergentes em {source_table.name}: "
                        f"SQLite={source_columns}, PostgreSQL={target_columns}"
                    )
                existing = int(
                    await target.scalar(select(func.count()).select_from(target_table))
                    or 0
                )
                if existing:
                    raise RuntimeError(
                        f"Destino nao esta vazio: {source_table.name} possui {existing} linha(s)."
                    )
                source_rows = await _rows(source, source_table)
                for offset in range(0, len(source_rows), BATCH_SIZE):
                    await target.execute(
                        insert(target_table), source_rows[offset : offset + BATCH_SIZE]
                    )
                target_rows = await _rows(target, target_table)
                source_digest = _digest(source_rows)
                target_digest = _digest(target_rows)
                if (
                    len(source_rows) != len(target_rows)
                    or source_digest != target_digest
                ):
                    raise RuntimeError(
                        f"Verificacao divergente em {source_table.name}: "
                        f"count {len(source_rows)}/{len(target_rows)}, "
                        f"sha256 {source_digest}/{target_digest}"
                    )
                report[source_table.name] = {
                    "rows": len(source_rows),
                    "sha256": source_digest,
                }
            await _reset_sequences(target, target_metadata)
    finally:
        await source_engine.dispose()
        await target_engine.dispose()
    return report


async def main() -> None:
    source_url = os.getenv("YUNO_SOURCE_DATABASE_URL", "")
    target_url = os.getenv("YUNO_TARGET_DATABASE_URL", "")
    if not source_url.startswith("sqlite+aiosqlite:"):
        raise SystemExit("YUNO_SOURCE_DATABASE_URL deve apontar para SQLite async.")
    if not target_url.startswith("postgresql+asyncpg:"):
        raise SystemExit("YUNO_TARGET_DATABASE_URL deve apontar para PostgreSQL async.")
    report = await copy_database(source_url, target_url)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    print(f"COPY_VERIFIED_TABLES={len(report)}")


if __name__ == "__main__":
    asyncio.run(main())
