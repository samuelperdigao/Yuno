"""add registration domain

Revision ID: a3b4c5d6e7f8
Revises: f2a1b3c4d5e6
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a3b4c5d6e7f8"
down_revision: str | Sequence[str] | None = "f2a1b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organization_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("discord_user_id", sa.String(32), nullable=False),
        sa.Column("player_id_original", sa.String(120), nullable=False),
        sa.Column("player_id_normalized", sa.String(120), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("approved_request_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("deactivated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "guild_id", "discord_user_id", name="uq_organization_members_guild_user"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')", name="ck_organization_members_status"
        ),
    )
    op.create_index("ix_organization_members_guild_id", "organization_members", ["guild_id"])
    op.create_index(
        "ix_organization_members_discord_user_id", "organization_members", ["discord_user_id"]
    )
    op.create_index(
        "ix_organization_members_player_id_normalized",
        "organization_members",
        ["player_id_normalized"],
    )
    op.create_index("ix_organization_members_status", "organization_members", ["status"])
    op.create_index(
        "ix_organization_members_approved_request_id",
        "organization_members",
        ["approved_request_id"],
    )
    op.create_index(
        "uq_organization_members_active_player_id",
        "organization_members",
        ["guild_id", "player_id_normalized"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_organization_members_guild_status_updated",
        "organization_members",
        ["guild_id", "status", "updated_at"],
    )

    op.create_table(
        "registration_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("discord_user_id", sa.String(32), nullable=False),
        sa.Column("submitted_name", sa.String(120), nullable=False),
        sa.Column("player_id_original", sa.String(120), nullable=False),
        sa.Column("player_id_normalized", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "config_version_submitted_id",
            sa.Integer(),
            sa.ForeignKey("module_config_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "config_version_reviewed_id",
            sa.Integer(),
            sa.ForeignKey("module_config_versions.id"),
        ),
        sa.Column("review_channel_id", sa.String(32)),
        sa.Column("review_message_id", sa.String(32)),
        sa.Column("reviewed_by", sa.String(32)),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("last_error_code", sa.String(120)),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("processing_token", sa.String(160)),
        sa.Column("processing_actor_id", sa.String(32)),
        sa.Column("processing_started_at", sa.DateTime(timezone=True)),
        sa.Column("processing_lease_until", sa.DateTime(timezone=True)),
        sa.Column("previous_nickname", sa.String(32)),
        sa.Column("target_nickname", sa.String(32)),
        sa.Column("role_was_present", sa.Boolean()),
        sa.Column("nickname_applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("role_applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("compensation_state", sa.String(20), nullable=False, server_default="none"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("rejected_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'approved', 'rejected')",
            name="ck_registration_requests_status",
        ),
        sa.CheckConstraint(
            "compensation_state IN ('none', 'prepared', 'required', 'complete', 'failed')",
            name="ck_registration_requests_compensation_state",
        ),
        sa.CheckConstraint("revision > 0", name="ck_registration_requests_revision"),
    )
    for column in (
        "guild_id",
        "discord_user_id",
        "player_id_normalized",
        "status",
        "config_version_submitted_id",
        "config_version_reviewed_id",
        "review_channel_id",
        "review_message_id",
        "reviewed_by",
        "processing_token",
        "processing_actor_id",
        "processing_lease_until",
    ):
        op.create_index(
            f"ix_registration_requests_{column}", "registration_requests", [column]
        )
    op.create_index(
        "uq_registration_requests_open_user",
        "registration_requests",
        ["guild_id", "discord_user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
        sqlite_where=sa.text("status IN ('pending', 'processing')"),
    )
    op.create_index(
        "uq_registration_requests_processing_player_id",
        "registration_requests",
        ["guild_id", "player_id_normalized"],
        unique=True,
        postgresql_where=sa.text("status = 'processing'"),
        sqlite_where=sa.text("status = 'processing'"),
    )
    op.create_index(
        "ix_registration_requests_guild_status_created",
        "registration_requests",
        ["guild_id", "status", "created_at"],
    )
    op.create_index(
        "ix_registration_requests_guild_lease",
        "registration_requests",
        ["guild_id", "status", "processing_lease_until"],
    )


def downgrade() -> None:
    op.drop_table("registration_requests")
    op.drop_table("organization_members")
