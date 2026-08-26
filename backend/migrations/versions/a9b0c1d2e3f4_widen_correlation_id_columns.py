"""widen correlation_id columns from 80 to 160

`correlation_id` nasceu como VARCHAR(80), mas o farm_tickets gera
`meta:{event_id}:ticket:{ticket_id}` -- 5 + 36 + 8 + 36 = 85 caracteres fixos.
No PostgreSQL isso levanta StringDataRightTruncationError e derruba o
`POST /internal/platform/guilds/{id}/modules/farm_tickets/meta-events/consume`
com 500 a cada boot do bot, travando o cursor de eventos da Meta. O SQLite
ignora o tamanho declarado de VARCHAR, entao a suite nunca pegou.

160 e o mesmo tamanho ja usado por `idempotency_key`, e nenhum formato atual de
correlacao chega perto disso.

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
Create Date: 2026-08-26

"""

import sqlalchemy as sa

from alembic import op

revision = "a9b0c1d2e3f4"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None


# (tabela, coluna nullable?)
TABLES = (
    ("automation_tasks", False),
    ("automation_runs", False),
    ("delivery_outbox", False),
    ("audit_entries", False),
    ("interaction_receipts", False),
    ("tag_sync_intents", True),
    ("tag_sync_runs", False),
)


def upgrade() -> None:
    for table, nullable in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "correlation_id",
                existing_type=sa.String(length=80),
                type_=sa.String(length=160),
                existing_nullable=nullable,
            )


def downgrade() -> None:
    # Volta ao tamanho antigo truncando o que nao couber, senao o ALTER falha em
    # bancos que ja gravaram correlacoes longas.
    for table, nullable in TABLES:
        op.execute(
            sa.text(
                f"UPDATE {table} SET correlation_id = substr(correlation_id, 1, 80) "
                "WHERE correlation_id IS NOT NULL AND length(correlation_id) > 80"
            )
        )
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "correlation_id",
                existing_type=sa.String(length=160),
                type_=sa.String(length=80),
                existing_nullable=nullable,
            )
