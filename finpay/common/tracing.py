"""OpenTelemetry setup helpers used by each FastAPI service."""

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

from finpay.common.config import settings


def setup_tracing(service_name: str) -> None:
    """Create and register a tracer provider with OTLP HTTP exporter."""

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def instrument_app(app: FastAPI) -> None:
    """Attach FastAPI auto-instrumentation for request spans."""

    FastAPIInstrumentor.instrument_app(app)
