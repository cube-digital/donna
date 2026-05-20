#!/usr/bin/env bash
# Donna container entrypoint.
#
# Dispatches by role:
#   web      → migrate, collectstatic, integrations_bootstrap, then gunicorn
#   worker   → celery worker
#   beat     → celery beat (scheduler)
#   migrate  → run migrations and exit
#   bootstrap→ run integrations_bootstrap and exit
#   shell    → drop into a Django shell
#   *        → exec the rest of the args verbatim
set -euo pipefail

ROLE="${1:-web}"
shift || true

wait_for_postgres() {
  if [ -n "${DATABASE_URL:-}" ] && [[ "$DATABASE_URL" == postgres* ]]; then
    echo "[entrypoint] waiting for Postgres..."
    python - <<'PY'
import os
import time
import urllib.parse as up

import psycopg2  # noqa: F401 — only needed when DATABASE_URL is postgres

url = up.urlparse(os.environ["DATABASE_URL"])
for attempt in range(60):
    try:
        conn = __import__("psycopg2").connect(
            host=url.hostname,
            port=url.port or 5432,
            user=url.username,
            password=url.password,
            dbname=(url.path or "/").lstrip("/") or "postgres",
            connect_timeout=2,
        )
        conn.close()
        print(f"[entrypoint] Postgres ready (attempt {attempt + 1})")
        break
    except Exception as exc:
        print(f"[entrypoint] Postgres not ready ({exc!r}); retrying...")
        time.sleep(1)
else:
    raise SystemExit("[entrypoint] Postgres never came up")
PY
  fi
}

wait_for_redis() {
  if [ -n "${CELERY_BROKER_URL:-}" ] && [[ "$CELERY_BROKER_URL" == redis* ]]; then
    echo "[entrypoint] waiting for Redis..."
    python - <<'PY'
import os
import time

import redis  # type: ignore

url = os.environ["CELERY_BROKER_URL"]
for attempt in range(60):
    try:
        redis.from_url(url, socket_connect_timeout=2).ping()
        print(f"[entrypoint] Redis ready (attempt {attempt + 1})")
        break
    except Exception as exc:
        print(f"[entrypoint] Redis not ready ({exc!r}); retrying...")
        time.sleep(1)
else:
    raise SystemExit("[entrypoint] Redis never came up")
PY
  fi
}

case "$ROLE" in
  web)
    wait_for_postgres
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput || true
    python manage.py integrations_bootstrap || true
    exec gunicorn donna.wsgi:application \
        --bind 0.0.0.0:8000 \
        --workers "${GUNICORN_WORKERS:-3}" \
        --access-logfile - \
        --error-logfile -
    ;;
  worker)
    wait_for_postgres
    wait_for_redis
    exec celery -A donna worker \
        --loglevel="${CELERY_LOG_LEVEL:-info}" \
        --concurrency="${CELERY_CONCURRENCY:-4}"
    ;;
  beat)
    wait_for_postgres
    wait_for_redis
    exec celery -A donna beat --loglevel="${CELERY_LOG_LEVEL:-info}"
    ;;
  migrate)
    wait_for_postgres
    exec python manage.py migrate --noinput
    ;;
  bootstrap)
    wait_for_postgres
    exec python manage.py integrations_bootstrap
    ;;
  shell)
    exec python manage.py shell
    ;;
  *)
    exec "$ROLE" "$@"
    ;;
esac
