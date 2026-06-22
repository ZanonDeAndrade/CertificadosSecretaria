#!/bin/sh
# Container entrypoint for environments that run ONE process per container and
# inject the port via $PORT (Google Cloud Run, Railway, Fly, etc.).
#
# Pick the process with APP_TARGET:
#   admin     → certificados-admin/backEnd (FastAPI admin API)  [default]
#   consulta  → certificados-consulta      (public site)
#   migrate   → alembic upgrade head + seed the default template
#
# Docker Compose overrides `command:` per service, so this file is only used by
# platforms that run the image as-is (Cloud Run uses the image CMD).
set -eu

PORT="${PORT:-8000}"
WORKERS="${WEB_CONCURRENCY:-1}"
TARGET="${APP_TARGET:-admin}"

case "$TARGET" in
  admin)
    exec uvicorn main:app \
      --app-dir certificados-admin/backEnd \
      --host 0.0.0.0 --port "$PORT" --workers "$WORKERS" \
      --proxy-headers --forwarded-allow-ips="*"
    ;;
  consulta)
    exec uvicorn app:app \
      --app-dir certificados-consulta \
      --host 0.0.0.0 --port "$PORT" --workers "$WORKERS" \
      --proxy-headers --forwarded-allow-ips="*"
    ;;
  migrate)
    alembic upgrade head
    exec python certificados-admin/backEnd/seed_template.py
    ;;
  *)
    echo "APP_TARGET inválido: '$TARGET' (use admin|consulta|migrate)" >&2
    exit 64
    ;;
esac
