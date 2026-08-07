"""add module config states

Revision ID: 8f3d6a1c2b4e
Revises: 3795707f5b0a
Create Date: 2026-08-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "8f3d6a1c2b4e"
down_revision: Union[str, Sequence[str], None] = "3795707f5b0a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
    op.create_table(
        "module_config_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.String(length=32), nullable=False),
        sa.Column("module_key", sa.String(length=40), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("draft_data", json_type, server_default=sa.text("'{}'"), nullable=False),
        sa.Column("published_data", json_type, server_default=sa.text("'{}'"), nullable=False),
        sa.Column("draft_revision", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("published_revision", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("draft_updated_by", sa.String(length=32), nullable=True),
        sa.Column("draft_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.String(length=32), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "module_key", name="uq_module_config_states_guild_module"),
    )
    op.create_index("ix_module_config_states_guild_id", "module_config_states", ["guild_id"], unique=False)
    op.create_index("ix_module_config_states_module_key", "module_config_states", ["module_key"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_module_config_states_module_key", table_name="module_config_states")
    op.drop_index("ix_module_config_states_guild_id", table_name="module_config_states")
    op.drop_table("module_config_states")
