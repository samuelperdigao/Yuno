"""add domain-first parceria persistence

Revision ID: b1c2d3e4f5a6
Revises: a9b0c1d2e3f4
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "a9b0c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "parceria_domain_families",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_normalized", sa.String(100), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("legacy_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("guild_id", "name_normalized", name="uq_parceria_domain_family_guild_name"),
    )
    op.create_index("ix_parceria_domain_families_guild_id", "parceria_domain_families", ["guild_id"])
    op.create_index("ix_parceria_domain_families_name_normalized", "parceria_domain_families", ["name_normalized"])
    op.create_index("ix_parceria_domain_family_guild_active", "parceria_domain_families", ["guild_id", "active"])

    op.create_table(
        "parceria_domain_images",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column("storage_url", sa.String(1000)),
        sa.Column("content_type", sa.String(40), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(128)),
        sa.Column("original_filename", sa.String(255)),
        sa.Column("uploaded_by", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("guild_id", "storage_key", name="uq_parceria_domain_image_storage"),
    )
    op.create_index("ix_parceria_domain_images_guild_id", "parceria_domain_images", ["guild_id"])
    op.create_index("ix_parceria_domain_images_checksum", "parceria_domain_images", ["checksum"])

    op.create_table(
        "parceria_domain_partnerships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("family_id", sa.String(36), sa.ForeignKey("parceria_domain_families.id"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("registered_by", sa.String(32), nullable=False),
        sa.Column("image_asset_id", sa.String(36), sa.ForeignKey("parceria_domain_images.id"), nullable=False),
        sa.Column("public_channel_id", sa.String(32)),
        sa.Column("public_message_id", sa.String(32)),
        sa.Column("publication_revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("legacy_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'inactive', 'publication_pending', 'degraded')", name="ck_parceria_domain_status"),
    )
    op.create_index("ix_parceria_domain_partnerships_guild_id", "parceria_domain_partnerships", ["guild_id"])
    op.create_index("ix_parceria_domain_partnerships_family_id", "parceria_domain_partnerships", ["family_id"])
    op.create_index("ix_parceria_domain_partnerships_status", "parceria_domain_partnerships", ["status"])
    op.create_index("ix_parceria_domain_guild_status", "parceria_domain_partnerships", ["guild_id", "status"])

    op.create_table(
        "parceria_domain_products",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("parceria_id", sa.String(36), sa.ForeignKey("parceria_domain_partnerships.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_parceria_domain_products_guild_id", "parceria_domain_products", ["guild_id"])

    op.create_table(
        "parceria_domain_contacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("parceria_id", sa.String(36), sa.ForeignKey("parceria_domain_partnerships.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("value", sa.String(150), nullable=False),
        sa.UniqueConstraint("parceria_id", "position", name="uq_parceria_domain_contact_position"),
    )
    op.create_index("ix_parceria_domain_contacts_guild_id", "parceria_domain_contacts", ["guild_id"])
    op.create_index("ix_parceria_domain_contacts_parceria_id", "parceria_domain_contacts", ["parceria_id"])

    op.create_table(
        "parceria_registration_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(32), nullable=False),
        sa.Column("channel_id", sa.String(32), nullable=False),
        sa.Column("family_name", sa.String(100), nullable=False),
        sa.Column("family_normalized", sa.String(100), nullable=False),
        sa.Column("product_name", sa.String(100), nullable=False),
        sa.Column("contact_01", sa.String(150)),
        sa.Column("contact_02", sa.String(150)),
        sa.Column("image_asset_id", sa.String(36), sa.ForeignKey("parceria_domain_images.id")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(160), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("completed_parceria_id", sa.String(36), sa.ForeignKey("parceria_domain_partnerships.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('awaiting_image', 'completed', 'expired', 'cancelled')", name="ck_parceria_registration_attempt_status"),
        sa.UniqueConstraint("guild_id", "idempotency_key", name="uq_parceria_registration_attempt_idempotency"),
    )
    for name, columns in (
        ("ix_parceria_registration_attempts_guild_id", ["guild_id"]),
        ("ix_parceria_registration_attempts_actor_id", ["actor_id"]),
        ("ix_parceria_registration_attempts_channel_id", ["channel_id"]),
        ("ix_parceria_registration_attempts_family_normalized", ["family_normalized"]),
        ("ix_parceria_registration_attempts_image_asset_id", ["image_asset_id"]),
        ("ix_parceria_registration_attempts_status", ["status"]),
        ("ix_parceria_registration_attempts_expires_at", ["expires_at"]),
        ("ix_parceria_registration_attempts_correlation_id", ["correlation_id"]),
        ("ix_parceria_registration_attempts_completed_parceria_id", ["completed_parceria_id"]),
    ):
        op.create_index(name, "parceria_registration_attempts", columns)
    op.create_index("ix_parceria_registration_attempt_expiry", "parceria_registration_attempts", ["guild_id", "status", "expires_at"])

    op.create_table(
        "parceria_domain_publications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(32), nullable=False),
        sa.Column("parceria_id", sa.String(36), sa.ForeignKey("parceria_domain_partnerships.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.String(32), nullable=False),
        sa.Column("message_id", sa.String(32)),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'published', 'missing', 'archived', 'failed')", name="ck_parceria_domain_publication_status"),
        sa.UniqueConstraint("guild_id", "idempotency_key", name="uq_parceria_domain_publication_idempotency"),
    )
    op.create_index("ix_parceria_domain_publications_guild_id", "parceria_domain_publications", ["guild_id"])
    op.create_index("ix_parceria_domain_publications_parceria_id", "parceria_domain_publications", ["parceria_id"])
    op.create_index("ix_parceria_domain_publications_status", "parceria_domain_publications", ["status"])
    op.create_index("ix_parceria_domain_publication_current", "parceria_domain_publications", ["guild_id", "parceria_id", "status"])


def downgrade() -> None:
    # Remove somente as tabelas novas do domínio; as tabelas legadas são preservadas.
    for index, table in (
        ("ix_parceria_domain_publication_current", "parceria_domain_publications"),
        ("ix_parceria_domain_publications_status", "parceria_domain_publications"),
        ("ix_parceria_domain_publications_parceria_id", "parceria_domain_publications"),
        ("ix_parceria_domain_publications_guild_id", "parceria_domain_publications"),
    ):
        op.drop_index(index, table_name=table)
    op.drop_table("parceria_domain_publications")
    for index in (
        "ix_parceria_registration_attempt_expiry",
        "ix_parceria_registration_attempts_completed_parceria_id",
        "ix_parceria_registration_attempts_correlation_id",
        "ix_parceria_registration_attempts_expires_at",
        "ix_parceria_registration_attempts_status",
        "ix_parceria_registration_attempts_image_asset_id",
        "ix_parceria_registration_attempts_family_normalized",
        "ix_parceria_registration_attempts_channel_id",
        "ix_parceria_registration_attempts_actor_id",
        "ix_parceria_registration_attempts_guild_id",
    ):
        op.drop_index(index, table_name="parceria_registration_attempts")
    op.drop_table("parceria_registration_attempts")
    op.drop_index("ix_parceria_domain_contacts_parceria_id", table_name="parceria_domain_contacts")
    op.drop_index("ix_parceria_domain_contacts_guild_id", table_name="parceria_domain_contacts")
    op.drop_table("parceria_domain_contacts")
    op.drop_index("ix_parceria_domain_products_guild_id", table_name="parceria_domain_products")
    op.drop_table("parceria_domain_products")
    for index in ("ix_parceria_domain_guild_status", "ix_parceria_domain_partnerships_status", "ix_parceria_domain_partnerships_family_id", "ix_parceria_domain_partnerships_guild_id"):
        op.drop_index(index, table_name="parceria_domain_partnerships")
    op.drop_table("parceria_domain_partnerships")
    op.drop_index("ix_parceria_domain_images_checksum", table_name="parceria_domain_images")
    op.drop_index("ix_parceria_domain_images_guild_id", table_name="parceria_domain_images")
    op.drop_table("parceria_domain_images")
    for index in ("ix_parceria_domain_family_guild_active", "ix_parceria_domain_families_name_normalized", "ix_parceria_domain_families_guild_id"):
        op.drop_index(index, table_name="parceria_domain_families")
    op.drop_table("parceria_domain_families")
