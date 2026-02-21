"""Notification persistence models (delivery logs + inbox dedupe)."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from finpay.common.db import Base


class NotificationLog(Base):
    """Stored record of notification attempts sent to downstream channel."""

    __tablename__ = "notification_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    payment_id: Mapped[str] = mapped_column(String, index=True)
    channel: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InboxEvent(Base):
    """Deduplication rows for consumed terminal payment events."""

    __tablename__ = "inbox_events"
    __table_args__ = (UniqueConstraint("event_id", "consumed_by_service", name="uq_inbox_consumer"),)

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    consumed_by_service: Mapped[str] = mapped_column(String, primary_key=True)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
