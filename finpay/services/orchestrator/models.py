"""Orchestrator database models.

This DB is the source of truth for payment state, attempts, timeline, and
service-local outbox/inbox records.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from finpay.common.db import Base


class Payment(Base):
    """Current state of a payment aggregate."""

    __tablename__ = "payments"

    payment_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    customer_id: Mapped[str] = mapped_column(String, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String, index=True)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PaymentAttempt(Base):
    """Operational record of provider authorization outcomes."""

    __tablename__ = "payment_attempts"

    attempt_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.payment_id"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    result: Mapped[str] = mapped_column(String)
    latency_ms: Mapped[int] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaymentTimeline(Base):
    """Immutable audit trail of every state transition."""

    __tablename__ = "payment_timeline"

    timeline_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.payment_id"), index=True)
    from_state: Mapped[str | None] = mapped_column(String, nullable=True)
    to_state: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    event_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboxEvent(Base):
    """Events waiting to be published to Kafka by orchestrator."""

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
    """Deduplication table for consumed Kafka events."""

    __tablename__ = "inbox_events"
    __table_args__ = (UniqueConstraint("event_id", "consumed_by_service", name="uq_inbox_consumer"),)

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    consumed_by_service: Mapped[str] = mapped_column(String, primary_key=True)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
