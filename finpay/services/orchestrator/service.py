"""Orchestrator saga logic.

Coordinates state transitions, emits next-step events, enforces idempotency via
inbox/outbox, and records timeline + terminal latency metrics.
"""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select, update

from finpay.common.events import EventEnvelope, KafkaBus, consume_forever
from finpay.common.logging import logger
from finpay.common.metrics import (
    duplicate_events_skipped_total,
    payment_e2e_seconds,
    payment_failure_total,
    payment_success_total,
)
from finpay.common.outbox import (
    claim_outbox_batch,
    mark_outbox_sent,
    requeue_outbox_event,
    update_outbox_backlog_metrics,
)
from finpay.common.state_machine import validate_transition
from finpay.services.orchestrator.models import (
    InboxEvent,
    OutboxEvent,
    Payment,
    PaymentAttempt,
    PaymentTimeline,
)


class OrchestratorService:
    """Owns payment state machine progression and saga orchestration."""

    def __init__(self, session_factory, service_name: str = "orchestrator") -> None:
        self.session_factory = session_factory
        self.kafka = KafkaBus()
        self.service_name = service_name

    def create_payment(self, req, trace_id: str) -> Payment:
        """Create payment row once per idempotency key and enqueue first event."""

        with self.session_factory() as db:
            existing = db.execute(
                select(Payment).where(Payment.idempotency_key == req.idempotency_key)
            ).scalar_one_or_none()
            if existing:
                return existing

            payment = Payment(
                customer_id=req.customer_id,
                amount_cents=req.amount_cents,
                currency=req.currency.upper(),
                status="CREATED",
                idempotency_key=req.idempotency_key,
            )
            db.add(payment)
            db.flush()
            db.add(
                PaymentTimeline(
                    payment_id=payment.payment_id,
                    from_state=None,
                    to_state="CREATED",
                    reason="payment_created",
                    event_id=None,
                )
            )

            outbox = OutboxEvent(
                aggregate_type="payment",
                aggregate_id=payment.payment_id,
                event_type="payments.requested",
                topic="payments.requested",
                payload=EventEnvelope(
                    event_type="payments.requested",
                    aggregate_id=payment.payment_id,
                    trace_id=trace_id,
                    payload={
                        "customer_id": payment.customer_id,
                        "amount_cents": payment.amount_cents,
                        "currency": payment.currency,
                    },
                ).model_dump(),
            )
            db.add(outbox)
            db.commit()
            return payment

    def _inbox_seen(self, db, event_id: str) -> bool:
        existing = db.execute(
            select(InboxEvent).where(
                InboxEvent.event_id == event_id,
                InboxEvent.consumed_by_service == self.service_name,
            )
        ).scalar_one_or_none()
        return existing is not None

    def _mark_inbox(self, db, event_id: str) -> None:
        db.add(InboxEvent(event_id=event_id, consumed_by_service=self.service_name))

    def _record_duplicate_skip(self, topic: str) -> None:
        duplicate_events_skipped_total.labels(service=self.service_name, topic=topic).inc()

    def _observe_terminal_e2e(self, payment: Payment, terminal_state: str) -> None:
        if payment.created_at is None:
            return
        created_at = payment.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        elapsed = max(0.0, (datetime.now(timezone.utc) - created_at).total_seconds())
        payment_e2e_seconds.labels(service=self.service_name, terminal_state=terminal_state).observe(elapsed)

    def _transition(
        self, db, payment: Payment, new_status: str, reason: str, event_id: str | None
    ) -> None:
        """Apply one validated state transition with optimistic concurrency.

        Transition writes are guarded by `(payment_id, status, state_version)` to
        prevent stale concurrent updates from succeeding.
        """

        validate_transition(payment.status, new_status)
        from_status = payment.status
        current_version = payment.state_version

        result = db.execute(
            update(Payment)
            .where(
                Payment.payment_id == payment.payment_id,
                Payment.status == from_status,
                Payment.state_version == current_version,
            )
            .values(
                status=new_status,
                state_version=current_version + 1,
                updated_at=datetime.now(timezone.utc),
            )
        )
        if result.rowcount != 1:
            raise RuntimeError(
                f"optimistic concurrency conflict for payment {payment.payment_id} "
                f"(expected version {current_version})"
            )

        payment.status = new_status
        payment.state_version = current_version + 1
        db.add(
            PaymentTimeline(
                payment_id=payment.payment_id,
                from_state=from_status,
                to_state=new_status,
                reason=reason,
                event_id=event_id,
            )
        )

    async def handle_risk_approved(self, event: EventEnvelope) -> None:
        """Move payment forward and request provider authorization."""

        with self.session_factory() as db:
            if self._inbox_seen(db, event.event_id):
                logger.info("duplicate event skipped topic=risk.approved event_id=%s", event.event_id)
                self._record_duplicate_skip("risk.approved")
                return
            payment = db.get(Payment, event.aggregate_id)
            if not payment:
                self._mark_inbox(db, event.event_id)
                db.commit()
                return

            self._transition(
                db,
                payment,
                "APPROVED",
                reason="risk_approved",
                event_id=event.event_id,
            )
            self._mark_inbox(db, event.event_id)
            db.add(
                OutboxEvent(
                    aggregate_type="payment",
                    aggregate_id=payment.payment_id,
                    event_type="provider.authorize.requested",
                    topic="provider.authorize.requested",
                    payload=EventEnvelope(
                        event_type="provider.authorize.requested",
                        aggregate_id=payment.payment_id,
                        trace_id=event.trace_id,
                        payload={
                            "amount_cents": payment.amount_cents,
                            "currency": payment.currency,
                            "customer_id": payment.customer_id,
                        },
                    ).model_dump(),
                )
            )
            db.commit()

    async def handle_risk_denied(self, event: EventEnvelope) -> None:
        """Handle DENY/REVIEW decisions from risk service."""

        with self.session_factory() as db:
            if self._inbox_seen(db, event.event_id):
                logger.info("duplicate event skipped topic=risk.denied event_id=%s", event.event_id)
                self._record_duplicate_skip("risk.denied")
                return
            payment = db.get(Payment, event.aggregate_id)
            if not payment:
                self._mark_inbox(db, event.event_id)
                db.commit()
                return
            target = "RISK_REVIEW" if event.payload.get("decision") == "REVIEW" else "FAILED"
            reason = "risk_review_required" if target == "RISK_REVIEW" else "risk_denied"
            self._transition(db, payment, target, reason=reason, event_id=event.event_id)
            self._mark_inbox(db, event.event_id)
            db.commit()
            payment_failure_total.labels(service=self.service_name).inc()

    async def handle_authorized(self, event: EventEnvelope) -> None:
        """Record authorization, move to CAPTURED, and request ledger settlement."""

        with self.session_factory() as db:
            if self._inbox_seen(db, event.event_id):
                logger.info("duplicate event skipped topic=payments.authorized event_id=%s", event.event_id)
                self._record_duplicate_skip("payments.authorized")
                return
            payment = db.get(Payment, event.aggregate_id)
            if not payment:
                self._mark_inbox(db, event.event_id)
                db.commit()
                return
            self._transition(
                db,
                payment,
                "AUTHORIZED",
                reason="provider_authorized",
                event_id=event.event_id,
            )
            self._transition(
                db,
                payment,
                "CAPTURED",
                reason="capture_requested",
                event_id=event.event_id,
            )
            db.add(
                PaymentAttempt(
                    payment_id=payment.payment_id,
                    attempt_number=event.payload.get("attempt_number", 1),
                    result="AUTHORIZED",
                    latency_ms=event.payload.get("latency_ms", 0),
                    error_code=None,
                )
            )
            self._mark_inbox(db, event.event_id)
            db.add(
                OutboxEvent(
                    aggregate_type="payment",
                    aggregate_id=payment.payment_id,
                    event_type="payments.captured",
                    topic="payments.captured",
                    payload=EventEnvelope(
                        event_type="payments.captured",
                        aggregate_id=payment.payment_id,
                        trace_id=event.trace_id,
                        payload={
                            "amount_cents": payment.amount_cents,
                            "currency": payment.currency,
                            "customer_id": payment.customer_id,
                        },
                    ).model_dump(),
                )
            )
            db.commit()

    async def handle_failed(self, event: EventEnvelope) -> None:
        """Handle provider failures and run compensation for timeout terminals."""

        with self.session_factory() as db:
            if self._inbox_seen(db, event.event_id):
                logger.info("duplicate event skipped topic=payments.failed event_id=%s", event.event_id)
                self._record_duplicate_skip("payments.failed")
                return
            payment = db.get(Payment, event.aggregate_id)
            if not payment:
                self._mark_inbox(db, event.event_id)
                db.commit()
                return
            if payment.status != "FAILED":
                self._transition(
                    db,
                    payment,
                    "FAILED",
                    reason=f"provider_failed:{event.payload.get('error_code', 'UNKNOWN')}",
                    event_id=event.event_id,
                )
            db.add(
                PaymentAttempt(
                    payment_id=payment.payment_id,
                    attempt_number=event.payload.get("attempt_number", 1),
                    result="FAILED",
                    latency_ms=event.payload.get("latency_ms", 0),
                    error_code=event.payload.get("error_code", "UNKNOWN"),
                )
            )
            # Compensation path: terminal provider timeout is auto-voided/reversed.
            if event.payload.get("error_code") == "PROVIDER_TIMEOUT":
                self._transition(
                    db,
                    payment,
                    "REVERSED",
                    reason="provider_timeout_compensation",
                    event_id=event.event_id,
                )
                db.add(
                    OutboxEvent(
                        aggregate_type="payment",
                        aggregate_id=payment.payment_id,
                        event_type="payments.reversed",
                        topic="payments.reversed",
                        payload=EventEnvelope(
                            event_type="payments.reversed",
                            aggregate_id=payment.payment_id,
                            trace_id=event.trace_id,
                            payload={
                                "reason": "provider_timeout_compensation",
                                "source_event_id": event.event_id,
                            },
                        ).model_dump(),
                    )
                )
            self._mark_inbox(db, event.event_id)
            db.commit()
            self._observe_terminal_e2e(payment, payment.status)
            payment_failure_total.labels(service=self.service_name).inc()

    async def handle_settled(self, event: EventEnvelope) -> None:
        """Mark payment as SETTLED after ledger posts balanced entries."""

        with self.session_factory() as db:
            if self._inbox_seen(db, event.event_id):
                logger.info("duplicate event skipped topic=payments.settled event_id=%s", event.event_id)
                self._record_duplicate_skip("payments.settled")
                return
            payment = db.get(Payment, event.aggregate_id)
            if not payment:
                self._mark_inbox(db, event.event_id)
                db.commit()
                return
            self._transition(
                db,
                payment,
                "SETTLED",
                reason="ledger_settled",
                event_id=event.event_id,
            )
            self._mark_inbox(db, event.event_id)
            db.commit()
            self._observe_terminal_e2e(payment, "SETTLED")
            payment_success_total.labels(service=self.service_name).inc()

    async def outbox_publisher(self) -> None:
        """Continuously publish and ack pending outbox events."""

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
                    logger.exception("outbox publish failed: %s", exc)
                    with self.session_factory() as db:
                        requeue_outbox_event(db, OutboxEvent, row["id"])
                        update_outbox_backlog_metrics(db, OutboxEvent, self.service_name)
                        db.commit()
            await asyncio.sleep(0.5)

    async def start_consumers(self) -> None:
        """Start all orchestrator Kafka consumers in parallel."""

        await asyncio.gather(
            consume_forever("risk.approved", "orchestrator-risk-approved", self.handle_risk_approved),
            consume_forever("risk.denied", "orchestrator-risk-denied", self.handle_risk_denied),
            consume_forever("payments.authorized", "orchestrator-authorized", self.handle_authorized),
            consume_forever("payments.failed", "orchestrator-failed", self.handle_failed),
            consume_forever("payments.settled", "orchestrator-settled", self.handle_settled),
        )
