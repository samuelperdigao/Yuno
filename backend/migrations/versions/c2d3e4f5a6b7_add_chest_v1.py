"""add domain-first chest v1

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chest_chests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("guild_id", "id", name="uq_chest_chests_guild_id"),
    )
    op.create_index("ix_chest_chests_guild", "chest_chests", ["guild_id"])
    op.create_table(
        "chest_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("guild_id", "id", name="uq_chest_items_guild_id"),
    )
    op.create_index("ix_chest_items_guild", "chest_items", ["guild_id"])

    op.create_table(
        "chest_draft_chests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("chest_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_normalized", sa.String(100), nullable=False),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "position", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"], ["module_config_drafts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "chest_id"],
            ["chest_chests.guild_id", "chest_chests.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "draft_id", "chest_id", name="uq_chest_draft_chest_identity"
        ),
        sa.UniqueConstraint(
            "draft_id", "name_normalized", name="uq_chest_draft_chest_name"
        ),
        sa.UniqueConstraint(
            "draft_id",
            "guild_id",
            "chest_id",
            name="uq_chest_draft_chest_tenant_identity",
        ),
    )
    op.create_index(
        "ix_chest_draft_chests_guild", "chest_draft_chests", ["guild_id", "draft_id"]
    )
    op.create_table(
        "chest_draft_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("item_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_normalized", sa.String(100), nullable=False),
        sa.Column("unit", sa.String(40), nullable=False, server_default="unidade"),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "position", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"], ["module_config_drafts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "item_id"],
            ["chest_items.guild_id", "chest_items.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("draft_id", "item_id", name="uq_chest_draft_item_identity"),
        sa.UniqueConstraint(
            "draft_id", "name_normalized", name="uq_chest_draft_item_name"
        ),
        sa.UniqueConstraint(
            "draft_id",
            "guild_id",
            "item_id",
            name="uq_chest_draft_item_tenant_identity",
        ),
    )
    op.create_index(
        "ix_chest_draft_items_guild", "chest_draft_items", ["guild_id", "draft_id"]
    )
    op.create_table(
        "chest_draft_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("chest_id", sa.String(36), nullable=False),
        sa.Column("item_id", sa.String(36), nullable=False),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.ForeignKeyConstraint(
            ["draft_id", "guild_id", "chest_id"],
            [
                "chest_draft_chests.draft_id",
                "chest_draft_chests.guild_id",
                "chest_draft_chests.chest_id",
            ],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["draft_id", "guild_id", "item_id"],
            [
                "chest_draft_items.draft_id",
                "chest_draft_items.guild_id",
                "chest_draft_items.item_id",
            ],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "draft_id", "chest_id", "item_id", name="uq_chest_draft_link"
        ),
    )
    op.create_index(
        "ix_chest_draft_links_guild", "chest_draft_links", ["guild_id", "draft_id"]
    )

    op.create_table(
        "chest_version_chests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("config_version_id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("chest_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_normalized", sa.String(100), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["config_version_id"], ["module_config_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "chest_id"],
            ["chest_chests.guild_id", "chest_chests.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "config_version_id", "chest_id", name="uq_chest_version_chest_identity"
        ),
        sa.UniqueConstraint(
            "config_version_id", "name_normalized", name="uq_chest_version_chest_name"
        ),
        sa.UniqueConstraint(
            "config_version_id",
            "guild_id",
            "chest_id",
            name="uq_chest_version_chest_tenant_identity",
        ),
    )
    op.create_index(
        "ix_chest_version_chests_guild",
        "chest_version_chests",
        ["guild_id", "config_version_id"],
    )
    op.create_table(
        "chest_version_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("config_version_id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("item_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_normalized", sa.String(100), nullable=False),
        sa.Column("unit", sa.String(40), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["config_version_id"], ["module_config_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "item_id"],
            ["chest_items.guild_id", "chest_items.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "config_version_id", "item_id", name="uq_chest_version_item_identity"
        ),
        sa.UniqueConstraint(
            "config_version_id", "name_normalized", name="uq_chest_version_item_name"
        ),
        sa.UniqueConstraint(
            "config_version_id",
            "guild_id",
            "item_id",
            name="uq_chest_version_item_tenant_identity",
        ),
    )
    op.create_index(
        "ix_chest_version_items_guild",
        "chest_version_items",
        ["guild_id", "config_version_id"],
    )
    op.create_table(
        "chest_version_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("config_version_id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("chest_id", sa.String(36), nullable=False),
        sa.Column("item_id", sa.String(36), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["config_version_id", "guild_id", "chest_id"],
            [
                "chest_version_chests.config_version_id",
                "chest_version_chests.guild_id",
                "chest_version_chests.chest_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["config_version_id", "guild_id", "item_id"],
            [
                "chest_version_items.config_version_id",
                "chest_version_items.guild_id",
                "chest_version_items.item_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "config_version_id", "chest_id", "item_id", name="uq_chest_version_link"
        ),
    )
    op.create_index(
        "ix_chest_version_links_lookup",
        "chest_version_links",
        ["guild_id", "config_version_id", "chest_id", "active"],
    )

    op.create_table(
        "chest_balances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("chest_id", sa.String(36), nullable=False),
        sa.Column("item_id", sa.String(36), nullable=False),
        sa.Column(
            "quantity", sa.Numeric(20, 3), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "sequence", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "chest_id"],
            ["chest_chests.guild_id", "chest_chests.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "item_id"],
            ["chest_items.guild_id", "chest_items.id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_chest_balance_nonnegative"),
        sa.CheckConstraint("sequence >= 0", name="ck_chest_balance_sequence"),
        sa.UniqueConstraint(
            "guild_id", "chest_id", "item_id", name="uq_chest_balance_identity"
        ),
        sa.UniqueConstraint("guild_id", "id", name="uq_chest_balance_guild_id"),
        sa.UniqueConstraint(
            "guild_id",
            "id",
            "chest_id",
            "item_id",
            name="uq_chest_balance_full_identity",
        ),
    )
    op.create_index(
        "ix_chest_balances_guild_chest", "chest_balances", ["guild_id", "chest_id"]
    )
    op.create_table(
        "chest_movements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("balance_id", sa.String(36), nullable=False),
        sa.Column("chest_id", sa.String(36), nullable=False),
        sa.Column("item_id", sa.String(36), nullable=False),
        sa.Column("movement_type", sa.String(24), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 3), nullable=False),
        sa.Column("actor_id", sa.String(32), nullable=False),
        sa.Column("actor_type", sa.String(16), nullable=False, server_default="user"),
        sa.Column("balance_before", sa.Numeric(20, 3), nullable=False),
        sa.Column("balance_after", sa.Numeric(20, 3), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("observation", sa.Text()),
        sa.Column("correlation_id", sa.String(160), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("origin", sa.String(64), nullable=False, server_default="discord"),
        sa.Column("chest_name_snapshot", sa.String(100), nullable=False),
        sa.Column("item_name_snapshot", sa.String(100), nullable=False),
        sa.Column("unit_snapshot", sa.String(40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "balance_id"],
            ["chest_balances.guild_id", "chest_balances.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "balance_id", "chest_id", "item_id"],
            [
                "chest_balances.guild_id",
                "chest_balances.id",
                "chest_balances.chest_id",
                "chest_balances.item_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "chest_id"],
            ["chest_chests.guild_id", "chest_chests.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["guild_id", "item_id"],
            ["chest_items.guild_id", "chest_items.id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_chest_movement_positive"),
        sa.CheckConstraint(
            "balance_before >= 0 AND balance_after >= 0",
            name="ck_chest_movement_balances",
        ),
        sa.CheckConstraint("sequence > 0", name="ck_chest_movement_sequence"),
        sa.CheckConstraint(
            "(movement_type IN ('DEPOSIT', 'ADJUSTMENT_CREDIT') AND balance_after = balance_before + quantity) OR (movement_type IN ('WITHDRAWAL', 'ADJUSTMENT_DEBIT') AND balance_after = balance_before - quantity)",
            name="ck_chest_movement_arithmetic",
        ),
        sa.UniqueConstraint(
            "guild_id", "idempotency_key", name="uq_chest_movement_idempotency"
        ),
        sa.UniqueConstraint(
            "balance_id", "sequence", name="uq_chest_movement_balance_sequence"
        ),
    )
    op.create_index(
        "ix_chest_movements_history",
        "chest_movements",
        ["guild_id", "chest_id", "created_at"],
    )
    op.create_index(
        "ix_chest_movements_actor",
        "chest_movements",
        ["guild_id", "actor_id", "created_at"],
    )
    op.create_index(
        "ix_chest_movements_correlation_id", "chest_movements", ["correlation_id"]
    )

    op.create_table(
        "chest_command_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("resource_id", sa.String(80), nullable=False, server_default=""),
        sa.Column("result", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "guild_id", "idempotency_key", name="uq_chest_command_receipt_idempotency"
        ),
    )
    op.create_index(
        "ix_chest_command_receipts_guild_action",
        "chest_command_receipts",
        ["guild_id", "action"],
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION yuno_chest_movement_immutable()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'chest_movements is append-only';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_chest_movements_immutable
            BEFORE UPDATE OR DELETE ON chest_movements
            FOR EACH ROW EXECUTE FUNCTION yuno_chest_movement_immutable()
            """
        )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade destrutivo bloqueado: o ledger chest_movements deve ser preservado. "
        "Use roll-forward ou procedimento operacional auditado."
    )
