"""Provider adapter persistence models (attempts + inbox/outbox)."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from finpay.common.db import Base


class ProviderAttempt(Base):
    """One provider authorization attempt result."""

    __tablename__ = "provider_attempts"

    attempt_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    payment_id: Mapped[str] = mapped_column(String, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    result: Mapped[str] = mapped_column(String)
    latency_ms: Mapped[int] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboxEvent(Base):
    """Events awaiting Kafka publish from provider adapter."""

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
    """Deduplication records for consumed authorize requests."""

    __tablename__ = "inbox_events"
    __table_args__ = (UniqueConstraint("event_id", "consumed_by_service", name="uq_inbox_consumer"),)

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    consumed_by_service: Mapped[str] = mapped_column(String, primary_key=True)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
