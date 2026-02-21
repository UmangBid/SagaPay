"""Notification consumer for terminal payment events."""

from sqlalchemy import select

from finpay.common.events import EventEnvelope, consume_forever
from finpay.common.logging import logger
from finpay.common.metrics import duplicate_events_skipped_total
from finpay.services.notification.models import InboxEvent, NotificationLog


class NotificationService:
    """Writes simple notification logs for failed/settled outcomes."""

    def __init__(self, session_factory, service_name: str = "notification") -> None:
        self.session_factory = session_factory
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

    async def handle_result(self, event: EventEnvelope) -> None:
        """Persist one notification log, skipping duplicate events safely."""

        with self.session_factory() as db:
            if self._inbox_seen(db, event.event_id):
                logger.info("duplicate event skipped topic=%s event_id=%s", event.event_type, event.event_id)
                duplicate_events_skipped_total.labels(
                    service=self.service_name,
                    topic=event.event_type,
                ).inc()
                return
            message = f"Payment {event.aggregate_id} event={event.event_type}"
            db.add(
                NotificationLog(
                    payment_id=event.aggregate_id,
                    channel="webhook",
                    message=message,
                )
            )
            self._mark_inbox(db, event.event_id)
            db.commit()
            logger.info(message)

    async def start_consumers(self) -> None:
        """Start both failed and settled event consumers."""

        import asyncio

        await asyncio.gather(
            consume_forever("payments.failed", "notification-failed", self.handle_result),
            consume_forever("payments.settled", "notification-settled", self.handle_result),
        )
