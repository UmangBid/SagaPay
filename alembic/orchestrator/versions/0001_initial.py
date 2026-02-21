"""initial orchestrator schema

Revision ID: 0001_orchestrator
Revises:
Create Date: 2026-02-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_orchestrator"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("payment_id", sa.String(), nullable=False),
        sa.Column("customer_id", sa.String(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("payment_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_payments_customer_id", "payments", ["customer_id"])
    op.create_index("ix_payments_status", "payments", ["status"])
    op.create_index("ix_payments_idempotency_key", "payments", ["idempotency_key"], unique=True)

    op.create_table(
        "payment_attempts",
        sa.Column("attempt_id", sa.String(), nullable=False),
        sa.Column("payment_id", sa.String(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("result", sa.String(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.payment_id"]),
        sa.PrimaryKeyConstraint("attempt_id"),
    )
    op.create_index("ix_payment_attempts_payment_id", "payment_attempts", ["payment_id"])

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
    op.drop_index("ix_payment_attempts_payment_id", table_name="payment_attempts")
    op.drop_table("payment_attempts")
    op.drop_index("ix_payments_idempotency_key", table_name="payments")
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_index("ix_payments_customer_id", table_name="payments")
    op.drop_table("payments")
