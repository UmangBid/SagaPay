"""Risk service persistence models (review queue + inbox/outbox)."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from finpay.common.db import Base


class OutboxEvent(Base):
    """Events produced by risk service and published asynchronously."""

    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    aggregate_type: Mapped[str] = mapped_column(String)
    aggregate_id: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    topic: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String, default="PENDING", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InboxEvent(Base):
    """Deduplication records for consumed Kafka events."""

    __tablename__ = "inbox_events"
    __table_args__ = (UniqueConstraint("event_id", "consumed_by_service", name="uq_inbox_consumer"),)

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    consumed_by_service: Mapped[str] = mapped_column(String, primary_key=True)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RiskReview(Base):
    """Manual review queue entry for payments blocked in `RISK_REVIEW`."""

    __tablename__ = "risk_reviews"

    review_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    payment_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    customer_id: Mapped[str] = mapped_column(String, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, index=True, default="PENDING")
    reviewed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
