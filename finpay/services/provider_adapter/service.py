"""Provider interaction simulation with retries and DLQ handling."""

import asyncio
import random
import time

from sqlalchemy import select

from finpay.common.events import EventEnvelope, KafkaBus, consume_forever
from finpay.common.logging import logger
from finpay.common.metrics import dlq_published_total, duplicate_events_skipped_total, retries_total
from finpay.common.outbox import (
    claim_outbox_batch,
    mark_outbox_sent,
    requeue_outbox_event,
    update_outbox_backlog_metrics,
)
from finpay.services.provider_adapter.models import InboxEvent, OutboxEvent, ProviderAttempt


class ProviderAdapterService:
    """Consumes authorize requests and emits authorized/failed outcomes."""

    def __init__(self, session_factory, service_name: str = "provider-adapter") -> None:
        self.session_factory = session_factory
        self.kafka = KafkaBus()
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

    def _enqueue_dlq(
        self,
        db,
        source_event: EventEnvelope,
        reason: str,
        error_type: str,
        retryable: bool,
        replay_topic: str | None = None,
    ) -> None:
        """Publish a DLQ envelope through provider outbox."""

        payload = {
            "reason": reason,
            "error_type": error_type,
            "retryable": retryable,
            "source": self.service_name,
            "source_event_id": source_event.event_id,
        }
        if replay_topic is not None:
            payload["replay_topic"] = replay_topic
            payload["failed_event"] = source_event.model_dump()
        db.add(
            OutboxEvent(
                aggregate_type="payment",
                aggregate_id=source_event.aggregate_id,
                event_type="payments.dlq",
                topic="payments.dlq",
                payload=EventEnvelope(
                    event_type="payments.dlq",
                    aggregate_id=source_event.aggregate_id,
                    trace_id=source_event.trace_id,
                    payload=payload,
                ).model_dump(),
            )
        )
        dlq_published_total.labels(
            service=self.service_name,
            topic="payments.dlq",
            error_type=error_type,
        ).inc()

    def _validate_authorize_payload(self, event: EventEnvelope) -> tuple[str, int, str]:
        """Schema/semantic validation for provider authorize requests."""

        payload = event.payload
        customer_id = payload.get("customer_id")
        currency = payload.get("currency")
        amount_cents = payload.get("amount_cents")

        if not isinstance(customer_id, str) or not customer_id:
            raise ValueError("invalid customer_id")
        if not isinstance(currency, str) or len(currency) != 3:
            raise ValueError("invalid currency")
        if not isinstance(amount_cents, int) or amount_cents <= 0:
            raise ValueError("invalid amount_cents")
        return customer_id, amount_cents, currency

    async def handle_authorize_request(self, event: EventEnvelope) -> None:
        """Run provider flow with retry/backoff and terminal failure handling."""

        with self.session_factory() as db:
            if self._inbox_seen(db, event.event_id):
                logger.info(
                    "duplicate event skipped topic=provider.authorize.requested event_id=%s",
                    event.event_id,
                )
                duplicate_events_skipped_total.labels(
                    service=self.service_name,
                    topic="provider.authorize.requested",
                ).inc()
                return
            self._mark_inbox(db, event.event_id)
            try:
                customer_id, _, _ = self._validate_authorize_payload(event)
            except ValueError as exc:
                self._enqueue_dlq(
                    db,
                    source_event=event,
                    reason=str(exc),
                    error_type="NON_RETRYABLE",
                    retryable=False,
                    replay_topic=None,
                )
                db.commit()
                logger.warning(
                    "non-retryable provider request dropped event_id=%s reason=%s",
                    event.event_id,
                    exc,
                )
                return
            db.commit()

        max_retries = 3
        last_error = "UNKNOWN"
        force_timeout = customer_id.lower().startswith("force-timeout")
        force_decline = customer_id.lower().startswith("force-decline")
        for attempt in range(1, max_retries + 1):
            start = time.perf_counter()
            if force_timeout:
                outcome = "TIMEOUT"
            elif force_decline:
                outcome = "DECLINE"
            else:
                outcome = random.choices(
                    population=["SUCCESS", "TIMEOUT", "DECLINE"],
                    weights=[0.70, 0.20, 0.10],
                    k=1,
                )[0]
            latency_ms = int((time.perf_counter() - start) * 1000)
            if outcome == "SUCCESS":
                with self.session_factory() as db:
                    db.add(
                        ProviderAttempt(
                            payment_id=event.aggregate_id,
                            attempt_number=attempt,
                            result="AUTHORIZED",
                            latency_ms=latency_ms,
                            error_code=None,
                        )
                    )
                    db.add(
                        OutboxEvent(
                            aggregate_type="payment",
                            aggregate_id=event.aggregate_id,
                            event_type="payments.authorized",
                            topic="payments.authorized",
                            payload=EventEnvelope(
                                event_type="payments.authorized",
                                aggregate_id=event.aggregate_id,
                                trace_id=event.trace_id,
                                payload={"attempt_number": attempt, "latency_ms": latency_ms},
                            ).model_dump(),
                        )
                    )
                    db.commit()
                return

            if outcome == "DECLINE":
                last_error = "PROVIDER_DECLINE"
                with self.session_factory() as db:
                    db.add(
                        ProviderAttempt(
                            payment_id=event.aggregate_id,
                            attempt_number=attempt,
                            result="FAILED",
                            latency_ms=latency_ms,
                            error_code=last_error,
                        )
                    )
                    db.add(
                        OutboxEvent(
                            aggregate_type="payment",
                            aggregate_id=event.aggregate_id,
                            event_type="payments.failed",
                            topic="payments.failed",
                            payload=EventEnvelope(
                                event_type="payments.failed",
                                aggregate_id=event.aggregate_id,
                                trace_id=event.trace_id,
                                payload={
                                    "attempt_number": attempt,
                                    "latency_ms": latency_ms,
                                    "error_code": last_error,
                                },
                            ).model_dump(),
                        )
                    )
                    db.commit()
                return

            last_error = "PROVIDER_TIMEOUT"
            retries_total.labels(service=self.service_name, dependency="provider").inc()
            # Exponential backoff: 1s, 2s, 4s.
            backoff_seconds = 2 ** (attempt - 1)
            logger.warning(
                "provider timeout payment_id=%s attempt=%s backoff_s=%s",
                event.aggregate_id,
                attempt,
                backoff_seconds,
            )
            await asyncio.sleep(backoff_seconds)

        with self.session_factory() as db:
            db.add(
                OutboxEvent(
                    aggregate_type="payment",
                    aggregate_id=event.aggregate_id,
                    event_type="payments.failed",
                    topic="payments.failed",
                    payload=EventEnvelope(
                        event_type="payments.failed",
                        aggregate_id=event.aggregate_id,
                        trace_id=event.trace_id,
                        payload={"attempt_number": max_retries, "latency_ms": 0, "error_code": last_error},
                    ).model_dump(),
                )
            )
            self._enqueue_dlq(
                db,
                source_event=event,
                reason=last_error,
                error_type="RETRY_EXHAUSTED",
                retryable=True,
                replay_topic="provider.authorize.requested",
            )
            db.commit()

    async def outbox_publisher(self) -> None:
        """Continuously publish provider outbox rows."""

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
                    logger.exception("provider outbox publish failed: %s", exc)
                    with self.session_factory() as db:
                        requeue_outbox_event(db, OutboxEvent, row["id"])
                        update_outbox_backlog_metrics(db, OutboxEvent, self.service_name)
                        db.commit()
            await asyncio.sleep(0.5)

    async def start_consumers(self) -> None:
        """Start Kafka consumer for authorization requests."""

        await consume_forever(
            "provider.authorize.requested",
            "provider-authorize-requested",
            self.handle_authorize_request,
        )
