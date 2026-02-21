"""initial notification schema

Revision ID: 0001_notification
Revises:
Create Date: 2026-02-17
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_notification"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_logs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("payment_id", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notification_logs_payment_id", "notification_logs", ["payment_id"])

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
    op.drop_index("ix_notification_logs_payment_id", table_name="notification_logs")
    op.drop_table("notification_logs")
