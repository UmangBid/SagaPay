"""initial ledger schema

Revision ID: 0001_ledger
Revises:
Create Date: 2026-02-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_ledger"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("account_type", sa.String(), nullable=False),
        sa.Column("balance_cents", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("account_id"),
    )
    op.create_index("ix_accounts_account_type", "accounts", ["account_type"])

    op.create_table(
        "ledger_entries",
        sa.Column("entry_id", sa.String(), nullable=False),
        sa.Column("transaction_id", sa.String(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"]),
        sa.PrimaryKeyConstraint("entry_id"),
    )
    op.create_index("ix_ledger_entries_account_id", "ledger_entries", ["account_id"])
    op.create_index("ix_ledger_entries_transaction_id", "ledger_entries", ["transaction_id"])

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("aggregate_type", sa.String(), nullable=False),
        sa.Column("aggregate_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("topic", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbox_events_aggregate_id", "outbox_events", ["aggregate_id"])
    op.create_index("ix_outbox_events_event_type", "outbox_events", ["event_type"])
    op.create_index("ix_outbox_events_status", "outbox_events", ["status"])

    op.create_table(
        "inbox_events",
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("consumed_by_service", sa.String(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("event_id", "consumed_by_service"),
        sa.UniqueConstraint("event_id", "consumed_by_service", name="uq_inbox_consumer"),
    )


def downgrade() -> None:
    op.drop_table("inbox_events")
    op.drop_index("ix_outbox_events_status", table_name="outbox_events")
    op.drop_index("ix_outbox_events_event_type", table_name="outbox_events")
    op.drop_index("ix_outbox_events_aggregate_id", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_ledger_entries_transaction_id", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_account_id", table_name="ledger_entries")
    op.drop_table("ledger_entries")
    op.drop_index("ix_accounts_account_type", table_name="accounts")
    op.drop_table("accounts")
