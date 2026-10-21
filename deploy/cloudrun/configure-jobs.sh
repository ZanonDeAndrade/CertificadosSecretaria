#!/usr/bin/env bash
# Creates/updates bounded Cloud Run Jobs and their Cloud Scheduler triggers.
# Run only after explicit deployment approval; this repository never invokes it.
set -euo pipefail

export MSYS2_ARG_CONV_EXCL="--set-env-vars;--set-secrets;--args"

PROJECT="${PROJECT:?Defina PROJECT}"
REGION="${REGION:?Defina REGION}"
APP_IMAGE="${APP_IMAGE:?Defina APP_IMAGE pelo digest aprovado}"
OPS_IMAGE="${OPS_IMAGE:?Defina OPS_IMAGE pelo digest aprovado}"
WORKER_SERVICE_ACCOUNT="${WORKER_SERVICE_ACCOUNT:?Defina WORKER_SERVICE_ACCOUNT}"
ADMIN_SERVICE_ACCOUNT="${ADMIN_SERVICE_ACCOUNT:?Defina ADMIN_SERVICE_ACCOUNT}"
OPERATIONS_SERVICE_ACCOUNT="${OPERATIONS_SERVICE_ACCOUNT:?Defina OPERATIONS_SERVICE_ACCOUNT}"
BACKUP_SERVICE_ACCOUNT="${BACKUP_SERVICE_ACCOUNT:?Defina BACKUP_SERVICE_ACCOUNT separado}"
SCHEDULER_SERVICE_ACCOUNT="${SCHEDULER_SERVICE_ACCOUNT:?Defina SCHEDULER_SERVICE_ACCOUNT}"

DRIVE_FOLDER_ID="${DRIVE_FOLDER_ID:-}"
PUBLIC_VALIDATION_BASE_URL="${PUBLIC_VALIDATION_BASE_URL:?Defina PUBLIC_VALIDATION_BASE_URL}"
FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:?Defina FORWARDED_ALLOW_IPS}"
TRUSTED_PROXY_CIDRS="${TRUSTED_PROXY_CIDRS:?Defina TRUSTED_PROXY_CIDRS}"
DOCUMENT_HASH_ACTIVE_KEY_ID="${DOCUMENT_HASH_ACTIVE_KEY_ID:?Defina DOCUMENT_HASH_ACTIVE_KEY_ID}"
BATCH_PAYLOAD_ACTIVE_KEY_ID="${BATCH_PAYLOAD_ACTIVE_KEY_ID:?Defina BATCH_PAYLOAD_ACTIVE_KEY_ID}"
BACKUP_DESTINATION="${BACKUP_DESTINATION:?Defina bucket/prefixo gs:// separado}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-35}"

DATABASE_SECRET="${DATABASE_SECRET:-certificados-database-url}"
POSTGRES_CA_SECRET="${POSTGRES_CA_SECRET:-certificados-postgres-ca}"
GOOGLE_ADMIN_TOKEN_SECRET="${GOOGLE_ADMIN_TOKEN_SECRET:-certificados-google-admin-oauth-token}"
GOOGLE_PUBLIC_TOKEN_SECRET="${GOOGLE_PUBLIC_TOKEN_SECRET:-certificados-google-public-readonly-token}"
DOCUMENT_KEYRING_SECRET="${DOCUMENT_KEYRING_SECRET:-certificados-document-hash-keyring}"
BATCH_KEYRING_SECRET="${BATCH_KEYRING_SECRET:-certificados-batch-payload-keyring}"
BACKUP_ENCRYPTION_SECRET="${BACKUP_ENCRYPTION_SECRET:-certificados-backup-encryption-key}"

WORKER_JOB="${WORKER_JOB:-certificados-emission-worker}"
RECONCILE_JOB="${RECONCILE_JOB:-certificados-reconcile}"
INTEGRITY_JOB="${INTEGRITY_JOB:-certificados-integrity}"
CLEANUP_JOB="${CLEANUP_JOB:-certificados-cleanup}"
BACKUP_JOB="${BACKUP_JOB:-certificados-backup}"

case "$APP_IMAGE,$OPS_IMAGE" in
  *@sha256:????????????????????????????????????????????????????????????????,*@sha256:????????????????????????????????????????????????????????????????) ;;
  *) echo "APP_IMAGE e OPS_IMAGE devem usar digest sha256." >&2; exit 64 ;;
esac
case "$BACKUP_DESTINATION" in gs://*/*) ;; *) echo "BACKUP_DESTINATION deve ser gs://bucket/prefixo." >&2; exit 64 ;; esac

COMMON_ENV="APP_ENV=production,DATABASE_URL_FILE=/secrets/database/url,DOCUMENT_HASH_KEYRING_FILE=/secrets/document/keyring.json,DOCUMENT_HASH_ACTIVE_KEY_ID=${DOCUMENT_HASH_ACTIVE_KEY_ID},STORAGE_PROVIDER=google_drive,GOOGLE_DRIVE_AUTH_MODE=oauth_user,GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID=${DRIVE_FOLDER_ID},PUBLIC_VALIDATION_BASE_URL=${PUBLIC_VALIDATION_BASE_URL},FORWARDED_ALLOW_IPS=${FORWARDED_ALLOW_IPS},TRUSTED_PROXY_CIDRS=${TRUSTED_PROXY_CIDRS},DB_POOL_SIZE=2,DB_MAX_OVERFLOW=1,DB_POOL_TIMEOUT=30,DB_POOL_RECYCLE=300"
COMMON_SECRETS="/secrets/database/url=${DATABASE_SECRET}:latest,/secrets/database/ca.pem=${POSTGRES_CA_SECRET}:latest,/secrets/document/keyring.json=${DOCUMENT_KEYRING_SECRET}:latest"

gcloud run jobs deploy "$WORKER_JOB" \
  --project "$PROJECT" --region "$REGION" --image "$APP_IMAGE" \
  --service-account "$WORKER_SERVICE_ACCOUNT" \
  --cpu 1 --memory 1Gi --tasks 1 --parallelism 1 --max-retries 1 --task-timeout 55m \
  --set-env-vars="APP_TARGET=worker,BATCH_WORKER_MODE=external,BATCH_PAYLOAD_KEYS_FILE=/secrets/batch/keyring.json,BATCH_PAYLOAD_ACTIVE_KEY_ID=${BATCH_PAYLOAD_ACTIVE_KEY_ID},GOOGLE_DRIVE_ACCESS_MODE=read_write,GOOGLE_ADMIN_OAUTH_TOKEN_FILE=/secrets/google/admin-token.json,${COMMON_ENV}" \
  --set-secrets="/secrets/batch/keyring.json=${BATCH_KEYRING_SECRET}:latest,/secrets/google/admin-token.json=${GOOGLE_ADMIN_TOKEN_SECRET}:latest,${COMMON_SECRETS}" \
  --args=--max-jobs,200 --quiet

gcloud run jobs deploy "$RECONCILE_JOB" \
  --project "$PROJECT" --region "$REGION" --image "$APP_IMAGE" \
  --service-account "$OPERATIONS_SERVICE_ACCOUNT" \
  --cpu 1 --memory 512Mi --tasks 1 --parallelism 1 --max-retries 1 --task-timeout 20m \
  --set-env-vars="APP_TARGET=reconcile,GOOGLE_DRIVE_ACCESS_MODE=read_write,GOOGLE_ADMIN_OAUTH_TOKEN_FILE=/secrets/google/admin-token.json,${COMMON_ENV}" \
  --set-secrets="/secrets/google/admin-token.json=${GOOGLE_ADMIN_TOKEN_SECRET}:latest,${COMMON_SECRETS}" \
  --args=--max-rows,10000 --quiet

gcloud run jobs deploy "$INTEGRITY_JOB" \
  --project "$PROJECT" --region "$REGION" --image "$APP_IMAGE" \
  --service-account "$OPERATIONS_SERVICE_ACCOUNT" \
  --cpu 1 --memory 512Mi --tasks 1 --parallelism 1 --max-retries 1 --task-timeout 30m \
  --set-env-vars="APP_TARGET=integrity,GOOGLE_DRIVE_ACCESS_MODE=read_only,GOOGLE_PUBLIC_OAUTH_TOKEN_FILE=/secrets/google/public-token.json,${COMMON_ENV}" \
  --set-secrets="/secrets/google/public-token.json=${GOOGLE_PUBLIC_TOKEN_SECRET}:latest,${COMMON_SECRETS}" \
  --args=--limit,10000 --quiet

gcloud run jobs deploy "$CLEANUP_JOB" \
  --project "$PROJECT" --region "$REGION" --image "$APP_IMAGE" \
  --service-account "$OPERATIONS_SERVICE_ACCOUNT" \
  --cpu 1 --memory 512Mi --tasks 1 --parallelism 1 --max-retries 1 --task-timeout 10m \
  --set-env-vars="APP_TARGET=cleanup,${COMMON_ENV}" \
  --set-secrets="$COMMON_SECRETS" --quiet

# The backup job uses workload identity for the separate bucket. Its Drive
# token is read-only and independent from the writer token used by issuance.
gcloud run jobs deploy "$BACKUP_JOB" \
  --project "$PROJECT" --region "$REGION" --image "$OPS_IMAGE" \
  --service-account "$BACKUP_SERVICE_ACCOUNT" \
  --cpu 1 --memory 1Gi --tasks 1 --parallelism 1 --max-retries 1 --task-timeout 60m \
  --set-env-vars="APP_TARGET=backup,BACKUP_DESTINATION=${BACKUP_DESTINATION},BACKUP_RETENTION_DAYS=${BACKUP_RETENTION_DAYS},BACKUP_ENCRYPTION_KEY_FILE=/secrets/backup/key,GOOGLE_DRIVE_ACCESS_MODE=read_only,GOOGLE_PUBLIC_OAUTH_TOKEN_FILE=/secrets/google/public-token.json,${COMMON_ENV}" \
  --set-secrets="/secrets/backup/key=${BACKUP_ENCRYPTION_SECRET}:latest,/secrets/google/public-token.json=${GOOGLE_PUBLIC_TOKEN_SECRET}:latest,${COMMON_SECRETS}" \
  --quiet

schedule_job() {
  local scheduler_name="$1" cron="$2" run_job="$3" deadline="$4"
  local uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${run_job}:run"
  if gcloud scheduler jobs describe "$scheduler_name" --project "$PROJECT" --location "$REGION" >/dev/null 2>&1; then
    gcloud scheduler jobs update http "$scheduler_name" \
      --project "$PROJECT" --location "$REGION" --schedule "$cron" --time-zone UTC \
      --uri "$uri" --http-method POST --message-body '{}' \
      --oauth-service-account-email "$SCHEDULER_SERVICE_ACCOUNT" \
      --oauth-token-scope https://www.googleapis.com/auth/cloud-platform \
      --attempt-deadline "$deadline" --max-retry-attempts 3 \
      --min-backoff 30s --max-backoff 300s --quiet
  else
    gcloud scheduler jobs create http "$scheduler_name" \
      --project "$PROJECT" --location "$REGION" --schedule "$cron" --time-zone UTC \
      --uri "$uri" --http-method POST --message-body '{}' \
      --oauth-service-account-email "$SCHEDULER_SERVICE_ACCOUNT" \
      --oauth-token-scope https://www.googleapis.com/auth/cloud-platform \
      --attempt-deadline "$deadline" --max-retry-attempts 3 \
      --min-backoff 30s --max-backoff 300s --quiet
  fi
}

# Least privilege: the API only starts the predefined job (no overrides).
gcloud run jobs add-iam-policy-binding "$WORKER_JOB" \
  --project "$PROJECT" --region "$REGION" \
  --member "serviceAccount:${ADMIN_SERVICE_ACCOUNT}" --role roles/run.invoker --quiet
for scheduled_job in "$WORKER_JOB" "$RECONCILE_JOB" "$INTEGRITY_JOB" "$CLEANUP_JOB" "$BACKUP_JOB"; do
  gcloud run jobs add-iam-policy-binding "$scheduled_job" \
    --project "$PROJECT" --region "$REGION" \
    --member "serviceAccount:${SCHEDULER_SERVICE_ACCOUNT}" --role roles/run.invoker --quiet
done

# The API dispatches immediately. This low-frequency execution is only a
# recovery net; together with the other schedules it remains near the Jobs
# free tier despite Cloud Run's one-minute minimum per execution.
schedule_job "${WORKER_JOB}-fallback-15m" "*/15 * * * *" "$WORKER_JOB" 180s
schedule_job "${RECONCILE_JOB}-hourly" "7 * * * *" "$RECONCILE_JOB" 180s
schedule_job "${INTEGRITY_JOB}-daily" "15 2 * * *" "$INTEGRITY_JOB" 180s
schedule_job "${CLEANUP_JOB}-daily" "45 3 * * *" "$CLEANUP_JOB" 180s
schedule_job "${BACKUP_JOB}-daily" "15 1 * * *" "$BACKUP_JOB" 180s

echo '{"status":"configured","component":"cloud-run-jobs-and-schedules"}'
