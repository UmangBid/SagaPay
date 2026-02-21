#!/usr/bin/env bash
set -euo pipefail

# Convenience wrapper to migrate every service database in a fixed order.
ORCH_DSN="${ORCHESTRATOR_POSTGRES_DSN:-postgresql+psycopg2://finpay:finpay@localhost:5432/finpay_orchestrator}"
RISK_DSN="${RISK_POSTGRES_DSN:-postgresql+psycopg2://finpay:finpay@localhost:5432/finpay_risk}"
PROVIDER_DSN="${PROVIDER_POSTGRES_DSN:-postgresql+psycopg2://finpay:finpay@localhost:5432/finpay_provider}"
LEDGER_DSN="${LEDGER_POSTGRES_DSN:-postgresql+psycopg2://finpay:finpay@localhost:5432/finpay_ledger}"
NOTIFICATION_DSN="${NOTIFICATION_POSTGRES_DSN:-postgresql+psycopg2://finpay:finpay@localhost:5432/finpay_notification}"

scripts/migrate_service.sh orchestrator "$ORCH_DSN"
scripts/migrate_service.sh risk "$RISK_DSN"
scripts/migrate_service.sh provider_adapter "$PROVIDER_DSN"
scripts/migrate_service.sh ledger "$LEDGER_DSN"
scripts/migrate_service.sh notification "$NOTIFICATION_DSN"

echo "All migrations applied successfully."
