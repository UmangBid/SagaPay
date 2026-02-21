"""Structured JSON logging with request/event context fields."""

import logging
import sys
from contextvars import ContextVar

from pythonjsonlogger.json import JsonFormatter

from finpay.common.config import settings


trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="")
event_id_ctx: ContextVar[str] = ContextVar("event_id", default="")
payment_id_ctx: ContextVar[str] = ContextVar("payment_id", default="")


class ContextFilter(logging.Filter):
    """Inject service and correlation identifiers into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.service_name = settings.service_name
        record.trace_id = trace_id_ctx.get()
        record.event_id = event_id_ctx.get()
        record.payment_id = payment_id_ctx.get()
        return True


def configure_logging() -> None:
    """Configure root logger once per service process."""

    handler = logging.StreamHandler(sys.stdout)
    context_filter = ContextFilter()
    handler.addFilter(context_filter)
    formatter = JsonFormatter(
        "%(asctime)s %(levelname)s %(service_name)s %(trace_id)s %(event_id)s %(payment_id)s %(message)s"
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)
    root.addFilter(context_filter)


logger = logging.getLogger("finpay")
