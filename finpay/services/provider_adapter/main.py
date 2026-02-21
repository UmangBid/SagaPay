"""Provider adapter API + worker lifecycle.

Simulates an external provider and translates its outcomes to internal events.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from finpay.common.db import SessionLocal
from finpay.common.config import settings
from finpay.common.logging import configure_logging
from finpay.common.tracing import instrument_app, setup_tracing
from finpay.common.metrics import metrics_response
from finpay.common.startup import log_startup_config
from finpay.services.provider_adapter.service import ProviderAdapterService

configure_logging()
setup_tracing(settings.service_name)
log_startup_config(
    settings.service_name,
    ["SERVICE_NAME", "POSTGRES_DSN", "KAFKA_BOOTSTRAP_SERVERS", "REDIS_URL"],
)
service = ProviderAdapterService(SessionLocal)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Run outbox publisher + authorize consumer with app lifecycle."""

    publisher_task = asyncio.create_task(service.outbox_publisher())
    consumer_task = asyncio.create_task(service.start_consumers())
    yield
    publisher_task.cancel()
    consumer_task.cancel()
    await service.kafka.close()


app = FastAPI(title="SagaPay Provider Adapter", lifespan=lifespan)
instrument_app(app)


@app.get("/health")
def health():
    """Container health probe endpoint."""

    return {"ok": True}


@app.get("/metrics")
def metrics():
    """Prometheus scrape endpoint."""

    return metrics_response()
