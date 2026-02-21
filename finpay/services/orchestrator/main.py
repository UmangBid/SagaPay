"""HTTP surface for orchestrator-owned payment records and lifecycle workers."""

import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException

from finpay.common.config import settings
from finpay.common.db import SessionLocal
from finpay.common.logging import configure_logging, trace_id_ctx
from finpay.common.metrics import metrics_response, payment_latency_seconds, payment_requests_total
from finpay.common.startup import log_startup_config
from finpay.common.tracing import instrument_app, setup_tracing
from finpay.services.orchestrator.models import Payment
from finpay.services.orchestrator.schemas import PaymentCreateRequest, PaymentResponse
from finpay.services.orchestrator.service import OrchestratorService

configure_logging()
setup_tracing(settings.service_name)
log_startup_config(
    settings.service_name,
    ["SERVICE_NAME", "POSTGRES_DSN", "KAFKA_BOOTSTRAP_SERVERS", "REDIS_URL"],
)
service = OrchestratorService(SessionLocal)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Run background outbox publisher + Kafka consumers with app lifecycle."""

    publisher_task = asyncio.create_task(service.outbox_publisher())
    consumer_task = asyncio.create_task(service.start_consumers())
    yield
    publisher_task.cancel()
    consumer_task.cancel()
    await service.kafka.close()


app = FastAPI(title="SagaPay Orchestrator", lifespan=lifespan)
instrument_app(app)


@app.post("/internal/payments", response_model=PaymentResponse)
async def create_payment(req: PaymentCreateRequest, x_trace_id: str | None = Header(default=None)):
    """Create a payment row in `CREATED` and emit `payments.requested`."""

    trace_id = x_trace_id or str(uuid4())
    trace_id_ctx.set(trace_id)
    payment_requests_total.labels(service=settings.service_name).inc()
    with payment_latency_seconds.labels(service=settings.service_name).time():
        try:
            payment = service.create_payment(req, trace_id)
            return PaymentResponse(payment_id=payment.payment_id, status=payment.status)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/payments/{payment_id}", response_model=PaymentResponse)
def get_payment(payment_id: str):
    """Fetch current status for one payment."""

    with SessionLocal() as db:
        payment = db.get(Payment, payment_id)
        if not payment:
            raise HTTPException(status_code=404, detail="payment not found")
        return PaymentResponse(payment_id=payment.payment_id, status=payment.status)


@app.get("/metrics")
def metrics():
    """Prometheus scrape endpoint."""

    return metrics_response()


@app.get("/health")
def health():
    """Container health probe endpoint."""

    return {"ok": True}
