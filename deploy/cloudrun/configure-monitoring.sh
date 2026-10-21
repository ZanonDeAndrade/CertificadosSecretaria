#!/usr/bin/env bash
# Idempotently provisions executable log metrics and alert policies.
# It does not create notification channels; pass existing resource names.
set -euo pipefail

PROJECT="${PROJECT:?Defina PROJECT}"
NOTIFICATION_CHANNELS="${NOTIFICATION_CHANNELS:?Informe resources separados por virgula}"
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
MONITORING_DIR="$ROOT/deploy/monitoring"

upsert_metric() {
  local name="$1" file="$2"
  if gcloud logging metrics describe "$name" --project "$PROJECT" >/dev/null 2>&1; then
    gcloud logging metrics update "$name" --project "$PROJECT" --config-from-file "$file" --quiet
  else
    gcloud logging metrics create "$name" --project "$PROJECT" --config-from-file "$file" --quiet
  fi
}

upsert_policy() {
  local display_name="$1" file="$2" existing
  existing="$(gcloud monitoring policies list --project "$PROJECT" \
    --filter="displayName=\"${display_name}\"" --format='value(name)' --limit=1)"
  if [[ -n "$existing" ]]; then
    gcloud monitoring policies update "$existing" --project "$PROJECT" \
      --policy-from-file "$file" --set-notification-channels "$NOTIFICATION_CHANNELS" --quiet
  else
    gcloud monitoring policies create --project "$PROJECT" \
      --policy-from-file "$file" --notification-channels "$NOTIFICATION_CHANNELS" --quiet
  fi
}

upsert_metric certificados_operation_failures "$MONITORING_DIR/log-metric-failures.json"
upsert_metric certificados_integrity_incidents "$MONITORING_DIR/log-metric-integrity.json"
upsert_metric certificados_backup_success "$MONITORING_DIR/log-metric-backup-success.json"
upsert_metric certificados_request_duration_ms "$MONITORING_DIR/log-metric-request-latency.json"
upsert_metric certificados_emission_job_duration_ms "$MONITORING_DIR/log-metric-emission-latency.json"

upsert_policy "Certificados | falha operacional" "$MONITORING_DIR/alert-operation-failures.json"
upsert_policy "Certificados | incidente de integridade" "$MONITORING_DIR/alert-integrity.json"
upsert_policy "Certificados | latencia HTTP p95" "$MONITORING_DIR/alert-request-latency.json"
upsert_policy "Certificados | emissao lenta p95" "$MONITORING_DIR/alert-emission-latency.json"
upsert_policy "Certificados | backup ausente" "$MONITORING_DIR/alert-backup-absence.json"

echo '{"status":"configured","component":"metrics-and-alerts"}'
