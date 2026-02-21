#!/usr/bin/env bash
set -euo pipefail

# Starts one service container process:
# 1) run that service's Alembic migrations with retries
# 2) launch uvicorn app
if [[ $# -ne 3 ]]; then
  echo "Usage: $0 <service> <app_path> <port>"
  exit 1
fi

service="$1"
app_path="$2"
port="$3"

migration_service="$service"
if [[ "$service" == "provider-adapter" ]]; then
  migration_service="provider_adapter"
fi

if [[ -f "alembic/$migration_service/alembic.ini" ]]; then
  echo "[start_service] running migrations for $migration_service"
  max_attempts=40
  for attempt in $(seq 1 "$max_attempts"); do
    if python -m alembic -c "alembic/$migration_service/alembic.ini" upgrade head; then
      break
    fi
    if [[ "$attempt" -eq "$max_attempts" ]]; then
      echo "[start_service] migration failed after $max_attempts attempts for $migration_service"
      exit 1
    fi
    echo "[start_service] migration retry $attempt/$max_attempts for $migration_service"
    sleep 2
  done
fi

echo "[start_service] starting $service on :$port"
exec uvicorn "$app_path" --host 0.0.0.0 --port "$port"
