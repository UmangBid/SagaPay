# SagaPay

SagaPay is a distributed backend payment system. We built it to process a payment from API request to final settlement, while handling real reliability issues like retries, duplicate events, crashes, stale workers, and accounting integrity.

A single payment goes through risk evaluation, provider authorization, ledger posting, and terminal completion. Each step is observable, recoverable, and auditable.

## Table of Contents
- [What SagaPay Solves](#what-sagapay-solves)
- [Architecture Overview](#architecture-overview)
- [Tech Stack](#tech-stack)
- [Results and Outcomes](#results-and-outcomes)
- [Payment Flow (End-to-End)](#payment-flow-end-to-end)
- [Services and Responsibilities](#services-and-responsibilities)
- [State Machine](#state-machine)
- [Reliability Guarantees](#reliability-guarantees)
- [Observability](#observability)
- [Security](#security)
- [Performance and Load Testing](#performance-and-load-testing)
- [Installation and Local Setup](#installation-and-local-setup)
- [How to Run and Use the System](#how-to-run-and-use-the-system)
- [Validation and Test Checklist](#validation-and-test-checklist)
- [Troubleshooting](#troubleshooting)
- [Scaling Strategy](#scaling-strategy)
- [Design Tradeoffs](#design-tradeoffs)
- [Improvements Added Over Time](#improvements-added-over-time)
- [Contributing](#contributing)
- [Future Improvements](#future-improvements)
- [License](#license)

## What SagaPay Solves
We needed a payment system where these properties hold at the same time:
- Duplicate client retries do not create duplicate charges.
- Service failures do not corrupt payment lifecycle state.
- Provider timeouts are retried safely and handled deterministically.
- Ledger entries remain balanced and immutable.
- Risk review can pause and manually resume flow.
- Teams can explain behavior from logs, metrics, and traces.

## Architecture Overview
SagaPay is split into independent services with clear ownership boundaries. Services communicate primarily through Kafka events, with small HTTP surfaces where appropriate.

Core runtime infrastructure:
- Kafka + Zookeeper for event transport
- Postgres for service data stores
- Redis for rate limiting, idempotency fast-path, and risk velocity counters
- Prometheus + Grafana for metrics
- OpenTelemetry Collector for tracing export

## Tech Stack
### Language and runtime
- Python 3.11+
- FastAPI + Uvicorn

### Data and messaging
- PostgreSQL 16
- Redis 7
- Kafka (Confluent `cp-kafka`) + Zookeeper
- SQLAlchemy 2
- Alembic migrations

### Reliability and observability
- Transactional Outbox + Inbox dedupe
- Prometheus metrics (`prometheus-client`)
- OpenTelemetry tracing (`opentelemetry-*`)
- Structured JSON logging (`python-json-logger`)

### Testing and quality
- Pytest
- Ruff

## Results and Outcomes
This system is already producing measurable, production-style outcomes in local distributed runs.

### Functional output
- Payments successfully complete end-to-end to terminal states (`SETTLED`, `FAILED`, `REVERSED`) based on path conditions.
- Idempotent retries return the same `payment_id` instead of creating duplicate processing.
- High-risk requests correctly enter `RISK_REVIEW`, and ops approve/deny actions safely resume or terminate flow.
- Replayed or duplicated Kafka events are safely skipped through inbox dedupe.

### Measured metrics
- Load run (`1000` requests, concurrency `100`):
  - success: `1000`
  - errors: `0`
  - error rate: `0.00%`
  - p50: `1694.28 ms`
  - p95: `2690.06 ms`
  - p99: `2722.14 ms`
  - avg: `1729.30 ms`
- Global reconciliation proof:
```json
{"transactions_checked":1000,"imbalanced_count":0,"imbalanced_transactions":[]}
```

### What is working well
- We have deterministic saga state progression with strict transition validation.
- We have strong reliability controls (outbox/inbox, retry, DLQ, replay safety).
- We have accounting correctness guarantees (double-entry + append-only + reconciliation).
- We have operational visibility through logs, metrics, traces, and dashboards.

### Why we are proud of these results
- The system maintains correctness under retries, duplicates, and partial failures.
- It reaches zero-error API outcomes in tested load scenarios while preserving auditability.
- It demonstrates real distributed-system patterns that are usually missing in basic CRUD projects.

## Payment Flow (End-to-End)
1. Client calls `POST /payments` on API Gateway.
2. Gateway validates auth, applies rate limiting, checks Redis idempotency cache, then forwards to orchestrator.
3. Orchestrator creates payment in `CREATED`, writes timeline row, writes `payments.requested` to outbox.
4. Risk service consumes `payments.requested` and emits:
   - `risk.approved` for approve
   - `risk.denied` with decision payload for deny/review
   - also persists `risk_reviews` row when decision is `REVIEW`
5. Orchestrator consumes risk decision:
   - `APPROVED` path emits `provider.authorize.requested`
   - deny path transitions to `FAILED` or `RISK_REVIEW`
6. Provider adapter consumes authorize request:
   - success -> `payments.authorized`
   - decline -> `payments.failed`
   - timeout -> retries with backoff (1s, 2s, 4s), then `payments.failed` + DLQ if exhausted
7. Orchestrator consumes provider result:
   - authorized: `AUTHORIZED -> CAPTURED`, emits `payments.captured`
   - failed: transitions to `FAILED`; timeout terminal path compensates to `REVERSED` and emits `payments.reversed`
8. Ledger consumes `payments.captured`, posts balanced double-entry rows, emits `payments.settled`.
9. Orchestrator consumes `payments.settled`, transitions to terminal `SETTLED`.
10. Notification consumes terminal events and stores notification logs.

## Services and Responsibilities
### API Gateway (`finpay/services/api_gateway`)
- Owns public payment API.
- Enforces API key auth (`401` on missing/invalid key).
- Enforces Redis token-bucket rate limiting (`429` on exceed).
- Uses Redis idempotency fast-path cache.
- Forwards valid payment requests to orchestrator internal API.

### Orchestrator (`finpay/services/orchestrator`)
- Owns payment lifecycle source of truth.
- Tables: `payments`, `payment_attempts`, `payment_timeline`, `outbox_events`, `inbox_events`.
- Enforces state machine and optimistic concurrency (`state_version` CAS).
- Produces next-step events to drive saga.

### Risk (`finpay/services/risk`)
- Owns risk decisions and manual review queue.
- Tables: `risk_reviews`, `outbox_events`, `inbox_events`.
- Uses Redis for velocity counters and failure counters.
- Provides ops endpoints to approve/deny pending reviews safely.

### Provider Adapter (`finpay/services/provider_adapter`)
- Simulates external provider authorization behavior.
- Tables: `provider_attempts`, `outbox_events`, `inbox_events`.
- Implements bounded retries + backoff.
- Publishes DLQ events with classification metadata.

### Ledger (`finpay/services/ledger`)
- Owns accounting correctness and reconciliation.
- Tables: `accounts`, `ledger_entries`, `outbox_events`, `inbox_events`.
- Posts double-entry records and emits settlement event.
- DB trigger enforces append-only ledger entries.

### Notification (`finpay/services/notification`)
- Owns terminal notification logs.
- Tables: `notification_logs`, `inbox_events`.
- Consumes failed/settled outcomes and records delivery log.

## State Machine
State rules are explicit in `finpay/common/state_machine.py`.

States:
- `CREATED`
- `RISK_REVIEW`
- `APPROVED`
- `AUTHORIZED`
- `CAPTURED`
- `SETTLED` (terminal)
- `FAILED` (terminal in failure path)
- `REVERSED` (terminal compensation path)

Invalid transitions are rejected. Orchestrator transition writes are CAS-guarded:
- `WHERE payment_id=? AND status=? AND state_version=?`
- `SET status=?, state_version=state_version+1`

This prevents stale concurrent consumers from overwriting newer state.

## Reliability Guarantees
### Outbox pattern
Each service writes business change + outbox row in the same DB transaction. Publisher workers read outbox and publish to Kafka. This prevents DB/event divergence.

### Inbox pattern
Consumers persist `(event_id, consumed_by_service)` and skip duplicates. This makes at-least-once delivery safe.

### Idempotency
- Durable layer: unique orchestrator `idempotency_key` constraint.
- Fast layer: Redis cache with TTL (`IDEMPOTENCY_TTL_SECONDS`).
- Scope: key is customer-scoped (`idempotency:payment:{customer_id}:{idempotency_key}`) to avoid cross-customer collisions.

### Retries and DLQ
- Provider retries timeouts 3 times with backoff `1s/2s/4s`.
- DLQ classification:
  - `NON_RETRYABLE` for malformed/invalid payloads
  - `RETRY_EXHAUSTED` for retryable failures after max attempts

### Safe DLQ replay
`scripts/replay_dlq.py` replays the original failed event payload (same `event_id`) to original replay topic. Inbox dedupe ensures replay safety.

### Crash recovery
Outbox supports stale `PROCESSING` row reclaim. If a worker crashes after claim, rows are re-eligible after timeout.

### Timeline audit
`payment_timeline` stores `from_state`, `to_state`, `reason`, `event_id`, and timestamp for every transition.

### Ledger immutability + reconciliation
- DB trigger blocks `UPDATE`/`DELETE` on `ledger_entries`.
- Reconciliation endpoints:
  - `GET /reconciliation/{transaction_id}`
  - `GET /reconciliation`
- Current proof output:
```json
{"transactions_checked":1000,"imbalanced_count":0,"imbalanced_transactions":[]}
```

## Observability
We instrumented all services with logs, metrics, and tracing.

### Logs
Structured JSON logs include:
- `service_name`
- `trace_id`
- `event_id`
- `payment_id`

### Metrics
Key metrics include:
- `http_request_duration_seconds`, `http_requests_total`
- `payment_e2e_seconds`
- `event_queue_delay_seconds`
- `outbox_pending_total`, `outbox_oldest_pending_age_seconds`
- `retries_total`, `dlq_published_total`
- `duplicate_events_skipped_total`

### Tracing
OpenTelemetry is wired through OTLP exporter (`OTEL_EXPORTER_OTLP_ENDPOINT`) into collector. Correlation IDs propagate across services.

### Dashboards and reports
- Grafana dashboards:
  - `infra/grafana/dashboards/finpay-dashboard.json`
  - `infra/grafana/dashboards/finpay-executive-dashboard.json`
- Static report generator:
  - `scripts/generate_executive_report.py` -> `reports/executive_report.html`

## Security
- API key authentication at gateway and risk ops endpoints.
- Redis token-bucket rate limiting at gateway.
- Pydantic input validation.
- Secrets managed via env vars (`API_KEY`, `POSTGRES_PASSWORD`, Grafana admin creds, DSNs).

Expected security behavior:
- Missing/invalid API key -> `401`
- Rate limit exceeded -> `429`

## Performance and Load Testing
Primary load command:
```bash
python scripts/load_test.py --total 1000 --concurrency 100 --base-url http://localhost:8000 --api-key dev-secret
```

Recent measured run:
- total: `1000`
- success: `1000`
- errors: `0`
- error_rate: `0.00%`
- p50: `1694.28 ms`
- p95: `2690.06 ms`
- p99: `2722.14 ms`
- avg: `1729.30 ms`

We also observed earlier runs with higher latency under heavier queue pressure. This is expected in event-driven pipelines when queue delay and downstream processing contention increase.

## Installation and Local Setup
This section is the exact setup path for a fresh machine.

### Prerequisites
- Docker Desktop (running)
- Docker Compose v2
- Python 3.11+ (for local scripts)
- Git

### 1) Clone repository
```bash
git clone <your-repo-url>
cd SagaPay
```

### 2) Create env file
```bash
cp .env.example .env
```

Windows PowerShell:
```powershell
Copy-Item .env.example .env
```

### 3) Edit `.env`
At minimum set:
- `API_KEY`
- `POSTGRES_PASSWORD`
- `GRAFANA_ADMIN_USER`
- `GRAFANA_ADMIN_PASSWORD`

Keep service DSNs aligned with your `POSTGRES_PASSWORD`.

### 4) Install Python deps (optional but recommended for scripts/tests)
```bash
pip install -r requirements.txt
```

### 5) Start full stack
```bash
docker compose up --build -d
```

### 6) Verify containers
```bash
docker compose ps
```

## How to Run and Use the System
### Health checks
```bash
curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health
curl http://localhost:8004/health
curl http://localhost:8005/health
```

### Create one payment (Bash)
```bash
curl -X POST http://localhost:8000/payments \
  -H 'content-type: application/json' \
  -H 'x-api-key: dev-secret' \
  -H 'x-correlation-id: trace-001' \
  -d '{"customer_id":"cust-1","amount_cents":2500,"currency":"USD","idempotency_key":"idem-001"}'
```

### Create one payment (PowerShell)
```powershell
$headers = @{
  "x-api-key" = "dev-secret"
  "x-correlation-id" = "trace-001"
  "Content-Type" = "application/json"
}

$body = @{
  customer_id = "cust-1"
  amount_cents = 2500
  currency = "USD"
  idempotency_key = "idem-001"
} | ConvertTo-Json

$response = Invoke-RestMethod -Method POST -Uri "http://localhost:8000/payments" -Headers $headers -Body $body
$response
```

### Check payment status
```bash
curl http://localhost:8001/payments/<payment_id>
```

### Follow flow in logs
```bash
docker compose logs -f api-gateway orchestrator risk provider-adapter ledger notification
```

### Risk review flow
Create high-amount payment to trigger review:
```bash
curl -X POST http://localhost:8000/payments \
  -H 'content-type: application/json' \
  -H 'x-api-key: dev-secret' \
  -H 'x-correlation-id: trace-review-1' \
  -d '{"customer_id":"cust-risk","amount_cents":150000,"currency":"USD","idempotency_key":"idem-review-1"}'
```

List pending reviews:
```bash
curl -H 'x-api-key: dev-secret' http://localhost:8002/ops/reviews
```

Approve review:
```bash
curl -X POST http://localhost:8002/ops/reviews/<payment_id>/approve \
  -H 'x-api-key: dev-secret' \
  -H 'content-type: application/json' \
  -d '{"reviewed_by":"ops-user"}'
```

Deny review:
```bash
curl -X POST http://localhost:8002/ops/reviews/<payment_id>/deny \
  -H 'x-api-key: dev-secret' \
  -H 'content-type: application/json' \
  -d '{"reviewed_by":"ops-user"}'
```

### Observability access
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`
  - login uses `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` from `.env`

### Generate static executive report
```bash
python scripts/generate_executive_report.py --prom-url http://localhost:9090 --output reports/executive_report.html
```

## Validation and Test Checklist
Static checks:
```bash
ruff check finpay scripts tests
pytest -q
python -m compileall -q finpay scripts tests
```

Functional checks:
- Happy path reaches `SETTLED`
- Same idempotency key returns same `payment_id`
- High amount enters `RISK_REVIEW`
- Manual approve resumes to completion
- Manual deny reaches failure terminal path
- Missing auth returns `401`
- Burst traffic yields `429`
- Reconciliation returns zero imbalance

## Troubleshooting
### `alembic: command not found`
Run migrations through Python module path:
```bash
python -m alembic -c alembic/orchestrator/alembic.ini upgrade head
```
Or use provided wrappers:
```bash
./scripts/migrate_all.sh
```
PowerShell:
```powershell
.\scripts\migrate_all.ps1
```

### Cannot connect to Docker engine on Windows
Make sure Docker Desktop is running before any `docker compose` command.

### Postgres connection refused
Start infra first:
```bash
docker compose up -d postgres redis zookeeper kafka
```

### OTEL collector connection errors
Start collector and restart services:
```bash
docker compose up -d otel-collector
docker compose restart api-gateway orchestrator risk provider-adapter ledger notification
```

### PowerShell `curl` issues
PowerShell aliases `curl` to `Invoke-WebRequest`. Prefer `Invoke-RestMethod` examples above.

## Scaling Strategy
- Scale services horizontally with Kafka consumer groups.
- Partition Kafka topics by `payment_id` for per-payment ordering.
- Outbox claiming uses `FOR UPDATE SKIP LOCKED` for multi-instance safety.
- Keep DB ownership per service and index hot paths (`idempotency_key`, status, outbox status+created_at, timeline/payment lookup keys).

## Design Tradeoffs
- We use orchestrated saga (not choreography) for clearer transition control.
- We use separate service databases (same Postgres instance locally) to preserve ownership boundaries.
- We use at-least-once messaging with inbox dedupe instead of exactly-once Kafka transactions for operational simplicity and explicit idempotency control.

## Improvements Added Over Time
- Added `state_version` CAS transitions to prevent stale updates.
- Added `payment_timeline` audit history.
- Added Redis idempotency fast-path with TTL and customer-scoped keys.
- Added multi-instance-safe outbox claiming + stale claim recovery.
- Added inbox dedupe across consumers.
- Added retry/DLQ classification and replay tooling.
- Added compensation to `REVERSED` for terminal timeout path.
- Added ledger immutability trigger and reconciliation endpoints.
- Added risk review queue and manual approve/deny flow.
- Added expanded observability metrics and executive dashboard/report.

## Contributing
We welcome contributions.

1. Fork the repository.
2. Create a branch (`git checkout -b feature/your-change`).
3. Make changes and keep tests/checks passing.
4. Push branch and open a pull request.

Recommended before PR:
```bash
ruff check finpay scripts tests
pytest -q
```

## Future Improvements
- Add stronger automated integration and chaos tests (consumer restarts, broker disruption, partial DB outages).
- Add partitioning strategy and topic-level tuning for higher throughput under sustained load.
- Add richer ops tooling for review queue triage and controlled bulk actions.
- Add historical data retention/archival strategy for timeline, attempts, and notification logs.
- Add auth hardening options (JWT/OAuth2) for environments beyond internal API-key usage.
- Add CI/CD pipeline with migration checks, contract tests, and release gates.
- Add formal SLO/SLA alerting rules tied to p95 latency, DLQ rates, and outbox backlog age.

## License
This repository currently does not include a license file.
If we plan to open-source this project, we should add a `LICENSE` file explicitly.
