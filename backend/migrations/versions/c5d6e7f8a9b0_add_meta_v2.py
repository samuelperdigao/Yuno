"""add canonical Meta V2 and remove legacy weekly goals

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-08-22

This migration intentionally does not preserve legacy Meta data. Existing
farm tickets keep their own ``goal_items`` snapshots and are not removed.
Database rollback is restore-from-backup; downgrade only recreates an empty
legacy goal table so a schema rollback remains technically possible.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c5d6e7f8a9b0"
down_revision: str | Sequence[str] | None = "b4c5d6e7f8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _index(table: str, column: str) -> None:
    op.create_index(f"ix_{table}_{column}", table, [column])


def _clean_legacy_projection() -> None:
    bind = op.get_bind()
    states = sa.table("module_config_states", sa.column("module_key", sa.String()))
    bind.execute(sa.delete(states).where(states.c.module_key == "meta"))

    configs = sa.table(
        "guild_configs",
        sa.column("id", sa.Integer()),
        sa.column("modules", sa.JSON()),
        sa.column("command_permissions", sa.JSON()),
        sa.column("messages", sa.JSON()),
        sa.column("settings", sa.JSON()),
    )
    rows = bind.execute(
        sa.select(
            configs.c.id,
            configs.c.modules,
            configs.c.command_permissions,
            configs.c.messages,
            configs.c.settings,
        )
    ).mappings()
    for row in rows:
        modules = dict(row["modules"] or {})
        messages = dict(row["messages"] or {})
        settings = dict(row["settings"] or {})
        permissions = dict(row["command_permissions"] or {})
        modules.pop("meta", None)
        messages.pop("meta", None)
        settings.pop("meta", None)
        permissions = {
            key: value
            for key, value in permissions.items()
            if key != "meta" and not str(key).startswith("meta.")
        }
        bind.execute(
            sa.update(configs)
            .where(configs.c.id == row["id"])
            .values(
                modules=modules,
                command_permissions=permissions,
                messages=messages,
                settings=settings,
            )
        )


def upgrade() -> None:
    _clean_legacy_projection()
    op.drop_table("farm_weekly_goals")

    op.create_table(
        "meta_guild_settings",
        sa.Column("guild_id", sa.String(32), primary_key=True),
        sa.Column("notice_channel_id", sa.String(32)),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "meta_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("normalized_name", sa.String(100), nullable=False),
        sa.Column("active_key", sa.String(100)),
        sa.Column("unit", sa.String(30), nullable=False, server_default="unidade"),
        sa.Column("last_suggested_quantity", sa.Numeric(20, 3)),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("guild_id", "active_key", name="uq_meta_products_guild_active_key"),
        sa.CheckConstraint(
            "last_suggested_quantity IS NULL OR last_suggested_quantity > 0",
            name="ck_meta_products_suggested_positive",
        ),
    )
    _index("meta_products", "guild_id")
    _index("meta_products", "normalized_name")

    op.create_table(
        "meta_goals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("created_sequence", sa.BigInteger(), nullable=False),
        sa.Column("creation_key", sa.String(100), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("state", sa.String(24), nullable=False, server_default="scheduled"),
        sa.Column("recurrence", sa.String(16), nullable=False),
        sa.Column("recurrence_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("current_config_version_id", sa.Integer()),
        sa.Column("future_config_version_id", sa.Integer()),
        sa.Column("next_transition_at", sa.DateTime(timezone=True)),
        sa.Column("end_reason", sa.String(20)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("guild_id", "created_sequence", name="uq_meta_goals_guild_sequence"),
        sa.UniqueConstraint("guild_id", "creation_key", name="uq_meta_goals_creation_key"),
        sa.CheckConstraint("version > 0", name="ck_meta_goals_version"),
    )
    for column in (
        "guild_id", "state", "recurrence", "current_config_version_id",
        "future_config_version_id", "next_transition_at",
    ):
        _index("meta_goals", column)
    op.create_index(
        "ix_meta_goals_selectable", "meta_goals", ["guild_id", "state", "created_sequence"]
    )

    op.create_table(
        "meta_goal_config_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("goal_id", sa.Integer(), sa.ForeignKey("meta_goals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("recurrence", sa.String(16), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("daily_time", sa.String(5)),
        sa.Column("weekday", sa.Integer()),
        sa.Column("month_day", sa.Integer()),
        sa.Column("scheduled_start_at", sa.DateTime(timezone=True)),
        sa.Column("scheduled_end_at", sa.DateTime(timezone=True)),
        sa.Column("participation", sa.String(20), nullable=False),
        sa.Column("notice_text", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("goal_id", "version", name="uq_meta_goal_config_version"),
        sa.CheckConstraint("version > 0", name="ck_meta_goal_config_version_positive"),
        sa.CheckConstraint("weekday IS NULL OR (weekday >= 0 AND weekday <= 6)", name="ck_meta_goal_weekday"),
        sa.CheckConstraint("month_day IS NULL OR (month_day >= 1 AND month_day <= 31)", name="ck_meta_goal_month_day"),
    )
    _index("meta_goal_config_versions", "goal_id")
    _index("meta_goal_config_versions", "guild_id")
    with op.batch_alter_table("meta_goals") as batch:
        batch.create_foreign_key(
            "fk_meta_goals_current_config", "meta_goal_config_versions",
            ["current_config_version_id"], ["id"], ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_meta_goals_future_config", "meta_goal_config_versions",
            ["future_config_version_id"], ["id"], ondelete="RESTRICT",
        )

    op.create_table(
        "meta_goal_config_roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("config_version_id", sa.Integer(), sa.ForeignKey("meta_goal_config_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("role_id", sa.String(32), nullable=False),
        sa.UniqueConstraint("config_version_id", "role_id", name="uq_meta_goal_config_role"),
    )
    for column in ("config_version_id", "guild_id", "role_id"):
        _index("meta_goal_config_roles", column)

    objective_shape = (
        "(kind = 'item' AND item_quantity IS NOT NULL AND item_quantity > 0 AND money_amount IS NULL) "
        "OR (kind = 'money' AND money_amount IS NOT NULL AND money_amount > 0 AND item_quantity IS NULL)"
    )
    op.create_table(
        "meta_goal_config_objectives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("config_version_id", sa.Integer(), sa.ForeignKey("meta_goal_config_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("meta_products.id", ondelete="RESTRICT")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("unit", sa.String(30)),
        sa.Column("item_quantity", sa.Numeric(20, 3)),
        sa.Column("money_amount", sa.Numeric(20, 2)),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("config_version_id", "position", name="uq_meta_config_objective_position"),
        sa.CheckConstraint(objective_shape, name="ck_meta_config_objective_shape"),
    )
    for column in ("config_version_id", "guild_id"):
        _index("meta_goal_config_objectives", column)

    op.create_table(
        "meta_admin_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("admin_id", sa.String(32), nullable=False),
        sa.Column("goal_id", sa.Integer(), sa.ForeignKey("meta_goals.id", ondelete="SET NULL")),
        sa.Column("expected_goal_version", sa.Integer()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("step", sa.String(32), nullable=False, server_default="name"),
        sa.Column("data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("submitted_goal_id", sa.Integer(), sa.ForeignKey("meta_goals.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("guild_id", "admin_id", name="uq_meta_admin_draft"),
        sa.CheckConstraint("revision > 0", name="ck_meta_admin_draft_revision"),
    )
    for column in ("guild_id", "admin_id"):
        _index("meta_admin_drafts", column)

    op.create_table(
        "meta_cycles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("goal_id", sa.Integer(), sa.ForeignKey("meta_goals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("config_version_id", sa.Integer(), sa.ForeignKey("meta_goal_config_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("cycle_key", sa.String(80), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("notice_text", sa.Text(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False, server_default="launch_pending"),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notice_channel_id", sa.String(32), nullable=False),
        sa.Column("notice_message_id", sa.String(32)),
        sa.Column("notice_reference", sa.String(100), nullable=False),
        sa.Column("end_reason", sa.String(20)),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("goal_id", "cycle_key", name="uq_meta_cycle_key"),
        sa.UniqueConstraint("guild_id", "notice_reference", name="uq_meta_cycle_notice_reference"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_meta_cycle_dates"),
    )
    for column in ("guild_id", "goal_id", "config_version_id", "state", "starts_at", "ends_at", "notice_message_id"):
        _index("meta_cycles", column)
    op.create_index("ix_meta_cycles_guild_state_ends", "meta_cycles", ["guild_id", "state", "ends_at"])

    op.create_table(
        "meta_cycle_objectives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("meta_cycles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("product_id", sa.Integer()),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("unit", sa.String(30)),
        sa.Column("item_quantity", sa.Numeric(20, 3)),
        sa.Column("money_amount", sa.Numeric(20, 2)),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("cycle_id", "position", name="uq_meta_cycle_objective_position"),
        sa.CheckConstraint(objective_shape, name="ck_meta_cycle_objective_shape"),
    )
    _index("meta_cycle_objectives", "guild_id")
    _index("meta_cycle_objectives", "cycle_id")

    op.create_table(
        "meta_cycle_participants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("meta_cycles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("member_id", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("role_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("joined_at", sa.DateTime(timezone=True)),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.Column("removal_reason", sa.String(32)),
        sa.UniqueConstraint("cycle_id", "member_id", name="uq_meta_cycle_participant_member"),
    )
    for column in ("guild_id", "cycle_id", "member_id", "active"):
        _index("meta_cycle_participants", column)
    op.create_index(
        "uq_meta_active_participant",
        "meta_cycle_participants",
        ["guild_id", "member_id"],
        unique=True,
        postgresql_where=sa.text("active = true"),
        sqlite_where=sa.text("active = 1"),
    )
    op.create_index(
        "ix_meta_cycle_participant_cycle_active", "meta_cycle_participants", ["cycle_id", "active"]
    )

    op.create_table(
        "meta_integration_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("causation_id", sa.String(100), nullable=False),
        sa.Column("deduplication_key", sa.String(180), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.UniqueConstraint("guild_id", "sequence", name="uq_meta_event_sequence"),
        sa.UniqueConstraint("guild_id", "deduplication_key", name="uq_meta_event_deduplication"),
        sa.CheckConstraint("sequence > 0", name="ck_meta_event_sequence_positive"),
    )
    for column in ("guild_id", "event_type", "causation_id"):
        _index("meta_integration_events", column)
    op.create_index(
        "ix_meta_events_read", "meta_integration_events", ["guild_id", "sequence", "event_type"]
    )

    op.execute(
        sa.text(
            "UPDATE module_instances SET contract_version = 2, domain_version = '2.0.0', "
            "runtime_mode = 'domain' WHERE module_key = 'meta'"
        )
    )


def downgrade() -> None:
    op.drop_table("meta_integration_events")
    op.drop_table("meta_cycle_participants")
    op.drop_table("meta_cycle_objectives")
    op.drop_table("meta_cycles")
    op.drop_table("meta_admin_drafts")
    op.drop_table("meta_goal_config_roles")
    op.drop_table("meta_goal_config_objectives")
    with op.batch_alter_table("meta_goals") as batch:
        batch.drop_constraint("fk_meta_goals_future_config", type_="foreignkey")
        batch.drop_constraint("fk_meta_goals_current_config", type_="foreignkey")
    op.drop_table("meta_goal_config_versions")
    op.drop_table("meta_goals")
    op.drop_table("meta_products")
    op.drop_table("meta_guild_settings")

    op.create_table(
        "farm_weekly_goals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("week_id", sa.String(12), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("guild_id", "week_id", name="uq_farm_weekly_goal_guild_week"),
    )
    for column in ("guild_id", "week_id", "active"):
        _index("farm_weekly_goals", column)
