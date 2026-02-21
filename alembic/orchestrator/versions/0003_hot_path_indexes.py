"""add hot-path indexes for payments and outbox

Revision ID: 0003_hot_path_indexes
Revises: 0002_state_version_timeline
Create Date: 2026-02-18
"""

from alembic import op


revision = "0003_hot_path_indexes"
down_revision = "0002_state_version_timeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_payments_customer_id_created_at",
        "payments",
        ["customer_id", "created_at"],
    )
    op.create_index(
        "ix_outbox_events_status_created_at",
        "outbox_events",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_status_created_at", table_name="outbox_events")
    op.drop_index("ix_payments_customer_id_created_at", table_name="payments")
