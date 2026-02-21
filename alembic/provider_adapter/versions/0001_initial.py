"""initial provider adapter schema

Revision ID: 0001_provider_adapter
Revises:
Create Date: 2026-02-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_provider_adapter"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_attempts",
        sa.Column("attempt_id", sa.String(), nullable=False),
        sa.Column("payment_id", sa.String(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("result", sa.String(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("attempt_id"),
    )
    op.create_index("ix_provider_attempts_payment_id", "provider_attempts", ["payment_id"])

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
    op.drop_index("ix_provider_attempts_payment_id", table_name="provider_attempts")
    op.drop_table("provider_attempts")
