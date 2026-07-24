#!/usr/bin/env bash
# Container entrypoint: wait for Postgres, optionally run migrations, then exec CMD.
set -euo pipefail

echo "[entrypoint] waiting for database..."
python - <<'PY'
import time
import sys
from sqlalchemy import create_engine, text
from app.core.config import settings

url = settings.database_url
for attempt in range(60):
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("[entrypoint] database is ready")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        print(f"[entrypoint] db not ready ({attempt+1}/60): {exc.__class__.__name__}")
        time.sleep(2)
print("[entrypoint] database did not become ready in time", file=sys.stderr)
sys.exit(1)
PY

# Only the process that sets RUN_MIGRATIONS=1 applies migrations (the api service),
# so worker/beat never race on schema changes.
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "[entrypoint] running alembic migrations..."
  alembic upgrade head
fi

echo "[entrypoint] starting: $*"
exec "$@"
