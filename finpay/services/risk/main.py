"""Risk service API + worker lifecycle.

This service evaluates risk rules and exposes manual review endpoints for ops.
"""

import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from finpay.common.db import SessionLocal
from finpay.common.config import settings
from finpay.common.logging import configure_logging, trace_id_ctx
from finpay.common.tracing import instrument_app, setup_tracing
from finpay.common.metrics import metrics_response
from finpay.common.startup import log_startup_config
from finpay.services.risk.service import RiskService

configure_logging()
setup_tracing(settings.service_name)
log_startup_config(
    settings.service_name,
    [
        "SERVICE_NAME",
        "POSTGRES_DSN",
        "KAFKA_BOOTSTRAP_SERVERS",
        "REDIS_URL",
        "RISK_VELOCITY_PER_HOUR",
        "RISK_REVIEW_AMOUNT_CENTS",
        "RISK_DENY_FREQUENCY_THRESHOLD",
    ],
)
service = RiskService(SessionLocal)


class ManualReviewRequest(BaseModel):
    """Body required for manual approve/deny actions."""

    reviewed_by: str = Field(min_length=1)


def enforce_api_key(x_api_key: str | None) -> None:
    """Simple API-key gate for ops endpoints."""

    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="invalid API key")


def _decision_error(exc: ValueError) -> HTTPException:
    """Map service validation errors to HTTP status codes."""

    message = str(exc)
    if "must be in RISK_REVIEW" in message or "already finalized" in message:
        return HTTPException(status_code=409, detail=message)
    if "not found" in message:
        return HTTPException(status_code=404, detail=message)
    return HTTPException(status_code=400, detail=message)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Run outbox publisher + consumer loops with application lifecycle."""

    publisher_task = asyncio.create_task(service.outbox_publisher())
    consumer_task = asyncio.create_task(service.start_consumers())
    yield
    publisher_task.cancel()
    consumer_task.cancel()
    await service.kafka.close()


app = FastAPI(title="SagaPay Risk Service", lifespan=lifespan)
instrument_app(app)


@app.get("/health")
def health():
    """Container health probe endpoint."""

    return {"ok": True}


@app.get("/metrics")
def metrics():
    """Prometheus scrape endpoint."""

    return metrics_response()


@app.get("/ops/reviews")
def get_reviews(
    status: str = "PENDING",
    limit: int = 100,
    x_api_key: str | None = Header(default=None),
):
    """List review queue rows (default: pending)."""

    enforce_api_key(x_api_key)
    rows = service.list_reviews(status=status.upper(), limit=limit)
    return [
        {
            "payment_id": row.payment_id,
            "customer_id": row.customer_id,
            "amount_cents": row.amount_cents,
            "reason": row.reason,
            "status": row.status,
            "reviewed_by": row.reviewed_by,
            "reviewed_at": row.reviewed_at,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@app.post("/ops/reviews/{payment_id}/approve")
def approve_review(
    payment_id: str,
    req: ManualReviewRequest,
    x_api_key: str | None = Header(default=None),
    x_trace_id: str | None = Header(default=None),
):
    """Manually approve a review item and emit `risk.approved`."""

    enforce_api_key(x_api_key)
    trace_id = x_trace_id or str(uuid4())
    trace_id_ctx.set(trace_id)
    try:
        row = service.manual_decision(payment_id, "APPROVE", req.reviewed_by, trace_id)
    except ValueError as exc:
        raise _decision_error(exc) from exc
    return {"payment_id": row.payment_id, "status": row.status, "reviewed_by": row.reviewed_by}


@app.post("/ops/reviews/{payment_id}/deny")
def deny_review(
    payment_id: str,
    req: ManualReviewRequest,
    x_api_key: str | None = Header(default=None),
    x_trace_id: str | None = Header(default=None),
):
    """Manually deny a review item and emit `risk.denied`."""

    enforce_api_key(x_api_key)
    trace_id = x_trace_id or str(uuid4())
    trace_id_ctx.set(trace_id)
    try:
        row = service.manual_decision(payment_id, "DENY", req.reviewed_by, trace_id)
    except ValueError as exc:
        raise _decision_error(exc) from exc
    return {"payment_id": row.payment_id, "status": row.status, "reviewed_by": row.reviewed_by}
