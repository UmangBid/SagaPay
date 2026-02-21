"""add payment state versioning and timeline

Revision ID: 0002_state_version_timeline
Revises: 0001_orchestrator
Create Date: 2026-02-18
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_state_version_timeline"
down_revision = "0001_orchestrator"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("state_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.alter_column("payments", "state_version", server_default=None)

    op.create_table(
        "payment_timeline",
        sa.Column("timeline_id", sa.String(), nullable=False),
        sa.Column("payment_id", sa.String(), nullable=False),
        sa.Column("from_state", sa.String(), nullable=True),
        sa.Column("to_state", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.payment_id"]),
        sa.PrimaryKeyConstraint("timeline_id"),
    )
    op.create_index("ix_payment_timeline_payment_id", "payment_timeline", ["payment_id"])
    op.create_index("ix_payment_timeline_event_id", "payment_timeline", ["event_id"])


def downgrade() -> None:
    op.drop_index("ix_payment_timeline_event_id", table_name="payment_timeline")
    op.drop_index("ix_payment_timeline_payment_id", table_name="payment_timeline")
    op.drop_table("payment_timeline")
    op.drop_column("payments", "state_version")
