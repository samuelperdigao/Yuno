"""add tags domain

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b4c5d6e7f8a9"
down_revision: str | Sequence[str] | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE module_instances SET contract_version = 2, domain_version = '2.0.0' "
            "WHERE module_key = 'registration' AND contract_version < 2"
        )
    )
    op.create_index(
        "ix_organization_members_active_pagination",
        "organization_members",
        ["guild_id", "status", "discord_user_id"],
    )

    op.create_table(
        "tag_role_binding_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("module_instance_id", sa.Integer(), sa.ForeignKey("module_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("discord_role_id", sa.String(32), nullable=False),
        sa.Column("tag", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("updated_by", sa.String(32), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("module_instance_id", "discord_role_id", name="uq_tag_draft_instance_role"),
        sa.CheckConstraint("discord_role_id <> guild_id", name="ck_tag_draft_not_everyone"),
    )
    for column in ("module_instance_id", "guild_id", "discord_role_id"):
        op.create_index(f"ix_tag_role_binding_drafts_{column}", "tag_role_binding_drafts", [column])
    op.create_index("ix_tag_draft_guild_role", "tag_role_binding_drafts", ["guild_id", "discord_role_id"])

    op.create_table(
        "tag_role_binding_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("config_version_id", sa.Integer(), sa.ForeignKey("module_config_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("module_instance_id", sa.Integer(), sa.ForeignKey("module_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("discord_role_id", sa.String(32), nullable=False),
        sa.Column("tag", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("config_version_id", "discord_role_id", name="uq_tag_version_config_role"),
    )
    for column in ("config_version_id", "module_instance_id", "guild_id", "discord_role_id"):
        op.create_index(f"ix_tag_role_binding_versions_{column}", "tag_role_binding_versions", [column])
    op.create_index("ix_tag_version_effective", "tag_role_binding_versions", ["module_instance_id", "config_version_id", "enabled"])

    op.create_table(
        "tag_sync_intents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("discord_user_id", sa.String(32), nullable=False),
        sa.Column("desired_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("applied_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("observed_fingerprint", sa.String(64)),
        sa.Column("state", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("processing_token", sa.String(64)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("winning_role_id", sa.String(32)),
        sa.Column("expected_nickname_hash", sa.String(64)),
        sa.Column("applied_nickname_hash", sa.String(64)),
        sa.Column("last_result", sa.String(80)),
        sa.Column("last_error_code", sa.String(120)),
        sa.Column("last_error_detail", sa.Text()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correlation_id", sa.String(80)),
        *_timestamps(),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("guild_id", "discord_user_id", name="uq_tag_intent_guild_user"),
        sa.CheckConstraint("desired_revision >= applied_revision", name="ck_tag_intent_revisions"),
    )
    for column in ("guild_id", "discord_user_id", "state", "processing_token", "lease_until", "correlation_id"):
        op.create_index(f"ix_tag_sync_intents_{column}", "tag_sync_intents", [column])
    op.create_index("ix_tag_intent_queue", "tag_sync_intents", ["guild_id", "state", "updated_at"])

    op.create_table(
        "tag_sync_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False, server_default="effective"),
        sa.Column("reason", sa.String(80), nullable=False),
        sa.Column("config_version_id", sa.Integer(), sa.ForeignKey("module_config_versions.id")),
        sa.Column("cursor_user_id", sa.String(32)),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("planned_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requested_by", sa.String(32)),
        sa.Column("correlation_id", sa.String(80), nullable=False),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    for column in ("guild_id", "reason", "config_version_id", "status", "correlation_id"):
        op.create_index(f"ix_tag_sync_runs_{column}", "tag_sync_runs", [column])
    op.create_index("ix_tag_run_guild_status_created", "tag_sync_runs", ["guild_id", "status", "created_at"])
    op.create_index(
        "uq_tag_run_active_guild",
        "tag_sync_runs",
        ["guild_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'planning', 'running')"),
        sqlite_where=sa.text("status IN ('pending', 'planning', 'running')"),
    )

    op.create_table(
        "tag_sync_run_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("tag_sync_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("discord_user_id", sa.String(32), nullable=False),
        sa.Column("intent_revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("result_code", sa.String(120)),
        sa.Column("error_detail", sa.Text()),
        *_timestamps(),
        sa.UniqueConstraint("run_id", "discord_user_id", name="uq_tag_run_item_user"),
    )
    for column in ("run_id", "guild_id", "discord_user_id", "state"):
        op.create_index(f"ix_tag_sync_run_items_{column}", "tag_sync_run_items", [column])
    op.create_index("ix_tag_run_item_progress", "tag_sync_run_items", ["run_id", "state"])
    op.create_index("ix_tag_run_item_guild_user", "tag_sync_run_items", ["guild_id", "discord_user_id"])


def downgrade() -> None:
    op.drop_table("tag_sync_run_items")
    op.drop_table("tag_sync_runs")
    op.drop_table("tag_sync_intents")
    op.drop_table("tag_role_binding_versions")
    op.drop_table("tag_role_binding_drafts")
    op.drop_index("ix_organization_members_active_pagination", table_name="organization_members")
    op.execute(
        sa.text(
            "UPDATE module_instances SET contract_version = 1 "
            "WHERE module_key = 'registration' AND contract_version = 2"
        )
    )
