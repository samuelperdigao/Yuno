"""add bau domain

Revision ID: a1b2c3d4e5f6
Revises: a9b0c1d2e3f4
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "a9b0c1d2e3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bau_categories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("guild_id", "name", name="uq_bau_categories_guild_name"),
    )
    op.create_index("ix_bau_categories_guild_id", "bau_categories", ["guild_id"])
    op.create_index(
        "ix_bau_categories_guild_position", "bau_categories", ["guild_id", "position"]
    )

    op.create_table(
        "bau_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column(
            "category_id",
            sa.String(36),
            sa.ForeignKey("bau_categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("guild_id", "name", name="uq_bau_items_guild_name"),
    )
    op.create_index("ix_bau_items_guild_id", "bau_items", ["guild_id"])
    op.create_index("ix_bau_items_category_id", "bau_items", ["category_id"])
    op.create_index(
        "ix_bau_items_guild_category", "bau_items", ["guild_id", "category_id", "position"]
    )

    op.create_table(
        "bau_stock",
        sa.Column(
            "item_id",
            sa.String(36),
            sa.ForeignKey("bau_items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("generation", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_by", sa.String(32)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("quantity >= 0", name="ck_bau_stock_quantity_non_negative"),
    )
    op.create_index("ix_bau_stock_guild_id", "bau_stock", ["guild_id"])

    op.create_table(
        "bau_movements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column(
            "item_id",
            sa.String(36),
            sa.ForeignKey("bau_items.id", ondelete="SET NULL"),
        ),
        sa.Column("item_name", sa.String(80), nullable=False),
        sa.Column("actor_id", sa.String(32), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("quantity_delta", sa.Integer(), nullable=False),
        sa.Column("quantity_before", sa.Integer(), nullable=False),
        sa.Column("quantity_after", sa.Integer(), nullable=False),
        sa.Column("generation_after", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.String(160), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_bau_movements_guild_id", "bau_movements", ["guild_id"])
    op.create_index("ix_bau_movements_item_id", "bau_movements", ["item_id"])
    op.create_index("ix_bau_movements_actor_id", "bau_movements", ["actor_id"])
    op.create_index("ix_bau_movements_correlation_id", "bau_movements", ["correlation_id"])
    op.create_index(
        "ix_bau_movements_guild_item_created", "bau_movements", ["guild_id", "item_id", "created_at"]
    )
    op.create_index(
        "ix_bau_movements_guild_created", "bau_movements", ["guild_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("bau_movements")
    op.drop_table("bau_stock")
    op.drop_table("bau_items")
    op.drop_table("bau_categories")
