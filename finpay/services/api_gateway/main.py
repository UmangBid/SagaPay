"""Public entrypoint for payment creation.

The gateway enforces API key auth, per-customer rate limiting, and a Redis
idempotency cache before forwarding requests to the orchestrator.
"""

import json
from time import perf_counter, time
from uuid import uuid4

import httpx
import redis
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from finpay.common.config import settings
from finpay.common.logging import configure_logging, logger, trace_id_ctx
from finpay.common.metrics import (
    http_request_duration_seconds,
    http_requests_total,
    metrics_response,
    payment_latency_seconds,
    payment_requests_total,
)
from finpay.common.startup import log_startup_config
from finpay.common.tracing import instrument_app, setup_tracing

configure_logging()
setup_tracing(settings.service_name)
log_startup_config(
    settings.service_name,
    [
        "SERVICE_NAME",
        "ORCHESTRATOR_URL",
        "REDIS_URL",
        "RATE_LIMIT_PER_MINUTE",
        "IDEMPOTENCY_TTL_SECONDS",
        "KAFKA_BOOTSTRAP_SERVERS",
    ],
)
app = FastAPI(title="SagaPay API Gateway")
instrument_app(app)
rdb = redis.Redis.from_url(settings.redis_url, decode_responses=True)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Record request count and latency for every HTTP call."""

    start = perf_counter()
    route = request.url.path
    method = request.method
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        route_obj = request.scope.get("route")
        if route_obj is not None and getattr(route_obj, "path", None):
            route = route_obj.path
        return response
    except Exception:
        raise
    finally:
        elapsed = max(0.0, perf_counter() - start)
        http_request_duration_seconds.labels(
            service=settings.service_name,
            route=route,
            method=method,
        ).observe(elapsed)
        http_requests_total.labels(
            service=settings.service_name,
            route=route,
            method=method,
            status_code=str(status_code),
        ).inc()


class PaymentRequest(BaseModel):
    """Payload accepted by `POST /payments`."""

    customer_id: str = Field(min_length=1)
    amount_cents: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    idempotency_key: str = Field(min_length=5)


def enforce_api_key(x_api_key: str | None) -> None:
    """Reject requests that do not provide the configured API key."""

    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="invalid API key")


def enforce_token_bucket(customer_id: str) -> None:
    # Redis token bucket (capacity = refill rate = limit per minute).
    key = f"tokenbucket:{customer_id}"
    now = time()
    capacity = float(settings.rate_limit_per_minute)
    refill_per_sec = capacity / 60.0

    values = rdb.hmget(key, "tokens", "updated_at")
    tokens = float(values[0]) if values[0] is not None else capacity
    updated_at = float(values[1]) if values[1] is not None else now
    elapsed = max(0.0, now - updated_at)
    tokens = min(capacity, tokens + elapsed * refill_per_sec)

    if tokens < 1.0:
        rdb.hset(key, mapping={"tokens": tokens, "updated_at": now})
        rdb.expire(key, 120)
        raise HTTPException(status_code=429, detail="rate limit exceeded")
    tokens -= 1.0
    rdb.hset(key, mapping={"tokens": tokens, "updated_at": now})
    rdb.expire(key, 120)


def _idempotency_cache_key(customer_id: str, idempotency_key: str) -> str:
    # Scope idempotency cache by tenant-like dimension to avoid cross-customer key collisions.
    return f"idempotency:payment:{customer_id}:{idempotency_key}"


@app.post("/payments")
async def create_payment(
    req: PaymentRequest,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_correlation_id: str | None = Header(default=None),
):
    """Create (or fetch existing) payment through orchestrator.

    Returns cached response when the same customer/idempotency key was already
    processed.
    """

    del request
    enforce_api_key(x_api_key)
    enforce_token_bucket(req.customer_id)
    trace_id = x_correlation_id or str(uuid4())
    trace_id_ctx.set(trace_id)

    cache_key = _idempotency_cache_key(req.customer_id, req.idempotency_key)
    try:
        cached = rdb.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception as exc:
        logger.warning("idempotency_cache_read_failed: %s", exc)

    payment_requests_total.labels(service=settings.service_name).inc()
    with payment_latency_seconds.labels(service=settings.service_name).time():
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{settings.orchestrator_url}/internal/payments",
                headers={"x-trace-id": trace_id},
                json=req.model_dump(),
            )
        if resp.status_code >= 400:
            logger.error("orchestrator rejected payment")
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        payload = resp.json()
        try:
            rdb.setex(cache_key, settings.idempotency_ttl_seconds, json.dumps(payload))
        except Exception as exc:
            logger.warning("idempotency_cache_write_failed: %s", exc)
        return payload


@app.get("/metrics")
def metrics():
    """Prometheus scrape endpoint."""

    return metrics_response()


@app.get("/health")
def health():
    """Container health probe endpoint."""

    return {"ok": True}
