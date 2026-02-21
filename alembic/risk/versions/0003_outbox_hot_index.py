"""add outbox hot-path index

Revision ID: 0003_outbox_hot_index
Revises: 0002_review_queue
Create Date: 2026-02-18
"""

from alembic import op


revision = "0003_outbox_hot_index"
down_revision = "0002_review_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_outbox_events_status_created_at",
        "outbox_events",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_status_created_at", table_name="outbox_events")
