"""remove legacy farm tickets and the unreleased farm domain

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-08-22

Etapa destrutiva. Exige zero ticket legado ativo, equivalencia integral do
arquivo append-only e ausencia de dados no modulo ``farm`` nunca lancado.
Rollback de dados e feito pelo backup PostgreSQL validado antes do deploy.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f8a9b0c1d2e3"
down_revision: str | Sequence[str] | None = "e7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_ACTIVE_STATUSES = ("reservado", "aberto", "revisao")
UNRELEASED_FARM_TABLES = (
    "farm_products",
    "farm_templates",
    "farm_template_items",
    "farm_cycles",
    "farm_cycle_goals",
    "farm_cycle_participants",
    "farm_cycle_tickets",
    "farm_submissions",
    "farm_submission_items",
    "farm_proofs",
    "farm_reviews",
)


def _json() -> sa.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _canonical(payload: dict) -> tuple[dict, str]:
    normalized = json.loads(json.dumps(payload, sort_keys=True, default=str))
    encoded = json.dumps(
        normalized, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return normalized, hashlib.sha256(encoded).hexdigest()


def _archive_row(
    bind,
    archive,
    *,
    namespace: str,
    source_id: str,
    guild_id: str,
    payload: dict,
) -> None:
    normalized, checksum = _canonical(payload)
    existing = bind.execute(
        sa.select(archive.c.payload, archive.c.checksum_sha256).where(
            archive.c.source_namespace == namespace,
            archive.c.source_id == source_id,
        )
    ).mappings().one_or_none()
    if existing is not None:
        archived_payload = existing["payload"]
        if isinstance(archived_payload, str):
            archived_payload = json.loads(archived_payload)
        archived_normalized, archived_checksum = _canonical(archived_payload)
        if (
            archived_normalized != normalized
            or existing["checksum_sha256"] != checksum
            or archived_checksum != checksum
        ):
            raise RuntimeError(
                f"Arquivo legado divergente para {namespace}:{source_id}."
            )
        return
    bind.execute(
        sa.insert(archive).values(
            id=str(uuid4()),
            source_namespace=namespace,
            source_id=source_id,
            guild_id=guild_id,
            payload=normalized,
            checksum_sha256=checksum,
        )
    )


def _archive_and_validate_legacy(bind, tables: set[str]) -> None:
    archive = sa.table(
        "farm_ticket_v2_legacy_archive",
        sa.column("id", sa.String()),
        sa.column("source_namespace", sa.String()),
        sa.column("source_id", sa.String()),
        sa.column("guild_id", sa.String()),
        sa.column("payload", _json()),
        sa.column("checksum_sha256", sa.String()),
    )
    if "farm_tickets" in tables:
        placeholders = ", ".join(f"'{item}'" for item in LEGACY_ACTIVE_STATUSES)
        active = int(
            bind.scalar(
                sa.text(
                    "SELECT COUNT(*) FROM farm_tickets "
                    f"WHERE deleted_at IS NULL AND status IN ({placeholders})"
                )
            )
            or 0
        )
        if active:
            raise RuntimeError(
                f"Cutover bloqueado: {active} ticket(s) legado(s) ainda ativo(s)."
            )
        tickets = list(
            bind.execute(sa.text("SELECT * FROM farm_tickets ORDER BY id")).mappings()
        )
        for ticket in tickets:
            entries = (
                list(
                    bind.execute(
                        sa.text(
                            "SELECT * FROM farm_ticket_entries "
                            "WHERE ticket_id = :ticket_id ORDER BY id"
                        ),
                        {"ticket_id": ticket["id"]},
                    ).mappings()
                )
                if "farm_ticket_entries" in tables
                else []
            )
            actions = (
                list(
                    bind.execute(
                        sa.text(
                            "SELECT * FROM farm_ticket_actions "
                            "WHERE ticket_id = :ticket_id ORDER BY id"
                        ),
                        {"ticket_id": ticket["id"]},
                    ).mappings()
                )
                if "farm_ticket_actions" in tables
                else []
            )
            _archive_row(
                bind,
                archive,
                namespace="yuno.legacy.farm_tickets.cutover",
                source_id=str(ticket["id"]),
                guild_id=str(ticket["guild_id"]),
                payload={
                    "ticket": dict(ticket),
                    "entries": [dict(row) for row in entries],
                    "actions": [dict(row) for row in actions],
                },
            )
        archived = int(
            bind.scalar(
                sa.select(sa.func.count()).select_from(archive).where(
                    archive.c.source_namespace == "yuno.legacy.farm_tickets.cutover"
                )
            )
            or 0
        )
        if archived != len(tickets):
            raise RuntimeError(
                f"Arquivo de tickets incompleto: {archived}/{len(tickets)}."
            )

    if "farm_ticket_configs" in tables:
        configs = list(
            bind.execute(
                sa.text("SELECT * FROM farm_ticket_configs ORDER BY id")
            ).mappings()
        )
        for config in configs:
            _archive_row(
                bind,
                archive,
                namespace="yuno.legacy.farm_ticket_configs",
                source_id=str(config["id"]),
                guild_id=str(config["guild_id"]),
                payload={"config": dict(config)},
            )

    if "farm_ticket_actions" in tables:
        orphan_actions = list(
            bind.execute(
                sa.text(
                    "SELECT * FROM farm_ticket_actions "
                    "WHERE ticket_id IS NULL ORDER BY id"
                )
            ).mappings()
        )
        for action in orphan_actions:
            _archive_row(
                bind,
                archive,
                namespace="yuno.legacy.farm_ticket_actions.orphan",
                source_id=str(action["id"]),
                guild_id=str(action["guild_id"]),
                payload={"action": dict(action)},
            )


def _remove_unreleased_farm_platform_state(bind, tables: set[str]) -> None:
    for table in UNRELEASED_FARM_TABLES:
        if table in tables:
            count = int(bind.scalar(sa.text(f"SELECT COUNT(*) FROM {table}")) or 0)
            if count:
                raise RuntimeError(
                    f"Cutover bloqueado: modulo farm nao lancado possui {count} "
                    f"linha(s) em {table}."
                )

    if "module_instances" not in tables:
        return
    non_inactive = int(
        bind.scalar(
            sa.text(
                "SELECT COUNT(*) FROM module_instances "
                "WHERE module_key = 'farm' AND lifecycle <> 'inactive'"
            )
        )
        or 0
    )
    if non_inactive:
        raise RuntimeError("Cutover bloqueado: modulo farm ainda esta ativo.")
    guarded_tables = (
        "module_config_versions",
        "module_permission_grants",
        "panel_instances",
        "automation_tasks",
        "delivery_outbox",
        "module_migration_runs",
        "interaction_receipts",
    )
    for table in guarded_tables:
        if table not in tables:
            continue
        count = int(
            bind.scalar(
                sa.text(f"SELECT COUNT(*) FROM {table} WHERE module_key = 'farm'")
            )
            or 0
        )
        if count:
            raise RuntimeError(
                f"Cutover bloqueado: modulo farm possui {count} registro(s) "
                f"em {table}."
            )
    if "module_config_drafts" in tables:
        dirty_drafts = int(
            bind.scalar(
                sa.text(
                    "SELECT COUNT(*) FROM module_config_drafts "
                    "WHERE module_key = 'farm' AND revision <> 0"
                )
            )
            or 0
        )
        if dirty_drafts:
            raise RuntimeError("Cutover bloqueado: modulo farm possui draft editado.")
        bind.execute(
            sa.text("DELETE FROM module_config_drafts WHERE module_key = 'farm'")
        )
    bind.execute(sa.text("DELETE FROM module_instances WHERE module_key = 'farm'"))


def _scrub_legacy_settings(bind, tables: set[str]) -> None:
    if "guild_configs" not in tables:
        return
    configs = sa.table(
        "guild_configs",
        sa.column("guild_id", sa.String()),
        sa.column("settings", _json()),
    )
    for row in bind.execute(sa.select(configs.c.guild_id, configs.c.settings)).mappings():
        settings = row["settings"]
        if isinstance(settings, str):
            settings = json.loads(settings or "{}")
        if not isinstance(settings, dict) or "farm_tickets" not in settings:
            continue
        updated = dict(settings)
        updated.pop("farm_tickets", None)
        bind.execute(
            sa.update(configs)
            .where(configs.c.guild_id == row["guild_id"])
            .values(settings=updated)
        )


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    _archive_and_validate_legacy(bind, tables)
    _remove_unreleased_farm_platform_state(bind, tables)
    _scrub_legacy_settings(bind, tables)

    for table in (
        "farm_ticket_actions",
        "farm_ticket_entries",
        "farm_tickets",
        "farm_ticket_configs",
        "farm_reviews",
        "farm_proofs",
        "farm_submission_items",
        "farm_submissions",
        "farm_cycle_tickets",
        "farm_cycle_participants",
        "farm_cycle_goals",
        "farm_cycles",
        "farm_template_items",
        "farm_templates",
        "farm_products",
    ):
        if table in tables:
            op.drop_table(table)


def downgrade() -> None:
    raise RuntimeError(
        "Migration destrutiva: restaure o backup PostgreSQL validado antes do cutover."
    )
