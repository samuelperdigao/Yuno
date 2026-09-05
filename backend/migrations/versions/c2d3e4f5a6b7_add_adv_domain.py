"""add adv domain

Revision ID: c2d3e4f5a6b7
Revises: a9b0c1d2e3f4
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c2d3e4f5a6b7"
down_revision: str | Sequence[str] | None = "a9b0c1d2e3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "adv_warnings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("discord_user_id", sa.String(32), nullable=False),
        sa.Column("member_display_name", sa.String(120), nullable=False),
        sa.Column("moderator_id", sa.String(32), nullable=False),
        sa.Column("moderator_display_name", sa.String(120), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by", sa.String(32)),
        sa.Column("revoke_reason", sa.Text()),
    )
    op.create_index("ix_adv_warnings_guild_id", "adv_warnings", ["guild_id"])
    op.create_index("ix_adv_warnings_discord_user_id", "adv_warnings", ["discord_user_id"])
    op.create_index(
        "ix_adv_warnings_guild_user", "adv_warnings", ["guild_id", "discord_user_id"]
    )
    op.create_index(
        "ix_adv_warnings_guild_created", "adv_warnings", ["guild_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("adv_warnings")
