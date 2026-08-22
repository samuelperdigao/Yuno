"""scope Discord binding identity by resource kind

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-08-22

Uma thread publica iniciada por mensagem reutiliza o snowflake da mensagem.
Mensagem e thread sao recursos distintos e precisam de bindings independentes.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: str | Sequence[str] | None = "d6e7f8a9b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("farm_ticket_v2_discord_bindings") as batch:
        batch.drop_constraint("uq_ftv2_binding_resource", type_="unique")
        batch.create_unique_constraint(
            "uq_ftv2_binding_resource_kind",
            ["guild_id", "kind", "resource_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("farm_ticket_v2_discord_bindings") as batch:
        batch.drop_constraint("uq_ftv2_binding_resource_kind", type_="unique")
        batch.create_unique_constraint(
            "uq_ftv2_binding_resource", ["guild_id", "resource_id"]
        )
