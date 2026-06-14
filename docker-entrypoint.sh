#!/usr/bin/env bash
set -e

# 1. First-run config: app reads backend/config.json (gitignored). Keep the live
#    copy inside the persisted data volume and symlink it, so edits survive rebuilds.
mkdir -p /app/backend/data
if [ ! -f /app/backend/data/config.json ]; then
  echo "[entrypoint] seeding data/config.json from config.example.json"
  cp /app/backend/config.example.json /app/backend/data/config.json
fi
ln -sf /app/backend/data/config.json /app/backend/config.json

# 2. Wait for Postgres. Startup hangs on Alembic if the DB is not ready, so block first.
echo "[entrypoint] waiting for database..."
python - <<'PY'
import os, time, sys
from sqlalchemy import create_engine
url = os.environ["DATABASE_URL"]
for i in range(60):
    try:
        create_engine(url).connect().close()
        print("[entrypoint] database is up")
        sys.exit(0)
    except Exception as e:
        print(f"[entrypoint]   db not ready ({i+1}/60): {e.__class__.__name__}")
        time.sleep(2)
print("[entrypoint] database never came up", file=sys.stderr)
sys.exit(1)
PY

# 3. Alembic migrations run automatically inside the app's lifespan (init_db()).
echo "[entrypoint] starting: $*"
exec "$@"
