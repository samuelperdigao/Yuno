import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ParceriaConfig:
    guild_id: str
    parceria_category_id: int | None
    parceria_registrar_channel_id: int
    parceria_ativas_channel_id: int
    parceria_panel_message_id: int | None


class ParceriasRepository:
    def __init__(self, database_path: str) -> None:
        self.database_path = Path(database_path)

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    async def get_config(self, guild_id: int) -> ParceriaConfig | None:
        return await asyncio.to_thread(self._get_config_sync, str(guild_id))

    async def upsert_config(
        self,
        *,
        guild_id: int,
        category_id: int | None,
        registrar_channel_id: int,
        ativas_channel_id: int,
        panel_message_id: int | None,
    ) -> None:
        await asyncio.to_thread(
            self._upsert_config_sync,
            str(guild_id),
            category_id,
            registrar_channel_id,
            ativas_channel_id,
            panel_message_id,
        )

    async def find_by_name(self, guild_id: int, nome_familia: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._find_by_name_sync, str(guild_id), nome_familia)

    async def name_exists_for_other(self, guild_id: int, nome_familia: str, parceria_id: int) -> bool:
        return await asyncio.to_thread(self._name_exists_for_other_sync, str(guild_id), nome_familia, parceria_id)

    async def list_active(self, guild_id: int) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_active_sync, str(guild_id))

    async def get(self, parceria_id: int) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get_sync, parceria_id)

    async def create_parceria(
        self,
        *,
        guild_id: int,
        nome_familia: str,
        produto: str,
        contato_01: str | None,
        contato_02: str | None,
        mensagem_lista_id: int,
        nome_arquivo_imagem: str,
        registrado_por: int,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._create_parceria_sync,
            str(guild_id),
            nome_familia,
            produto,
            contato_01,
            contato_02,
            mensagem_lista_id,
            nome_arquivo_imagem,
            registrado_por,
        )

    async def update_details(
        self,
        *,
        parceria_id: int,
        nome_familia: str,
        produto: str,
        contato_01: str | None,
        contato_02: str | None,
    ) -> dict[str, Any] | None:
        return await asyncio.to_thread(
            self._update_details_sync,
            parceria_id,
            nome_familia,
            produto,
            contato_01,
            contato_02,
        )

    async def update_image(self, *, parceria_id: int, nome_arquivo_imagem: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._update_image_sync, parceria_id, nome_arquivo_imagem)

    async def deactivate(self, parceria_id: int) -> None:
        await asyncio.to_thread(self._deactivate_sync, parceria_id)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_sync(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS parcerias (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    nome_familia TEXT NOT NULL COLLATE NOCASE,
                    produto TEXT NOT NULL,
                    contato_01 TEXT,
                    contato_02 TEXT,
                    mensagem_lista_id INTEGER NOT NULL,
                    nome_arquivo_imagem TEXT NOT NULL,
                    registrado_por INTEGER NOT NULL,
                    criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
                    atualizado_em TEXT,
                    ativo INTEGER DEFAULT 1,
                    UNIQUE (guild_id, nome_familia)
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS parcerias_config (
                    guild_id TEXT PRIMARY KEY,
                    parceria_category_id INTEGER,
                    parceria_registrar_channel_id INTEGER NOT NULL,
                    parceria_ativas_channel_id INTEGER NOT NULL,
                    parceria_panel_message_id INTEGER
                );
                """
            )

    def _get_config_sync(self, guild_id: str) -> ParceriaConfig | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM parcerias_config WHERE guild_id = ?", (guild_id,)).fetchone()
        if not row:
            return None
        return ParceriaConfig(
            guild_id=row["guild_id"],
            parceria_category_id=row["parceria_category_id"],
            parceria_registrar_channel_id=row["parceria_registrar_channel_id"],
            parceria_ativas_channel_id=row["parceria_ativas_channel_id"],
            parceria_panel_message_id=row["parceria_panel_message_id"],
        )

    def _upsert_config_sync(
        self,
        guild_id: str,
        category_id: int | None,
        registrar_channel_id: int,
        ativas_channel_id: int,
        panel_message_id: int | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO parcerias_config (
                    guild_id,
                    parceria_category_id,
                    parceria_registrar_channel_id,
                    parceria_ativas_channel_id,
                    parceria_panel_message_id
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    parceria_category_id = excluded.parceria_category_id,
                    parceria_registrar_channel_id = excluded.parceria_registrar_channel_id,
                    parceria_ativas_channel_id = excluded.parceria_ativas_channel_id,
                    parceria_panel_message_id = excluded.parceria_panel_message_id
                """,
                (guild_id, category_id, registrar_channel_id, ativas_channel_id, panel_message_id),
            )

    def _find_by_name_sync(self, guild_id: str, nome_familia: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM parcerias WHERE guild_id = ? AND nome_familia = ? COLLATE NOCASE",
                (guild_id, nome_familia),
            ).fetchone()
        return _row_to_dict(row)

    def _name_exists_for_other_sync(self, guild_id: str, nome_familia: str, parceria_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM parcerias
                WHERE guild_id = ? AND nome_familia = ? COLLATE NOCASE AND id != ?
                LIMIT 1
                """,
                (guild_id, nome_familia, parceria_id),
            ).fetchone()
        return row is not None

    def _list_active_sync(self, guild_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM parcerias
                WHERE guild_id = ? AND ativo = 1
                ORDER BY nome_familia COLLATE NOCASE
                """,
                (guild_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _get_sync(self, parceria_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM parcerias WHERE id = ?", (parceria_id,)).fetchone()
        return _row_to_dict(row)

    def _create_parceria_sync(
        self,
        guild_id: str,
        nome_familia: str,
        produto: str,
        contato_01: str | None,
        contato_02: str | None,
        mensagem_lista_id: int,
        nome_arquivo_imagem: str,
        registrado_por: int,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO parcerias (
                    guild_id,
                    nome_familia,
                    produto,
                    contato_01,
                    contato_02,
                    mensagem_lista_id,
                    nome_arquivo_imagem,
                    registrado_por
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    nome_familia,
                    produto,
                    _optional_text(contato_01),
                    _optional_text(contato_02),
                    mensagem_lista_id,
                    nome_arquivo_imagem,
                    registrado_por,
                ),
            )
            row = conn.execute("SELECT * FROM parcerias WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return dict(row)

    def _update_details_sync(
        self,
        parceria_id: int,
        nome_familia: str,
        produto: str,
        contato_01: str | None,
        contato_02: str | None,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE parcerias
                SET nome_familia = ?,
                    produto = ?,
                    contato_01 = ?,
                    contato_02 = ?,
                    atualizado_em = ?
                WHERE id = ?
                """,
                (
                    nome_familia,
                    produto,
                    _optional_text(contato_01),
                    _optional_text(contato_02),
                    _now_iso(),
                    parceria_id,
                ),
            )
            row = conn.execute("SELECT * FROM parcerias WHERE id = ?", (parceria_id,)).fetchone()
        return _row_to_dict(row)

    def _update_image_sync(self, parceria_id: int, nome_arquivo_imagem: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE parcerias
                SET nome_arquivo_imagem = ?,
                    atualizado_em = ?
                WHERE id = ?
                """,
                (nome_arquivo_imagem, _now_iso(), parceria_id),
            )
            row = conn.execute("SELECT * FROM parcerias WHERE id = ?", (parceria_id,)).fetchone()
        return _row_to_dict(row)

    def _deactivate_sync(self, parceria_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE parcerias SET ativo = 0, atualizado_em = ? WHERE id = ?",
                (_now_iso(), parceria_id),
            )


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def _optional_text(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
