"""add yuno platform foundation

Revision ID: c1d2e3f4a5b6
Revises: 8f3d6a1c2b4e
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c1d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "8f3d6a1c2b4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "guild_profiles",
        sa.Column("guild_id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(120)),
        sa.Column("locale", sa.String(20), nullable=False, server_default="pt-BR"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="America/Sao_Paulo"),
        sa.Column("preferences", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "guild_admin_roles",
        sa.Column("guild_id", sa.String(32), primary_key=True),
        sa.Column("role_id", sa.String(32), primary_key=True),
        sa.Column("created_by", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "module_instances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("module_key", sa.String(64), nullable=False),
        sa.Column("lifecycle", sa.String(20), nullable=False, server_default="inactive"),
        sa.Column("runtime_mode", sa.String(20), nullable=False, server_default="legacy"),
        sa.Column("contract_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("domain_version", sa.String(32), nullable=False, server_default="legacy"),
        sa.Column("published_config_version_id", sa.Integer()),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("guild_id", "module_key", name="uq_module_instances_guild_module"),
    )
    op.create_index("ix_module_instances_guild_id", "module_instances", ["guild_id"])
    op.create_index("ix_module_instances_module_key", "module_instances", ["module_key"])
    op.create_index("ix_module_instances_lifecycle", "module_instances", ["lifecycle"])
    op.create_index("ix_module_instances_runtime_mode", "module_instances", ["runtime_mode"])
    op.create_index(
        "ix_module_instances_published_config_version_id",
        "module_instances",
        ["published_config_version_id"],
    )

    op.create_table(
        "module_config_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("module_instance_id", sa.Integer(), sa.ForeignKey("module_instances.id"), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("module_key", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("base_published_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("updated_by", sa.String(32)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("module_instance_id", name="uq_module_config_drafts_instance"),
    )
    op.create_index("ix_module_config_drafts_guild_id", "module_config_drafts", ["guild_id"])
    op.create_index("ix_module_config_drafts_module_key", "module_config_drafts", ["module_key"])
    op.create_index(
        "ix_module_config_drafts_module_instance_id",
        "module_config_drafts",
        ["module_instance_id"],
    )
    op.create_index("ix_module_config_drafts_updated_by", "module_config_drafts", ["updated_by"])

    op.create_table(
        "module_config_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("module_instance_id", sa.Integer(), sa.ForeignKey("module_instances.id"), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("module_key", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source_version", sa.Integer()),
        sa.Column("published_by", sa.String(32), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("module_instance_id", "version", name="uq_module_config_versions_instance_version"),
        sa.UniqueConstraint("id", "module_instance_id", name="uq_module_config_versions_id_instance"),
    )
    op.create_index("ix_module_config_versions_guild_id", "module_config_versions", ["guild_id"])
    op.create_index("ix_module_config_versions_module_key", "module_config_versions", ["module_key"])
    op.create_index(
        "ix_module_config_versions_module_instance_id",
        "module_config_versions",
        ["module_instance_id"],
    )
    op.create_index("ix_module_config_versions_published_by", "module_config_versions", ["published_by"])

    op.create_table(
        "module_permission_grants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("module_instance_id", sa.Integer(), sa.ForeignKey("module_instances.id"), nullable=False),
        sa.Column("config_version_id", sa.Integer(), sa.ForeignKey("module_config_versions.id"), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("module_key", sa.String(64), nullable=False),
        sa.Column("capability", sa.String(120), nullable=False),
        sa.Column("subject_type", sa.String(20), nullable=False),
        sa.Column("subject_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("scope_type", sa.String(20), nullable=False, server_default="guild"),
        sa.Column("scope_id", sa.String(80), nullable=False, server_default=""),
        sa.Column("constraints", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.UniqueConstraint(
            "config_version_id", "capability", "subject_type", "subject_id", "scope_type", "scope_id",
            name="uq_module_permission_grants_identity",
        ),
    )
    op.create_index("ix_module_permission_grants_guild_id", "module_permission_grants", ["guild_id"])
    op.create_index("ix_module_permission_grants_capability", "module_permission_grants", ["capability"])
    op.create_index(
        "ix_module_permission_grants_module_instance_id",
        "module_permission_grants",
        ["module_instance_id"],
    )
    op.create_index(
        "ix_module_permission_grants_config_version_id",
        "module_permission_grants",
        ["config_version_id"],
    )
    op.create_index("ix_module_permission_grants_module_key", "module_permission_grants", ["module_key"])

    op.create_table(
        "panel_instances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("module_key", sa.String(64), nullable=False),
        sa.Column("panel_key", sa.String(80), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False, server_default=""),
        sa.Column("resource_id", sa.String(80), nullable=False, server_default=""),
        sa.Column("channel_id", sa.String(32)),
        sa.Column("message_id", sa.String(32)),
        sa.Column("definition_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("config_version", sa.Integer()),
        sa.Column("render_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("recovery_policy", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_by", sa.String(32)),
        sa.Column("updated_by", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "guild_id", "module_key", "panel_key", "resource_type", "resource_id",
            name="uq_panel_instances_logical_identity",
        ),
        sa.UniqueConstraint("guild_id", "channel_id", "message_id", name="uq_panel_instances_discord_message"),
    )
    op.create_index("ix_panel_instances_guild_id", "panel_instances", ["guild_id"])
    op.create_index("ix_panel_instances_module_key", "panel_instances", ["module_key"])
    op.create_index("ix_panel_instances_state", "panel_instances", ["state"])
    op.create_index("ix_panel_instances_panel_key", "panel_instances", ["panel_key"])
    op.create_index("ix_panel_instances_channel_id", "panel_instances", ["channel_id"])
    op.create_index("ix_panel_instances_message_id", "panel_instances", ["message_id"])

    op.create_table(
        "automation_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("module_key", sa.String(64), nullable=False),
        sa.Column("job_key", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False, server_default=""),
        sa.Column("resource_id", sa.String(80), nullable=False, server_default=""),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("lease_owner", sa.String(80)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("correlation_id", sa.String(80), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("guild_id", "module_key", "job_key", "idempotency_key", name="uq_automation_tasks_idempotency"),
    )
    op.create_index("ix_automation_tasks_claim", "automation_tasks", ["state", "due_at", "lease_until"])
    op.create_index("ix_automation_tasks_guild_id", "automation_tasks", ["guild_id"])
    op.create_index("ix_automation_tasks_module_key", "automation_tasks", ["module_key"])
    op.create_index("ix_automation_tasks_job_key", "automation_tasks", ["job_key"])
    op.create_index("ix_automation_tasks_due_at", "automation_tasks", ["due_at"])
    op.create_index("ix_automation_tasks_state", "automation_tasks", ["state"])
    op.create_index("ix_automation_tasks_lease_owner", "automation_tasks", ["lease_owner"])
    op.create_index("ix_automation_tasks_lease_until", "automation_tasks", ["lease_until"])
    op.create_index("ix_automation_tasks_correlation_id", "automation_tasks", ["correlation_id"])

    op.create_table(
        "automation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("automation_tasks.id"), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("module_key", sa.String(64), nullable=False),
        sa.Column("job_key", sa.String(100), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="claimed"),
        sa.Column("worker_id", sa.String(80), nullable=False),
        sa.Column("correlation_id", sa.String(80), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("task_id", "attempt", name="uq_automation_runs_task_attempt"),
    )
    op.create_index("ix_automation_runs_guild_id", "automation_runs", ["guild_id"])
    op.create_index("ix_automation_runs_task_id", "automation_runs", ["task_id"])
    op.create_index("ix_automation_runs_module_key", "automation_runs", ["module_key"])
    op.create_index("ix_automation_runs_job_key", "automation_runs", ["job_key"])
    op.create_index("ix_automation_runs_correlation_id", "automation_runs", ["correlation_id"])

    op.create_table(
        "delivery_outbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("module_key", sa.String(64), nullable=False),
        sa.Column("renderer_key", sa.String(100), nullable=False),
        sa.Column("destination_type", sa.String(30), nullable=False),
        sa.Column("destination_id", sa.String(80), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False, server_default=""),
        sa.Column("resource_id", sa.String(80), nullable=False, server_default=""),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("state", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("lease_owner", sa.String(80)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("correlation_id", sa.String(80), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("guild_id", "module_key", "idempotency_key", name="uq_delivery_outbox_idempotency"),
    )
    op.create_index("ix_delivery_outbox_claim", "delivery_outbox", ["state", "available_at", "lease_until"])
    op.create_index("ix_delivery_outbox_guild_id", "delivery_outbox", ["guild_id"])
    op.create_index("ix_delivery_outbox_module_key", "delivery_outbox", ["module_key"])
    op.create_index("ix_delivery_outbox_state", "delivery_outbox", ["state"])
    op.create_index("ix_delivery_outbox_available_at", "delivery_outbox", ["available_at"])
    op.create_index("ix_delivery_outbox_lease_owner", "delivery_outbox", ["lease_owner"])
    op.create_index("ix_delivery_outbox_lease_until", "delivery_outbox", ["lease_until"])
    op.create_index("ix_delivery_outbox_correlation_id", "delivery_outbox", ["correlation_id"])

    op.create_table(
        "delivery_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("delivery_id", sa.String(36), sa.ForeignKey("delivery_outbox.id"), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(80), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="claimed"),
        sa.Column("external_id", sa.String(80)),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("delivery_id", "attempt", name="uq_delivery_attempts_delivery_attempt"),
    )
    op.create_index("ix_delivery_attempts_delivery_id", "delivery_attempts", ["delivery_id"])

    op.create_table(
        "audit_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("actor_type", sa.String(20), nullable=False, server_default="user"),
        sa.Column("actor_id", sa.String(64)),
        sa.Column("module_key", sa.String(64)),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False),
        sa.Column("resource_id", sa.String(80)),
        sa.Column("before", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("after", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("config_version", sa.Integer()),
        sa.Column("result", sa.String(30), nullable=False, server_default="success"),
        sa.Column("correlation_id", sa.String(80), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_entries_guild_id", "audit_entries", ["guild_id"])
    op.create_index("ix_audit_entries_module_key", "audit_entries", ["module_key"])
    op.create_index("ix_audit_entries_correlation_id", "audit_entries", ["correlation_id"])
    op.create_index("ix_audit_entries_actor_id", "audit_entries", ["actor_id"])
    op.create_index("ix_audit_entries_action", "audit_entries", ["action"])
    op.create_index("ix_audit_entries_resource_id", "audit_entries", ["resource_id"])
    op.create_index("ix_audit_entries_created_at", "audit_entries", ["created_at"])

    op.create_table(
        "module_migration_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("module_key", sa.String(64), nullable=False),
        sa.Column("migration_key", sa.String(100), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_mode", sa.String(20), nullable=False, server_default="legacy"),
        sa.Column("target_mode", sa.String(20), nullable=False, server_default="domain"),
        sa.Column("state", sa.String(20), nullable=False, server_default="inventory"),
        sa.Column("checkpoint", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("counts", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("checksum", sa.String(128)),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("errors", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("started_by", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("guild_id", "module_key", "migration_key", "attempt", name="uq_module_migration_runs_attempt"),
    )
    op.create_index("ix_module_migration_runs_guild_id", "module_migration_runs", ["guild_id"])
    op.create_index("ix_module_migration_runs_module_key", "module_migration_runs", ["module_key"])
    op.create_index("ix_module_migration_runs_state", "module_migration_runs", ["state"])

    op.create_table(
        "interaction_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("interaction_id", sa.String(32), nullable=False),
        sa.Column("module_key", sa.String(64), nullable=False),
        sa.Column("action_key", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False, server_default=""),
        sa.Column("resource_id", sa.String(80), nullable=False, server_default=""),
        sa.Column("state", sa.String(20), nullable=False, server_default="claimed"),
        sa.Column("correlation_id", sa.String(80), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("guild_id", "interaction_id", name="uq_interaction_receipts_guild_interaction"),
    )
    op.create_index("ix_interaction_receipts_guild_id", "interaction_receipts", ["guild_id"])
    op.create_index("ix_interaction_receipts_expires_at", "interaction_receipts", ["expires_at"])
    op.create_index("ix_interaction_receipts_module_key", "interaction_receipts", ["module_key"])
    op.create_index("ix_interaction_receipts_correlation_id", "interaction_receipts", ["correlation_id"])

    # Fecha dois drifts preexistentes do Control Plane legado sem alterar seu
    # comportamento. Estes indices ja estavam declarados no modelo ORM.
    op.create_index(
        "ix_module_config_states_draft_updated_by",
        "module_config_states",
        ["draft_updated_by"],
    )
    op.create_index(
        "ix_module_config_states_published_by",
        "module_config_states",
        ["published_by"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_module_config_states_published_by",
        table_name="module_config_states",
    )
    op.drop_index(
        "ix_module_config_states_draft_updated_by",
        table_name="module_config_states",
    )
    for table in (
        "interaction_receipts",
        "module_migration_runs",
        "audit_entries",
        "delivery_attempts",
        "delivery_outbox",
        "automation_runs",
        "automation_tasks",
        "panel_instances",
        "module_permission_grants",
        "module_config_versions",
        "module_config_drafts",
        "module_instances",
        "guild_admin_roles",
        "guild_profiles",
    ):
        op.drop_table(table)
