"""Notification service lifecycle and lightweight read endpoints."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from finpay.common.db import SessionLocal
from finpay.common.config import settings
from finpay.common.logging import configure_logging
from finpay.common.tracing import instrument_app, setup_tracing
from finpay.common.metrics import metrics_response
from finpay.common.startup import log_startup_config
from finpay.services.notification.service import NotificationService

configure_logging()
setup_tracing(settings.service_name)
log_startup_config(
    settings.service_name,
    ["SERVICE_NAME", "POSTGRES_DSN", "KAFKA_BOOTSTRAP_SERVERS", "REDIS_URL"],
)
service = NotificationService(SessionLocal)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Run consumer loop with FastAPI application lifecycle."""

    consumer_task = asyncio.create_task(service.start_consumers())
    yield
    consumer_task.cancel()


app = FastAPI(title="SagaPay Notification Service", lifespan=lifespan)
instrument_app(app)


@app.get("/health")
def health():
    """Container health probe endpoint."""

    return {"ok": True}


@app.get("/metrics")
def metrics():
    """Prometheus scrape endpoint."""

    return metrics_response()
