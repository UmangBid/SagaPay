"""Ledger service API + lifecycle.

Consumes capture events, posts double-entry records, and exposes reconciliation
endpoints for integrity checks.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import case, func, select

from finpay.common.db import SessionLocal
from finpay.common.config import settings
from finpay.common.logging import configure_logging
from finpay.common.tracing import instrument_app, setup_tracing
from finpay.common.metrics import metrics_response
from finpay.common.startup import log_startup_config
from finpay.services.ledger.models import LedgerEntry
from finpay.services.ledger.service import LedgerService

configure_logging()
setup_tracing(settings.service_name)
log_startup_config(
    settings.service_name,
    ["SERVICE_NAME", "POSTGRES_DSN", "KAFKA_BOOTSTRAP_SERVERS", "REDIS_URL"],
)
service = LedgerService(SessionLocal)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Ensure accounts exist and start publisher/consumer loops."""

    service.ensure_accounts()
    publisher_task = asyncio.create_task(service.outbox_publisher())
    consumer_task = asyncio.create_task(service.start_consumers())
    yield
    publisher_task.cancel()
    consumer_task.cancel()
    await service.kafka.close()


app = FastAPI(title="SagaPay Ledger Service", lifespan=lifespan)
instrument_app(app)


@app.get("/reconciliation/{transaction_id}")
def reconciliation(transaction_id: str):
    """Return debit/credit details for one transaction id."""

    with SessionLocal() as db:
        entries = db.execute(
            select(LedgerEntry).where(LedgerEntry.transaction_id == transaction_id)
        ).scalars().all()
        debits = sum(e.amount_cents for e in entries if e.direction == "DEBIT")
        credits = sum(e.amount_cents for e in entries if e.direction == "CREDIT")
        return {
            "transaction_id": transaction_id,
            "balanced": debits == credits,
            "debits": debits,
            "credits": credits,
            "entries": [
                {
                    "entry_id": e.entry_id,
                    "account_id": e.account_id,
                    "direction": e.direction,
                    "amount_cents": e.amount_cents,
                }
                for e in entries
            ],
        }


@app.get("/reconciliation")
def reconciliation_report(limit: int = 1000):
    """Return global reconciliation summary over posted transactions."""

    with SessionLocal() as db:
        rows = db.execute(
            select(
                LedgerEntry.transaction_id,
                func.sum(case((LedgerEntry.direction == "DEBIT", LedgerEntry.amount_cents), else_=0)).label(
                    "debits"
                ),
                func.sum(case((LedgerEntry.direction == "CREDIT", LedgerEntry.amount_cents), else_=0)).label(
                    "credits"
                ),
                func.count(LedgerEntry.entry_id).label("entry_count"),
            )
            .group_by(LedgerEntry.transaction_id)
            .order_by(LedgerEntry.transaction_id)
            .limit(limit)
        ).all()
        imbalanced = [
            {
                "transaction_id": row.transaction_id,
                "debits": int(row.debits or 0),
                "credits": int(row.credits or 0),
                "entry_count": int(row.entry_count or 0),
            }
            for row in rows
            if int(row.debits or 0) != int(row.credits or 0)
        ]
        return {
            "transactions_checked": len(rows),
            "imbalanced_count": len(imbalanced),
            "imbalanced_transactions": imbalanced,
        }


@app.get("/metrics")
def metrics():
    """Prometheus scrape endpoint."""

    return metrics_response()


@app.get("/health")
def health():
    """Container health probe endpoint."""

    return {"ok": True}
