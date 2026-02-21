"""Central environment-driven settings shared by all services.

Each service process loads this once at startup. Service-specific behavior is
controlled by environment variables (see `.env.example`).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class CommonSettings(BaseSettings):
    """Typed view of runtime configuration from environment variables."""

    service_name: str = "unknown-service"
    log_level: str = "INFO"
    kafka_bootstrap_servers: str = "kafka:9092"
    redis_url: str = "redis://redis:6379/0"
    postgres_dsn: str
    api_key: str
    orchestrator_url: str = "http://orchestrator:8001"
    provider_url: str = "http://provider-adapter:8003"
    otel_exporter_otlp_endpoint: str = "http://otel-collector:4318/v1/traces"
    risk_velocity_per_hour: int = 20
    rate_limit_per_minute: int = 30
    idempotency_ttl_seconds: int = 86400
    risk_review_amount_cents: int = 100_000
    risk_deny_frequency_threshold: int = 50
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = CommonSettings()
