"""Risk decision engine and manual-review orchestration."""

import asyncio
from datetime import datetime, timezone

import httpx
import redis
from sqlalchemy import select

from finpay.common.config import settings
from finpay.common.events import EventEnvelope, KafkaBus, consume_forever
from finpay.common.logging import logger
from finpay.common.metrics import duplicate_events_skipped_total
from finpay.common.outbox import (
    claim_outbox_batch,
    mark_outbox_sent,
    requeue_outbox_event,
    update_outbox_backlog_metrics,
)
from finpay.services.risk.models import InboxEvent, OutboxEvent, RiskReview


class RiskService:
    """Consumes `payments.requested` and emits risk outcomes."""

    def __init__(self, session_factory, service_name: str = "risk") -> None:
        self.session_factory = session_factory
        self.kafka = KafkaBus()
        self.rdb = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        self.service_name = service_name

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

    def _fetch_orchestrator_payment_status(self, payment_id: str) -> str:
        """Validate payment state before manual decision actions."""

        url = f"{settings.orchestrator_url}/payments/{payment_id}"
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url)
        if resp.status_code == 404:
            raise ValueError("payment not found in orchestrator")
        if resp.status_code >= 400:
            raise ValueError(f"failed to validate payment status (status={resp.status_code})")
        payload = resp.json()
        status = payload.get("status")
        if not isinstance(status, str):
            raise ValueError("orchestrator status response malformed")
        return status

    def _rule_decision(self, customer_id: str, amount_cents: int) -> tuple[str, str]:
        """Apply velocity/high-amount/failed-attempt rules."""

        hour_key = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        velocity_key = f"velocity:{customer_id}:{hour_key}"
        current_hour_count = self.rdb.incr(velocity_key)
        self.rdb.expire(velocity_key, 7200)

        failed_key = f"failed_attempts:{customer_id}"
        failed_attempts = int(self.rdb.get(failed_key) or 0)

        if current_hour_count > settings.risk_deny_frequency_threshold:
            return "DENY", "high_frequency"
        if amount_cents > settings.risk_review_amount_cents:
            return "REVIEW", "high_amount"
        if failed_attempts >= 3:
            return "REVIEW", "multiple_failed_attempts"
        if current_hour_count > settings.risk_velocity_per_hour:
            return "REVIEW", "velocity_threshold"
        return "APPROVE", "rule_passed"

    async def handle_payment_requested(self, event: EventEnvelope) -> None:
        """Evaluate a requested payment and enqueue APPROVE/DENY/REVIEW outcome."""

        with self.session_factory() as db:
            if self._inbox_seen(db, event.event_id):
                logger.info("duplicate event skipped topic=payments.requested event_id=%s", event.event_id)
                duplicate_events_skipped_total.labels(
                    service=self.service_name,
                    topic="payments.requested",
                ).inc()
                return
            payload = event.payload
            customer_id = payload["customer_id"]
            amount_cents = int(payload["amount_cents"])
            decision, reason = self._rule_decision(customer_id, amount_cents)
            topic = "risk.approved" if decision == "APPROVE" else "risk.denied"
            if decision == "REVIEW":
                existing_review = db.execute(
                    select(RiskReview).where(RiskReview.payment_id == event.aggregate_id)
                ).scalar_one_or_none()
                if existing_review is None:
                    db.add(
                        RiskReview(
                            payment_id=event.aggregate_id,
                            customer_id=customer_id,
                            amount_cents=amount_cents,
                            reason=reason,
                            status="PENDING",
                        )
                    )
            out_event = EventEnvelope(
                event_type=topic,
                aggregate_id=event.aggregate_id,
                trace_id=event.trace_id,
                payload={"decision": decision, "reason": reason, "customer_id": customer_id},
            )
            db.add(
                OutboxEvent(
                    aggregate_type="payment",
                    aggregate_id=event.aggregate_id,
                    event_type=topic,
                    topic=topic,
                    payload=out_event.model_dump(),
                )
            )
            self._mark_inbox(db, event.event_id)
            db.commit()

    def list_reviews(self, status: str = "PENDING", limit: int = 100) -> list[RiskReview]:
        """Return review queue rows for ops tooling."""

        with self.session_factory() as db:
            return (
                db.execute(
                    select(RiskReview)
                    .where(RiskReview.status == status)
                    .order_by(RiskReview.created_at.asc())
                    .limit(limit)
                )
                .scalars()
                .all()
            )

    def manual_decision(self, payment_id: str, decision: str, reviewed_by: str, trace_id: str) -> RiskReview:
        """Finalize one review row and emit corresponding risk event."""

        if decision not in {"APPROVE", "DENY"}:
            raise ValueError("decision must be APPROVE or DENY")

        with self.session_factory() as db:
            review = db.execute(select(RiskReview).where(RiskReview.payment_id == payment_id)).scalar_one_or_none()
            if review is None:
                raise ValueError("review not found")
            if review.status != "PENDING":
                raise ValueError(f"review already finalized with status={review.status}")
            orchestrator_status = self._fetch_orchestrator_payment_status(payment_id)
            if orchestrator_status != "RISK_REVIEW":
                raise ValueError(
                    f"payment must be in RISK_REVIEW for manual decision (current={orchestrator_status})"
                )

            topic = "risk.approved" if decision == "APPROVE" else "risk.denied"
            reviewed_at = datetime.now(timezone.utc)
            event = EventEnvelope(
                event_type=topic,
                aggregate_id=payment_id,
                trace_id=trace_id,
                payload={
                    "decision": decision,
                    "reason": f"manual_{decision.lower()}",
                    "customer_id": review.customer_id,
                    "reviewed_by": reviewed_by,
                    "reviewed_at": reviewed_at.isoformat(),
                    "review_status": "APPROVED" if decision == "APPROVE" else "DENIED",
                },
            )
            db.add(
                OutboxEvent(
                    aggregate_type="payment",
                    aggregate_id=payment_id,
                    event_type=topic,
                    topic=topic,
                    payload=event.model_dump(),
                )
            )
            review.status = "APPROVED" if decision == "APPROVE" else "DENIED"
            review.reviewed_by = reviewed_by
            review.reviewed_at = reviewed_at
            review.decision_event_id = event.event_id
            db.commit()
            db.refresh(review)
            return review

    async def outbox_publisher(self) -> None:
        """Continuously publish risk outbox events to Kafka."""

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
                    logger.exception("risk outbox publish failed: %s", exc)
                    with self.session_factory() as db:
                        requeue_outbox_event(db, OutboxEvent, row["id"])
                        update_outbox_backlog_metrics(db, OutboxEvent, self.service_name)
                        db.commit()
            await asyncio.sleep(0.5)

    async def start_consumers(self) -> None:
        """Start Kafka consumer for payment-requested events."""

        await consume_forever("payments.requested", "risk-payments-requested", self.handle_payment_requested)
