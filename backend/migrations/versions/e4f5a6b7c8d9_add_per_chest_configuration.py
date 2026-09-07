"""add per-chest configuration and permissions

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
"""

from alembic import op
import sqlalchemy as sa


revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


_JSON_EMPTY = sa.text("'[]'")


def _add(table: str) -> None:
    op.add_column(table, sa.Column("description", sa.String(300), nullable=False, server_default=""))
    op.add_column(table, sa.Column("panel_channel_id", sa.String(32), nullable=True))
    op.add_column(table, sa.Column("log_channel_id", sa.String(32), nullable=True))
    op.add_column(table, sa.Column("show_balances_to_members", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column(table, sa.Column("allow_personal_history", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column(table, sa.Column("withdrawal_reason_required", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column(table, sa.Column("view_role_ids", sa.JSON(), nullable=False, server_default=_JSON_EMPTY))
    op.add_column(table, sa.Column("deposit_role_ids", sa.JSON(), nullable=False, server_default=_JSON_EMPTY))
    op.add_column(table, sa.Column("withdraw_role_ids", sa.JSON(), nullable=False, server_default=_JSON_EMPTY))
    op.add_column(table, sa.Column("admin_role_ids", sa.JSON(), nullable=False, server_default=_JSON_EMPTY))


def upgrade() -> None:
    _add("chest_draft_chests")
    _add("chest_version_chests")


def downgrade() -> None:
    for table in ("chest_version_chests", "chest_draft_chests"):
        for column in (
            "admin_role_ids",
            "withdraw_role_ids",
            "deposit_role_ids",
            "view_role_ids",
            "withdrawal_reason_required",
            "allow_personal_history",
            "show_balances_to_members",
            "log_channel_id",
            "panel_channel_id",
            "description",
        ):
            op.drop_column(table, column)
