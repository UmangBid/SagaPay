#!/usr/bin/env bash
set -euo pipefail

# Apply Alembic migrations for one service DB using explicit DSN.
if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <service> <postgres_dsn>"
  echo "Services: orchestrator | risk | provider_adapter | ledger | notification"
  exit 1
fi

service="$1"
postgres_dsn="$2"

python_bin="${PYTHON_BIN:-}"
if [[ -z "$python_bin" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    python_bin="python3"
  elif command -v python >/dev/null 2>&1; then
    python_bin="python"
  else
    echo "Python not found. Set PYTHON_BIN to your interpreter path."
    exit 1
  fi
fi

case "$service" in
  orchestrator|risk|provider_adapter|ledger|notification) ;;
  *)
    echo "Unsupported service: $service"
    exit 1
    ;;
esac

POSTGRES_DSN="$postgres_dsn" "$python_bin" -m alembic -c "alembic/$service/alembic.ini" upgrade head
