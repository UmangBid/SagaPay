"""Ledger database models for accounts, entries, and inbox/outbox."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from finpay.common.db import Base


class Account(Base):
    """Logical account used for double-entry postings."""

    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    account_type: Mapped[str] = mapped_column(String, index=True)
    balance_cents: Mapped[int] = mapped_column(Integer, default=0)


class LedgerEntry(Base):
    """Immutable debit/credit record for one transaction leg."""

    __tablename__ = "ledger_entries"

    entry_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    transaction_id: Mapped[str] = mapped_column(String, index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    direction: Mapped[str] = mapped_column(String)
    amount_cents: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboxEvent(Base):
    """Events waiting to be published by ledger outbox worker."""

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
    """Deduplication rows for consumed capture events."""

    __tablename__ = "inbox_events"
    __table_args__ = (UniqueConstraint("event_id", "consumed_by_service", name="uq_inbox_consumer"),)

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    consumed_by_service: Mapped[str] = mapped_column(String, primary_key=True)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
