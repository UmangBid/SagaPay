"""Startup-time helpers for safe config logging."""

import os

from finpay.common.logging import logger


def _safe_env(name: str) -> str:
    """Return env value with simple redaction for secret-like variable names."""

    value = os.getenv(name)
    if value is None:
        return "<unset>"
    if any(secret in name for secret in ["KEY", "SECRET", "PASSWORD", "TOKEN"]):
        return "<redacted>"
    return value


def log_startup_config(service_name: str, keys: list[str]) -> None:
    """Log selected startup config keys for quick troubleshooting."""

    config = {"service": service_name}
    for key in keys:
        config[key] = _safe_env(key)
    logger.info("startup_config=%s", config)
