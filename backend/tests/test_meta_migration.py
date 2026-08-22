import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
PYTHON = Path(sys.executable)


def _alembic(database: Path, revision: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{database.as_posix()}"
    subprocess.run(
        [str(PYTHON), "-m", "alembic", "-c", "alembic.ini", "upgrade", revision],
        cwd=BACKEND,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_meta_migration_on_empty_sqlite(tmp_path: Path) -> None:
    database = tmp_path / "empty.db"
    _alembic(database, "head")
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "c5d6e7f8a9b0"
        assert len([name for name in tables if name.startswith("meta_")]) == 11
        assert "farm_weekly_goals" not in tables


def test_representative_migration_removes_only_legacy_meta_and_preserves_tickets(tmp_path: Path) -> None:
    database = tmp_path / "representative.db"
    _alembic(database, "b4c5d6e7f8a9")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO guild_configs "
            "(guild_id, admin_role_ids, modules, command_permissions, messages, settings) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "guild-1",
                "[]",
                json.dumps({"meta": True, "ticket": False}),
                json.dumps({"meta.editar": {"role_ids": ["1"]}, "ticket.abrir": {}}),
                json.dumps({"meta": {"title": "antiga"}, "ticket": {"title": "ok"}}),
                json.dumps({"meta": {"channel_id": "9"}, "ticket": {"channel_id": "8"}}),
            ),
        )
        connection.execute(
            "INSERT INTO module_config_states "
            "(guild_id, module_key, schema_version, draft_data, published_data, draft_revision, published_revision) "
            "VALUES (?, 'meta', 1, '{}', '{}', 0, 0)",
            ("guild-1",),
        )
        connection.execute(
            "INSERT INTO farm_weekly_goals (guild_id, week_id, items, active) VALUES (?, ?, ?, 1)",
            ("guild-1", "2026-W30", json.dumps([{"name": "Item", "quantity": 10}])),
        )
        cursor = connection.execute(
            "INSERT INTO farm_tickets "
            "(guild_id, week_id, user_id, member_name, status, goal_items, progress) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "guild-1",
                "2026-W30",
                "member-1",
                "Ana",
                "aberto",
                json.dumps([{"name": "Item", "quantity": 10}]),
                json.dumps({"percent": 50}),
            ),
        )
        ticket_id = cursor.lastrowid
        connection.execute(
            "INSERT INTO farm_ticket_entries "
            "(ticket_id, guild_id, \"values\", proof_channel_id, proof_message_id, proof_url, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticket_id, "guild-1", json.dumps({"Item": 5}), "10", "11", "https://example.com/p.png", "registrado"),
        )
        connection.execute(
            "INSERT INTO farm_ticket_actions (ticket_id, guild_id, action, payload, log_attempts) VALUES (?, ?, ?, ?, 0)",
            (ticket_id, "guild-1", "ticket_aberto", "{}"),
        )
        connection.commit()

    _alembic(database, "head")
    with sqlite3.connect(database) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "farm_weekly_goals" not in tables
        assert connection.execute("SELECT COUNT(*) FROM module_config_states WHERE module_key = 'meta'").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM farm_tickets").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM farm_ticket_entries").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM farm_ticket_actions").fetchone()[0] == 1
        modules, permissions, messages, settings = connection.execute(
            "SELECT modules, command_permissions, messages, settings FROM guild_configs WHERE guild_id = 'guild-1'"
        ).fetchone()
        assert json.loads(modules) == {"ticket": False}
        assert json.loads(permissions) == {"ticket.abrir": {}}
        assert json.loads(messages) == {"ticket": {"title": "ok"}}
        assert json.loads(settings) == {"ticket": {"channel_id": "8"}}


def test_meta_schema_has_no_progress_or_surplus_storage(tmp_path: Path) -> None:
    database = tmp_path / "meta-shape.db"
    _alembic(database, "head")
    with sqlite3.connect(database) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'meta_%'"
            )
        ]
        columns = {
            row[1]
            for table in tables
            for row in connection.execute(f'PRAGMA table_info("{table}")')
        }
    assert not {"progress", "progress_value", "surplus", "excess"} & columns
