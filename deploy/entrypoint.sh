#!/bin/sh
set -eu

if [ "${APP_ENV:-development}" = "production" ] && [ -z "${APP_TARGET:-}" ]; then
  echo "APP_TARGET é obrigatório em produção." >&2
  exit 64
fi

PORT="${PORT:-8000}"
WORKERS="${WEB_CONCURRENCY:-1}"
TARGET="${APP_TARGET:-admin}"
export FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-127.0.0.1}"

case "$TARGET" in
  admin)
    exec uvicorn certificados_backend.main:app \
      --host 0.0.0.0 --port "$PORT" --workers "$WORKERS" \
      --no-access-log \
      --proxy-headers --forwarded-allow-ips="$FORWARDED_ALLOW_IPS"
    ;;
  consulta)
    exec uvicorn certificados_consulta.app:app \
      --host 0.0.0.0 --port "$PORT" --workers "$WORKERS" \
      --no-access-log \
      --proxy-headers --forwarded-allow-ips="$FORWARDED_ALLOW_IPS"
    ;;
  worker)
    exec certificados-worker "$@"
    ;;
  migrate)
    alembic upgrade head
    exec python -m certificados_backend.seed_template
    ;;
  reconcile)
    exec certificados-reconcile "$@"
    ;;
  integrity)
    exec certificados-integrity "$@"
    ;;
  cleanup)
    exec certificados-maintenance cleanup-runtime "$@"
    ;;
  backup)
    : "${BACKUP_DESTINATION:?BACKUP_DESTINATION é obrigatório}"
    exec certificados-backup create \
      --destination "$BACKUP_DESTINATION" \
      --retention-days "${BACKUP_RETENTION_DAYS:-35}" "$@"
    ;;
  *)
    echo "APP_TARGET inválido: use admin|consulta|worker|migrate|reconcile|integrity|cleanup|backup" >&2
    exit 64
    ;;
esac
