"""Ledger posting logic with inbox/outbox reliability patterns."""

import asyncio

from sqlalchemy import select

from finpay.common.events import EventEnvelope, KafkaBus, consume_forever
from finpay.common.logging import logger
from finpay.common.metrics import duplicate_events_skipped_total
from finpay.common.outbox import (
    claim_outbox_batch,
    mark_outbox_sent,
    requeue_outbox_event,
    update_outbox_backlog_metrics,
)
from finpay.services.ledger.models import Account, InboxEvent, LedgerEntry, OutboxEvent


class LedgerService:
    """Consumes `payments.captured` and posts balanced ledger entries."""

    def __init__(self, session_factory, service_name: str = "ledger") -> None:
        self.session_factory = session_factory
        self.kafka = KafkaBus()
        self.service_name = service_name

    def ensure_accounts(self) -> None:
        """Bootstrap required accounts; retry during cold-start races."""

        retries = 20
        for attempt in range(1, retries + 1):
            try:
                with self.session_factory() as db:
                    for account_id, account_type in [
                        ("customer_cash", "CUSTOMER"),
                        ("merchant_receivable", "MERCHANT"),
                        ("platform_fee", "PLATFORM"),
                        ("clearing", "CLEARING"),
                    ]:
                        if not db.get(Account, account_id):
                            db.add(
                                Account(account_id=account_id, account_type=account_type, balance_cents=0)
                            )
                    db.commit()
                    return
            except Exception as exc:
                logger.warning("ledger account bootstrap retry=%s/%s error=%s", attempt, retries, exc)
                if attempt == retries:
                    raise
                # Keep startup resilient during cold boot when postgres is still initializing.
                import time

                time.sleep(1)

    def _inbox_seen(self, db, event_id: str) -> bool:
        return (
            db.execute(
                select(InboxEvent).where(
                    InboxEvent.event_id == event_id,
                    InboxEvent.consumed_by_service == self.service_name,
                )
            ).scalar_one_or_none()
            is not None
        )

    def _mark_inbox(self, db, event_id: str) -> None:
        db.add(InboxEvent(event_id=event_id, consumed_by_service=self.service_name))

    def _post_entry(self, db, tx_id: str, account_id: str, direction: str, amount: int) -> None:
        """Insert one ledger row and update in-memory account balance snapshot."""

        db.add(
            LedgerEntry(
                transaction_id=tx_id,
                account_id=account_id,
                direction=direction,
                amount_cents=amount,
            )
        )
        account = db.get(Account, account_id)
        if direction == "DEBIT":
            account.balance_cents -= amount
        else:
            account.balance_cents += amount

    async def handle_captured(self, event: EventEnvelope) -> None:
        """Post settlement entries and emit `payments.settled`."""

        with self.session_factory() as db:
            if self._inbox_seen(db, event.event_id):
                logger.info("duplicate event skipped topic=payments.captured event_id=%s", event.event_id)
                duplicate_events_skipped_total.labels(
                    service=self.service_name,
                    topic="payments.captured",
                ).inc()
                return

            amount = int(event.payload["amount_cents"])
            tx_id = f"settlement:{event.aggregate_id}"
            self._post_entry(db, tx_id, "customer_cash", "DEBIT", amount)
            self._post_entry(db, tx_id, "merchant_receivable", "CREDIT", amount)

            tx_entries = db.execute(
                select(LedgerEntry).where(LedgerEntry.transaction_id == tx_id)
            ).scalars().all()
            # Safety check: every transaction must balance debits and credits.
            debits = sum(e.amount_cents for e in tx_entries if e.direction == "DEBIT")
            credits = sum(e.amount_cents for e in tx_entries if e.direction == "CREDIT")
            if debits != credits:
                raise ValueError("ledger imbalance detected")

            self._mark_inbox(db, event.event_id)
            db.add(
                OutboxEvent(
                    aggregate_type="payment",
                    aggregate_id=event.aggregate_id,
                    event_type="payments.settled",
                    topic="payments.settled",
                    payload=EventEnvelope(
                        event_type="payments.settled",
                        aggregate_id=event.aggregate_id,
                        trace_id=event.trace_id,
                        payload={"transaction_id": tx_id, "amount_cents": amount},
                    ).model_dump(),
                )
            )
            db.commit()

    async def outbox_publisher(self) -> None:
        """Continuously publish ledger outbox rows to Kafka."""

        while True:
            with self.session_factory() as db:
                rows = claim_outbox_batch(db, OutboxEvent, limit=100)
                update_outbox_backlog_metrics(db, OutboxEvent, self.service_name)
                db.commit()
            for row in rows:
                try:
                    await self.kafka.publish(row["topic"], EventEnvelope(**row["payload"]))
                    with self.session_factory() as db:
                        mark_outbox_sent(db, OutboxEvent, row["id"])
                        update_outbox_backlog_metrics(db, OutboxEvent, self.service_name)
                        db.commit()
                except Exception as exc:
                    logger.exception("ledger outbox publish failed: %s", exc)
                    with self.session_factory() as db:
                        requeue_outbox_event(db, OutboxEvent, row["id"])
                        update_outbox_backlog_metrics(db, OutboxEvent, self.service_name)
                        db.commit()
            await asyncio.sleep(0.5)

    async def start_consumers(self) -> None:
        """Start Kafka consumer for captured-payment events."""

        await consume_forever("payments.captured", "ledger-captured", self.handle_captured)
