"""add farm domain

Revision ID: f2a1b3c4d5e6
Revises: c1d2e3f4a5b6
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f2a1b3c4d5e6"
down_revision: str | Sequence[str] | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "farm_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("normalized_name", sa.String(80), nullable=False),
        sa.Column("active_key", sa.String(80)),
        sa.Column("description", sa.Text()),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("precision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("archived_by", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("guild_id", "active_key", name="uq_farm_products_guild_active_key"),
        sa.CheckConstraint("precision >= 0 AND precision <= 3", name="ck_farm_products_precision"),
    )
    op.create_index("ix_farm_products_guild_id", "farm_products", ["guild_id"])
    op.create_index("ix_farm_products_normalized_name", "farm_products", ["normalized_name"])
    op.create_index("ix_farm_products_status", "farm_products", ["status"])

    op.create_table(
        "farm_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("template_key", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("activated_by", sa.String(32)),
        sa.Column("archived_by", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("guild_id", "template_key", "version", name="uq_farm_templates_key_version"),
        sa.CheckConstraint("version > 0", name="ck_farm_templates_version"),
    )
    op.create_index("ix_farm_templates_guild_id", "farm_templates", ["guild_id"])
    op.create_index("ix_farm_templates_template_key", "farm_templates", ["template_key"])
    op.create_index("ix_farm_templates_status", "farm_templates", ["status"])

    op.create_table(
        "farm_template_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("farm_templates.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("farm_products.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("template_id", "product_id", name="uq_farm_template_items_product"),
        sa.CheckConstraint("quantity > 0", name="ck_farm_template_items_quantity"),
    )
    op.create_index("ix_farm_template_items_guild_id", "farm_template_items", ["guild_id"])
    op.create_index("ix_farm_template_items_template_id", "farm_template_items", ["template_id"])
    op.create_index("ix_farm_template_items_product_id", "farm_template_items", ["product_id"])

    op.create_table(
        "farm_cycles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("farm_templates.id"), nullable=False),
        sa.Column("config_version_id", sa.Integer(), sa.ForeignKey("module_config_versions.id"), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_deadline_at", sa.DateTime(timezone=True)),
        sa.Column("participation_mode", sa.String(20), nullable=False),
        sa.Column("proof_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("cancelled_by", sa.String(32)),
        sa.Column("cancel_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("ends_at > starts_at", name="ck_farm_cycles_dates"),
        sa.CheckConstraint("review_deadline_at IS NULL OR review_deadline_at >= ends_at", name="ck_farm_cycles_review_deadline"),
    )
    op.create_index("ix_farm_cycles_guild_id", "farm_cycles", ["guild_id"])
    op.create_index("ix_farm_cycles_template_id", "farm_cycles", ["template_id"])
    op.create_index("ix_farm_cycles_config_version_id", "farm_cycles", ["config_version_id"])
    op.create_index("ix_farm_cycles_starts_at", "farm_cycles", ["starts_at"])
    op.create_index("ix_farm_cycles_ends_at", "farm_cycles", ["ends_at"])
    op.create_index("ix_farm_cycles_review_deadline_at", "farm_cycles", ["review_deadline_at"])
    op.create_index("ix_farm_cycles_status", "farm_cycles", ["status"])
    op.create_index("ix_farm_cycles_guild_status_start", "farm_cycles", ["guild_id", "status", "starts_at"])

    op.create_table(
        "farm_cycle_goals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("farm_cycles.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("farm_products.id"), nullable=False),
        sa.Column("product_name", sa.String(80), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("precision", sa.Integer(), nullable=False),
        sa.Column("quantity_required", sa.Numeric(18, 3), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("cycle_id", "product_id", name="uq_farm_cycle_goals_product"),
        sa.CheckConstraint("quantity_required > 0", name="ck_farm_cycle_goals_quantity"),
        sa.CheckConstraint("precision >= 0 AND precision <= 3", name="ck_farm_cycle_goals_precision"),
    )
    op.create_index("ix_farm_cycle_goals_guild_id", "farm_cycle_goals", ["guild_id"])
    op.create_index("ix_farm_cycle_goals_cycle_id", "farm_cycle_goals", ["cycle_id"])
    op.create_index("ix_farm_cycle_goals_product_id", "farm_cycle_goals", ["product_id"])

    op.create_table(
        "farm_cycle_participants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("farm_cycles.id"), nullable=False),
        sa.Column("member_id", sa.String(32), nullable=False),
        sa.Column("member_display_name", sa.String(120), nullable=False),
        sa.Column("assigned_by", sa.String(32), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("cycle_id", "member_id", name="uq_farm_cycle_participants_member"),
    )
    op.create_index("ix_farm_cycle_participants_guild_id", "farm_cycle_participants", ["guild_id"])
    op.create_index("ix_farm_cycle_participants_cycle_id", "farm_cycle_participants", ["cycle_id"])
    op.create_index("ix_farm_cycle_participants_member_id", "farm_cycle_participants", ["member_id"])

    op.create_table(
        "farm_cycle_tickets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("farm_cycles.id"), nullable=False),
        sa.Column("member_id", sa.String(32), nullable=False),
        sa.Column("member_display_name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("cancelled_by", sa.String(32)),
        sa.Column("cancel_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("cycle_id", "member_id", name="uq_farm_cycle_tickets_member"),
    )
    op.create_index("ix_farm_cycle_tickets_guild_id", "farm_cycle_tickets", ["guild_id"])
    op.create_index("ix_farm_cycle_tickets_cycle_id", "farm_cycle_tickets", ["cycle_id"])
    op.create_index("ix_farm_cycle_tickets_member_id", "farm_cycle_tickets", ["member_id"])
    op.create_index("ix_farm_cycle_tickets_status", "farm_cycle_tickets", ["status"])
    op.create_index("ix_farm_cycle_tickets_created_by", "farm_cycle_tickets", ["created_by"])
    op.create_index("ix_farm_cycle_tickets_guild_member_status", "farm_cycle_tickets", ["guild_id", "member_id", "status"])

    op.create_table(
        "farm_submissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("farm_cycle_tickets.id"), nullable=False),
        sa.Column("correction_of_submission_id", sa.Integer(), sa.ForeignKey("farm_submissions.id")),
        sa.Column("status", sa.String(24), nullable=False, server_default="submitted"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("submitted_by", sa.String(32), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("claimed_by", sa.String(32)),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("guild_id", "idempotency_key", name="uq_farm_submissions_idempotency"),
    )
    op.create_index("ix_farm_submissions_guild_id", "farm_submissions", ["guild_id"])
    op.create_index("ix_farm_submissions_ticket_id", "farm_submissions", ["ticket_id"])
    op.create_index("ix_farm_submissions_correction_of_submission_id", "farm_submissions", ["correction_of_submission_id"])
    op.create_index("ix_farm_submissions_status", "farm_submissions", ["status"])
    op.create_index("ix_farm_submissions_submitted_by", "farm_submissions", ["submitted_by"])
    op.create_index("ix_farm_submissions_claimed_by", "farm_submissions", ["claimed_by"])
    op.create_index("ix_farm_submissions_claim_expires_at", "farm_submissions", ["claim_expires_at"])
    op.create_index("ix_farm_submissions_guild_status_created", "farm_submissions", ["guild_id", "status", "created_at"])

    op.create_table(
        "farm_submission_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("farm_submissions.id"), nullable=False),
        sa.Column("goal_id", sa.Integer(), sa.ForeignKey("farm_cycle_goals.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.UniqueConstraint("submission_id", "goal_id", name="uq_farm_submission_items_goal"),
        sa.CheckConstraint("quantity > 0", name="ck_farm_submission_items_quantity"),
    )
    op.create_index("ix_farm_submission_items_guild_id", "farm_submission_items", ["guild_id"])
    op.create_index("ix_farm_submission_items_submission_id", "farm_submission_items", ["submission_id"])
    op.create_index("ix_farm_submission_items_goal_id", "farm_submission_items", ["goal_id"])

    op.create_table(
        "farm_proofs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("farm_submissions.id"), nullable=False),
        sa.Column("channel_id", sa.String(32), nullable=False),
        sa.Column("message_id", sa.String(32), nullable=False),
        sa.Column("attachment_id", sa.String(32)),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(120)),
        sa.Column("submitted_by", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("guild_id", "message_id", "attachment_id", name="uq_farm_proofs_discord_attachment"),
    )
    op.create_index("ix_farm_proofs_guild_id", "farm_proofs", ["guild_id"])
    op.create_index("ix_farm_proofs_submission_id", "farm_proofs", ["submission_id"])
    op.create_index("ix_farm_proofs_message_id", "farm_proofs", ["message_id"])

    op.create_table(
        "farm_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("farm_submissions.id"), nullable=False),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("reviewer_id", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("guild_id", "idempotency_key", name="uq_farm_reviews_idempotency"),
    )
    op.create_index("ix_farm_reviews_guild_id", "farm_reviews", ["guild_id"])
    op.create_index("ix_farm_reviews_submission_id", "farm_reviews", ["submission_id"])
    op.create_index("ix_farm_reviews_decision", "farm_reviews", ["decision"])
    op.create_index("ix_farm_reviews_reviewer_id", "farm_reviews", ["reviewer_id"])
    op.create_index("ix_farm_reviews_guild_submission_created", "farm_reviews", ["guild_id", "submission_id", "created_at"])


def downgrade() -> None:
    for table in (
        "farm_reviews",
        "farm_proofs",
        "farm_submission_items",
        "farm_submissions",
        "farm_cycle_tickets",
        "farm_cycle_participants",
        "farm_cycle_goals",
        "farm_cycles",
        "farm_template_items",
        "farm_templates",
        "farm_products",
    ):
        op.drop_table(table)
