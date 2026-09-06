"""add ausencia domain

Revision ID: b1c2d3e4f5a6
Revises: a9b0c1d2e3f4
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b1c2d3e4f5a6"
down_revision: str | Sequence[str] | None = "a9b0c1d2e3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "absence_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("discord_user_id", sa.String(32), nullable=False),
        sa.Column("member_display_name", sa.String(120), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("overdue_notified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("guild_id", "discord_user_id", name="uq_absence_records_guild_user"),
        sa.CheckConstraint("days >= 1", name="ck_absence_records_days_positive"),
    )
    op.create_index("ix_absence_records_guild_id", "absence_records", ["guild_id"])
    op.create_index("ix_absence_records_discord_user_id", "absence_records", ["discord_user_id"])
    op.create_index(
        "ix_absence_records_guild_ends_at", "absence_records", ["guild_id", "ends_at"]
    )
    op.create_index(
        "ix_absence_records_guild_overdue",
        "absence_records",
        ["guild_id", "overdue_notified", "ends_at"],
    )


def downgrade() -> None:
    op.drop_table("absence_records")
