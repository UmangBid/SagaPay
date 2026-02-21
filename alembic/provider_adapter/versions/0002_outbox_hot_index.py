"""add outbox hot-path index

Revision ID: 0002_provider_outbox_hot_index
Revises: 0001_provider_adapter
Create Date: 2026-02-18
"""

from alembic import op


revision = "0002_provider_outbox_hot_index"
down_revision = "0001_provider_adapter"
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
