"""add risk review queue

Revision ID: 0002_review_queue
Revises: 0001_risk
Create Date: 2026-02-18
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_review_queue"
down_revision = "0001_risk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "risk_reviews",
        sa.Column("review_id", sa.String(), nullable=False),
        sa.Column("payment_id", sa.String(), nullable=False),
        sa.Column("customer_id", sa.String(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reviewed_by", sa.String(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_event_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("review_id"),
        sa.UniqueConstraint("payment_id"),
    )
    op.create_index("ix_risk_reviews_payment_id", "risk_reviews", ["payment_id"], unique=True)
    op.create_index("ix_risk_reviews_customer_id", "risk_reviews", ["customer_id"])
    op.create_index("ix_risk_reviews_status", "risk_reviews", ["status"])


def downgrade() -> None:
    op.drop_index("ix_risk_reviews_status", table_name="risk_reviews")
    op.drop_index("ix_risk_reviews_customer_id", table_name="risk_reviews")
    op.drop_index("ix_risk_reviews_payment_id", table_name="risk_reviews")
    op.drop_table("risk_reviews")
