"""add Farm Tickets V2 domain and read-only legacy archive

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-08-22

Etapa aditiva. O legado permanece operacional e nenhum ticket ativo recebe
um vinculo Meta inventado. A limpeza destrutiva exige aceite, backup
restauravel e zero ticket legado ativo.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d6e7f8a9b0c1"
down_revision: str | Sequence[str] | None = "c5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json() -> sa.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _index(table: str, column: str) -> None:
    op.create_index(f"ix_{table}_{column}", table, [column])


def _enum(*values: str, name: str, length: int) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=length)


def _archive_legacy_tickets() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "farm_tickets" not in inspector.get_table_names():
        return
    archive = sa.table(
        "farm_ticket_v2_legacy_archive",
        sa.column("id", sa.String()),
        sa.column("source_namespace", sa.String()),
        sa.column("source_id", sa.String()),
        sa.column("guild_id", sa.String()),
        sa.column("payload", _json()),
        sa.column("checksum_sha256", sa.String()),
    )
    ticket_rows = bind.execute(sa.text("SELECT * FROM farm_tickets ORDER BY id")).mappings()
    for ticket in ticket_rows:
        source_id = str(ticket["id"])
        exists = bind.scalar(
            sa.select(sa.func.count()).select_from(archive).where(
                archive.c.source_namespace == "yuno.legacy.farm_tickets",
                archive.c.source_id == source_id,
            )
        )
        if exists:
            continue
        entries = []
        actions = []
        if "farm_ticket_entries" in inspector.get_table_names():
            entries = list(
                bind.execute(
                    sa.text("SELECT * FROM farm_ticket_entries WHERE ticket_id = :ticket_id ORDER BY id"),
                    {"ticket_id": ticket["id"]},
                ).mappings()
            )
        if "farm_ticket_actions" in inspector.get_table_names():
            actions = list(
                bind.execute(
                    sa.text("SELECT * FROM farm_ticket_actions WHERE ticket_id = :ticket_id ORDER BY id"),
                    {"ticket_id": ticket["id"]},
                ).mappings()
            )
        payload = json.loads(
            json.dumps(
                {"ticket": dict(ticket), "entries": [dict(row) for row in entries], "actions": [dict(row) for row in actions]},
                sort_keys=True,
                default=str,
            )
        )
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        bind.execute(
            sa.insert(archive).values(
                id=str(uuid4()),
                source_namespace="yuno.legacy.farm_tickets",
                source_id=source_id,
                guild_id=str(ticket["guild_id"]),
                payload=payload,
                checksum_sha256=hashlib.sha256(canonical).hexdigest(),
            )
        )


def upgrade() -> None:
    op.create_table(
        "farm_ticket_v2_legacy_archive",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_namespace", sa.String(80), nullable=False),
        sa.Column("source_id", sa.String(120), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("payload", _json(), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_namespace", "source_id", name="uq_ftv2_legacy_source"),
    )
    _index("farm_ticket_v2_legacy_archive", "guild_id")

    op.create_table(
        "farm_ticket_v2_meta_cursors",
        sa.Column("guild_id", sa.String(32), primary_key=True),
        sa.Column("last_sequence", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("bootstrap_complete", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "farm_ticket_v2_meta_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("guild_id", "event_id", name="uq_ftv2_meta_receipt_event"),
        sa.UniqueConstraint("guild_id", "sequence", name="uq_ftv2_meta_receipt_sequence"),
    )
    _index("farm_ticket_v2_meta_receipts", "guild_id")

    op.create_table(
        "farm_ticket_v2_tickets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("member_id", sa.String(32), nullable=False),
        sa.Column("meta_goal_id", sa.BigInteger(), nullable=False),
        sa.Column("meta_cycle_id", sa.BigInteger(), nullable=False),
        sa.Column("registration_identity_id", sa.String(36), nullable=False),
        sa.Column("member_name", sa.String(120), nullable=False),
        sa.Column("player_id", sa.String(120), nullable=False),
        sa.Column("base_nickname", sa.String(120), nullable=False),
        sa.Column(
            "status",
            _enum(
                "IN_PROGRESS", "APPROVED", "FINALIZED_INCOMPLETE", "CLOSED_MANUALLY",
                name="ticketstatus", length=32,
            ),
            server_default=sa.text("'IN_PROGRESS'"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("assigned_admin_id", sa.String(32)),
        sa.Column("operations_closed_at", sa.DateTime(timezone=True)),
        sa.Column("withdrawals_open", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("settlement_closed_at", sa.DateTime(timezone=True)),
        sa.Column("binding_released_at", sa.DateTime(timezone=True)),
        sa.Column("member_left_at", sa.DateTime(timezone=True)),
        sa.Column("result_finalized_at", sa.DateTime(timezone=True)),
        sa.Column(
            "close_reason",
            _enum(
                "APPROVED", "MANUAL", "CYCLE_ENDED", "NEW_GOAL", "LEFT_GUILD",
                name="ticketclosereason", length=32,
            ),
        ),
        sa.Column(
            "last_resource_removal_reason",
            _enum(
                "MANUAL_DELETE", "CYCLE_CLEANUP", "NEW_GOAL_CLEANUP",
                "MEMBER_LEFT_CLEANUP", "RECONCILIATION",
                name="resourceremovalreason", length=32,
            ),
        ),
        sa.Column("frozen_launched_total", sa.Numeric(20, 3)),
        sa.Column("frozen_withdrawn_total", sa.Numeric(20, 3)),
        sa.Column("frozen_unwithdrawn_total", sa.Numeric(20, 3)),
        sa.Column("frozen_totals", _json()),
        sa.Column("provisioning_error", sa.Text()),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("revision > 0", name="ck_ftv2_ticket_revision"),
        sa.CheckConstraint(
            "(status = 'IN_PROGRESS' AND result_finalized_at IS NULL) OR "
            "(status <> 'IN_PROGRESS' AND result_finalized_at IS NOT NULL)",
            name="ck_ftv2_ticket_result_finalized",
        ),
        sa.UniqueConstraint("guild_id", "meta_cycle_id", "member_id", name="uq_ftv2_ticket_history"),
    )
    for column in (
        "guild_id", "member_id", "meta_goal_id", "meta_cycle_id", "status",
        "assigned_admin_id", "binding_released_at",
    ):
        _index("farm_ticket_v2_tickets", column)
    op.create_index(
        "uq_ftv2_active_member_binding",
        "farm_ticket_v2_tickets",
        ["guild_id", "member_id"],
        unique=True,
        postgresql_where=sa.text("binding_released_at IS NULL"),
        sqlite_where=sa.text("binding_released_at IS NULL"),
    )

    op.create_table(
        "farm_ticket_v2_cycles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ticket_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("meta_goal_id", sa.BigInteger(), nullable=False),
        sa.Column("meta_cycle_id", sa.BigInteger(), nullable=False),
        sa.Column("goal_name", sa.String(120), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("participation_ended_at", sa.DateTime(timezone=True)),
        sa.Column("event_sequence_at_open", sa.BigInteger()),
        sa.CheckConstraint("ends_at > starts_at", name="ck_ftv2_cycle_dates"),
        sa.UniqueConstraint("ticket_id", name="uq_ftv2_cycle_ticket"),
    )
    for column in ("ticket_id", "guild_id", "meta_goal_id", "meta_cycle_id", "ends_at"):
        _index("farm_ticket_v2_cycles", column)

    op.create_table(
        "farm_ticket_v2_objectives",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ticket_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("meta_objective_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", _enum("ITEM", "MONEY", name="objectivekind", length=10), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("unit", sa.String(30)),
        sa.Column("target_amount", sa.Numeric(20, 3), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("target_amount > 0", name="ck_ftv2_objective_target"),
        sa.UniqueConstraint("ticket_id", "meta_objective_id", name="uq_ftv2_ticket_objective"),
        sa.UniqueConstraint("ticket_id", "position", name="uq_ftv2_objective_position"),
    )
    _index("farm_ticket_v2_objectives", "ticket_id")
    _index("farm_ticket_v2_objectives", "guild_id")

    op.create_table(
        "farm_ticket_v2_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ticket_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(32), nullable=False),
        sa.Column("current_revision", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("number > 0", name="ck_ftv2_entry_number"),
        sa.UniqueConstraint("ticket_id", "number", name="uq_ftv2_entry_number"),
    )
    _index("farm_ticket_v2_entries", "ticket_id")
    _index("farm_ticket_v2_entries", "guild_id")

    op.create_table(
        "farm_ticket_v2_entry_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entry_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticket_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            _enum("PENDING", "CURRENT", "SUPERSEDED", "REJECTED", name="entryrevisionstatus", length=16),
            server_default=sa.text("'PENDING'"), nullable=False,
        ),
        sa.Column("actor_id", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("version > 0", name="ck_ftv2_entry_revision_version"),
        sa.UniqueConstraint("entry_id", "version", name="uq_ftv2_entry_revision"),
    )
    for column in ("entry_id", "ticket_id", "guild_id"):
        _index("farm_ticket_v2_entry_revisions", column)

    op.create_table(
        "farm_ticket_v2_entry_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("revision_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_entry_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticket_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("objective_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_objectives.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount", sa.Numeric(20, 3), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_ftv2_entry_item_amount"),
        sa.UniqueConstraint("revision_id", "objective_id", name="uq_ftv2_entry_item_objective"),
    )
    for column in ("revision_id", "entry_id", "ticket_id", "objective_id"):
        _index("farm_ticket_v2_entry_items", column)

    op.create_table(
        "farm_ticket_v2_pending_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ticket_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("kind", _enum("CREATE_ENTRY", "EDIT_ENTRY", name="operationkind", length=20), nullable=False),
        sa.Column(
            "status",
            _enum(
                "AWAITING_PROOF", "PROOF_CLAIMED", "PROCESSING_PROOF", "RETRYING_PROOF",
                "CONFIRMED", "EXPIRED", "FAILED", name="operationstatus", length=24,
            ),
            nullable=False,
        ),
        sa.Column("target_entry_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_entries.id", ondelete="RESTRICT")),
        sa.Column("pending_entry_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pending_revision_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_entry_revisions.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("actor_id", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(180), nullable=False),
        sa.Column("interaction_id", sa.String(32)),
        sa.Column("proof_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_token", sa.String(72), unique=True),
        sa.Column("proof_message_id", sa.String(32)),
        sa.Column("proof_attachment_id", sa.String(32)),
        sa.Column("proof_author_id", sa.String(32)),
        sa.Column("proof_channel_id", sa.String(32)),
        sa.Column("proof_received_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("attachment_filename", sa.String(255)),
        sa.Column("attachment_content_type", sa.String(100)),
        sa.Column("attachment_size", sa.BigInteger()),
        sa.Column("attachment_url", sa.Text()),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("processing_error", sa.Text()),
        sa.Column("failed_recoverably", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("proof_deadline > created_at", name="ck_ftv2_operation_deadline"),
        sa.CheckConstraint("attempts >= 0", name="ck_ftv2_operation_attempts"),
        sa.UniqueConstraint("guild_id", "idempotency_key", name="uq_ftv2_operation_idempotency"),
    )
    for column in (
        "ticket_id", "guild_id", "status", "target_entry_id", "pending_entry_id",
        "actor_id", "proof_deadline", "proof_received_at",
    ):
        _index("farm_ticket_v2_pending_operations", column)
    active_predicate = sa.text(
        "status IN ('AWAITING_PROOF','PROOF_CLAIMED','PROCESSING_PROOF','RETRYING_PROOF')"
    )
    op.create_index(
        "uq_ftv2_active_operation", "farm_ticket_v2_pending_operations", ["ticket_id"],
        unique=True, postgresql_where=active_predicate, sqlite_where=active_predicate,
    )
    for name, column in (
        ("uq_ftv2_operation_interaction", "interaction_id"),
        ("uq_ftv2_proof_message", "proof_message_id"),
    ):
        predicate = sa.text(f"{column} IS NOT NULL")
        op.create_index(
            name, "farm_ticket_v2_pending_operations", ["guild_id", column],
            unique=True, postgresql_where=predicate, sqlite_where=predicate,
        )

    op.create_table(
        "farm_ticket_v2_proof_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("operation_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_pending_operations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticket_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("message_id", sa.String(32), nullable=False),
        sa.Column("attachment_id", sa.String(32), nullable=False),
        sa.Column("author_id", sa.String(32), nullable=False),
        sa.Column("channel_id", sa.String(32), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100)),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("claim_token", sa.String(72), nullable=False, unique=True),
        sa.Column(
            "status", _enum("CLAIMED", "REJECTED", "ACCEPTED", name="proofcandidatestatus", length=12),
            server_default=sa.text("'CLAIMED'"), nullable=False,
        ),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("guild_id", "message_id", name="uq_ftv2_candidate_message"),
        sa.UniqueConstraint("guild_id", "attachment_id", name="uq_ftv2_candidate_attachment"),
    )
    for column in ("operation_id", "ticket_id", "guild_id", "received_at"):
        _index("farm_ticket_v2_proof_candidates", column)

    op.create_table(
        "farm_ticket_v2_proofs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("operation_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_pending_operations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ticket_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_revision_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_entry_revisions.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("message_id", sa.String(32), nullable=False),
        sa.Column("attachment_id", sa.String(32), nullable=False),
        sa.Column("author_id", sa.String(32), nullable=False),
        sa.Column("channel_id", sa.String(32), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("object_key", sa.String(500), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column(
            "storage_state",
            _enum("PENDING", "STORED", "DELETE_PENDING", "RETAINED", "DELETED", name="proofstoragestate", length=20),
            server_default=sa.text("'STORED'"), nullable=False,
        ),
        sa.Column("thread_delivery_confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("cleanup_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("size_bytes > 0 AND size_bytes <= 20971520", name="ck_ftv2_proof_size"),
        sa.UniqueConstraint("operation_id", name="uq_ftv2_proof_operation"),
        sa.UniqueConstraint("guild_id", "message_id", name="uq_ftv2_proof_message_stored"),
        sa.UniqueConstraint("object_key", name="uq_ftv2_proof_object_key"),
    )
    for column in ("operation_id", "ticket_id", "guild_id"):
        _index("farm_ticket_v2_proofs", column)

    op.create_table(
        "farm_ticket_v2_withdrawals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ticket_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(180), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("number > 0", name="ck_ftv2_withdrawal_number"),
        sa.UniqueConstraint("ticket_id", "number", name="uq_ftv2_withdrawal_number"),
        sa.UniqueConstraint("guild_id", "idempotency_key", name="uq_ftv2_withdrawal_idempotency"),
    )
    _index("farm_ticket_v2_withdrawals", "ticket_id")
    _index("farm_ticket_v2_withdrawals", "guild_id")

    op.create_table(
        "farm_ticket_v2_withdrawal_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("withdrawal_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_withdrawals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticket_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("objective_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_objectives.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount", sa.Numeric(20, 3), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_ftv2_withdrawal_item_amount"),
        sa.UniqueConstraint("withdrawal_id", "objective_id", name="uq_ftv2_withdrawal_objective"),
    )
    for column in ("withdrawal_id", "ticket_id", "objective_id"):
        _index("farm_ticket_v2_withdrawal_items", column)

    op.create_table(
        "farm_ticket_v2_allocations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ticket_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("objective_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_objectives.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("withdrawal_item_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_withdrawal_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_item_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_entry_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount", sa.Numeric(20, 3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_ftv2_allocation_amount"),
        sa.UniqueConstraint("withdrawal_item_id", "entry_item_id", name="uq_ftv2_allocation_pair"),
    )
    for column in ("ticket_id", "objective_id", "withdrawal_item_id", "entry_item_id"):
        _index("farm_ticket_v2_allocations", column)

    op.create_table(
        "farm_ticket_v2_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ticket_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("actor_id", sa.String(32)),
        sa.Column("deduplication_key", sa.String(180), nullable=False),
        sa.Column("payload", _json(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence > 0", name="ck_ftv2_event_sequence"),
        sa.UniqueConstraint("ticket_id", "sequence", name="uq_ftv2_event_sequence"),
        sa.UniqueConstraint("guild_id", "deduplication_key", name="uq_ftv2_event_deduplication"),
    )
    for column in ("ticket_id", "guild_id", "event_type"):
        _index("farm_ticket_v2_events", column)
    op.create_index("ix_ftv2_event_read", "farm_ticket_v2_events", ["ticket_id", "sequence"])

    op.create_table(
        "farm_ticket_v2_discord_bindings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ticket_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE")),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column(
            "kind",
            _enum(
                "CATEGORY", "GLOBAL_PANEL_CHANNEL", "GLOBAL_PANEL_MESSAGE", "LOG_CHANNEL",
                "TICKET_CHANNEL", "TICKET_PANEL_MESSAGE", "TICKET_MAIN_MESSAGE", "TICKET_THREAD",
                name="resourcekind", length=32,
            ),
            nullable=False,
        ),
        sa.Column("resource_id", sa.String(32), nullable=False),
        sa.Column("parent_resource_id", sa.String(32)),
        sa.Column("ownership", _enum("ADOPTED", "MANAGED", name="bindingownership", length=12), nullable=False),
        sa.Column(
            "state",
            _enum("PROVISIONING", "ACTIVE", "MISSING", "DELETE_PENDING", "DELETED", name="bindingstate", length=20),
            nullable=False,
        ),
        sa.Column("desired_revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("applied_revision", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("deletion_intent_at", sa.DateTime(timezone=True)),
        sa.Column(
            "deletion_reason",
            _enum(
                "MANUAL_DELETE", "CYCLE_CLEANUP", "NEW_GOAL_CLEANUP",
                "MEMBER_LEFT_CLEANUP", "RECONCILIATION",
                name="resourceremovalreason", length=32,
            ),
        ),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("guild_id", "resource_id", name="uq_ftv2_binding_resource"),
        sa.UniqueConstraint("ticket_id", "kind", name="uq_ftv2_ticket_binding_kind"),
    )
    _index("farm_ticket_v2_discord_bindings", "ticket_id")
    _index("farm_ticket_v2_discord_bindings", "guild_id")

    op.create_table(
        "farm_ticket_v2_form_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ticket_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(32), nullable=False),
        sa.Column(
            "operation_kind",
            _enum("CREATE_ENTRY", "EDIT_ENTRY", "WITHDRAWAL", name="formkind", length=20),
            nullable=False,
        ),
        sa.Column("target_entry_id", sa.String(36), sa.ForeignKey("farm_ticket_v2_entries.id", ondelete="RESTRICT")),
        sa.Column("step", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("values", _json(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("revision > 0", name="ck_ftv2_form_draft_revision"),
        sa.UniqueConstraint("ticket_id", "actor_id", name="uq_ftv2_form_draft_actor"),
    )
    for column in ("ticket_id", "guild_id", "actor_id"):
        _index("farm_ticket_v2_form_drafts", column)

    _archive_legacy_tickets()


def downgrade() -> None:
    for table in (
        "farm_ticket_v2_form_drafts",
        "farm_ticket_v2_discord_bindings",
        "farm_ticket_v2_events",
        "farm_ticket_v2_allocations",
        "farm_ticket_v2_withdrawal_items",
        "farm_ticket_v2_withdrawals",
        "farm_ticket_v2_proofs",
        "farm_ticket_v2_proof_candidates",
        "farm_ticket_v2_pending_operations",
        "farm_ticket_v2_entry_items",
        "farm_ticket_v2_entry_revisions",
        "farm_ticket_v2_entries",
        "farm_ticket_v2_objectives",
        "farm_ticket_v2_cycles",
        "farm_ticket_v2_tickets",
        "farm_ticket_v2_meta_receipts",
        "farm_ticket_v2_meta_cursors",
        "farm_ticket_v2_legacy_archive",
    ):
        op.drop_table(table)
