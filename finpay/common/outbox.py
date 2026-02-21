"""Reusable helpers for transactional outbox publishing.

These utilities are intentionally model-agnostic so each service can reuse the
same claim/requeue/mark logic against its own `outbox_events` table.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, update

from finpay.common.metrics import outbox_oldest_pending_age_seconds, outbox_pending_total


def claim_outbox_batch(db, outbox_model, limit: int = 100, processing_timeout_seconds: int = 30) -> list[dict]:
    """Atomically claim a batch of pending/stale rows for publishing."""

    table = outbox_model.__table__
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=processing_timeout_seconds)
    claim_ids = (
        select(table.c.id)
        .where(
            or_(
                table.c.status == "PENDING",
                (table.c.status == "PROCESSING") & (table.c.sent_at.is_not(None)) & (table.c.sent_at < stale_before),
            )
        )
        .order_by(table.c.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .cte("claim_ids")
    )
    rows = db.execute(
        update(table)
        .where(table.c.id.in_(select(claim_ids.c.id)))
        .values(status="PROCESSING", sent_at=now)
        .returning(table.c.id, table.c.topic, table.c.payload)
    ).all()
    return [{"id": row.id, "topic": row.topic, "payload": row.payload} for row in rows]


def mark_outbox_sent(db, outbox_model, event_id: str) -> None:
    """Mark one claimed outbox row as delivered."""

    table = outbox_model.__table__
    db.execute(
        update(table)
        .where(table.c.id == event_id, table.c.status == "PROCESSING")
        .values(status="SENT", sent_at=datetime.now(timezone.utc))
    )


def requeue_outbox_event(db, outbox_model, event_id: str) -> None:
    """Return a claimed row to `PENDING` so it can be retried."""

    table = outbox_model.__table__
    db.execute(
        update(table)
        .where(table.c.id == event_id, table.c.status == "PROCESSING")
        .values(status="PENDING", sent_at=None)
    )


def update_outbox_backlog_metrics(db, outbox_model, service_name: str) -> None:
    """Update service-level gauges for pending outbox depth and oldest age."""

    table = outbox_model.__table__
    now = datetime.now(timezone.utc)
    pending_statuses = ("PENDING", "PROCESSING")
    pending_count = (
        db.execute(select(func.count()).select_from(table).where(table.c.status.in_(pending_statuses))).scalar_one()
    )
    oldest_pending = db.execute(
        select(func.min(table.c.created_at)).where(table.c.status.in_(pending_statuses))
    ).scalar_one()
    age_seconds = 0.0
    if oldest_pending is not None:
        if oldest_pending.tzinfo is None:
            oldest_pending = oldest_pending.replace(tzinfo=timezone.utc)
        age_seconds = max(0.0, (now - oldest_pending).total_seconds())
    outbox_pending_total.labels(service=service_name).set(float(pending_count))
    outbox_oldest_pending_age_seconds.labels(service=service_name).set(age_seconds)
