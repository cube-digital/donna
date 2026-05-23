#!/usr/bin/env bash
# Donna server entrypoint — migrate, collect static, exec uvicorn.
# Worker + beat run their own commands from docker-compose.yml.
#
# Set UVICORN_RELOAD=true to enable hot-reload (dev only — incompatible
# with --workers >1, so workers is forced to 1 in reload mode).
set -euo pipefail

python manage.py migrate --noinput
python manage.py collectstatic --noinput || true

uvicorn donna.asgi:application \
  --host 0.0.0.0 \
  --port 8000 \
  --proxy-headers \
  --reload
