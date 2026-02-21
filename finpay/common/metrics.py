"""Prometheus metric definitions shared across services."""

from prometheus_client import Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response


payment_requests_total = Counter("payment_requests_total", "Total payment requests", ["service"])
payment_success_total = Counter("payment_success_total", "Total successful payments", ["service"])
payment_failure_total = Counter("payment_failure_total", "Total failed payments", ["service"])
payment_latency_seconds = Histogram("payment_latency_seconds", "Payment latency seconds", ["service"])
kafka_consumer_lag = Counter("kafka_consumer_lag", "Kafka lag approximation", ["service", "topic"])
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["service", "route", "method", "status_code"],
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration seconds",
    ["service", "route", "method"],
)
payment_e2e_seconds = Histogram(
    "payment_e2e_seconds",
    "Payment end-to-end duration seconds from CREATED to terminal",
    ["service", "terminal_state"],
)
event_queue_delay_seconds = Histogram(
    "event_queue_delay_seconds",
    "Event queue delay seconds between occurred_at and consume time",
    ["service", "topic"],
)
outbox_pending_total = Gauge(
    "outbox_pending_total",
    "Current count of outbox events not yet sent",
    ["service"],
)
outbox_oldest_pending_age_seconds = Gauge(
    "outbox_oldest_pending_age_seconds",
    "Age in seconds of the oldest pending outbox event",
    ["service"],
)
retries_total = Counter("retries_total", "Retry count", ["service", "dependency"])
dlq_published_total = Counter(
    "dlq_published_total",
    "Total DLQ events published",
    ["service", "topic", "error_type"],
)
duplicate_events_skipped_total = Counter(
    "duplicate_events_skipped_total",
    "Duplicate inbox events skipped",
    ["service", "topic"],
)

# Backward-compatible names for existing dashboards/queries.
retry_count = retries_total


def metrics_response() -> Response:
    """Expose all registered Prometheus metrics in text format."""

    return Response(content=generate_latest(), media_type="text/plain")
