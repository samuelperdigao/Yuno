"""reconcile parceria indexes

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
"""

from alembic import op

revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        "image_asset_id",
        "public_channel_id",
        "public_message_id",
        "registered_by",
    ):
        op.create_index(
            f"ix_parceria_domain_partnerships_{column}",
            "parceria_domain_partnerships",
            [column],
            unique=False,
            if_not_exists=True,
        )


def downgrade() -> None:
    for column in reversed(
        (
            "image_asset_id",
            "public_channel_id",
            "public_message_id",
            "registered_by",
        )
    ):
        op.drop_index(
            f"ix_parceria_domain_partnerships_{column}",
            table_name="parceria_domain_partnerships",
            if_exists=True,
        )
