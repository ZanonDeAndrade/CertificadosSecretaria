#!/usr/bin/env bash
# Cloud Run release helper. It deploys only pre-built, scanned image digests;
# building and scanning belong to CI. Nothing in this file runs automatically.
set -euo pipefail

export MSYS2_ARG_CONV_EXCL="--set-env-vars;--set-secrets"

PROJECT="${PROJECT:?Defina PROJECT explicitamente}"
REGION="${REGION:?Defina REGION explicitamente}"
ADMIN_SERVICE_ACCOUNT="${ADMIN_SERVICE_ACCOUNT:?Defina ADMIN_SERVICE_ACCOUNT}"
PUBLIC_SERVICE_ACCOUNT="${PUBLIC_SERVICE_ACCOUNT:?Defina PUBLIC_SERVICE_ACCOUNT}"
WEB_SERVICE_ACCOUNT="${WEB_SERVICE_ACCOUNT:?Defina WEB_SERVICE_ACCOUNT}"
OPERATIONS_SERVICE_ACCOUNT="${OPERATIONS_SERVICE_ACCOUNT:?Defina OPERATIONS_SERVICE_ACCOUNT}"

APP_IMAGE="${APP_IMAGE:?Defina APP_IMAGE pelo digest aprovado no CI}"
WEB_IMAGE="${WEB_IMAGE:?Defina WEB_IMAGE pelo digest aprovado no CI}"

ADMIN_SERVICE="${ADMIN_SERVICE:-certificados-admin-api}"
CONSULTA_SERVICE="${CONSULTA_SERVICE:-certificados-consulta}"
WEB_SERVICE="${WEB_SERVICE:-certificados-painel}"
MIGRATION_JOB="${MIGRATION_JOB:-certificados-migrate}"
WORKER_JOB="${WORKER_JOB:-certificados-emission-worker}"

ADMIN_API_HOST="${ADMIN_API_HOST:?Defina o hostname interno do serviço admin}"
CONSULTA_API_HOST="${CONSULTA_API_HOST:?Defina o hostname do serviço de consulta}"
ADMIN_FRONTEND_URL="${ADMIN_FRONTEND_URL:?Defina ADMIN_FRONTEND_URL}"
PUBLIC_VALIDATION_BASE_URL="${PUBLIC_VALIDATION_BASE_URL:?Defina PUBLIC_VALIDATION_BASE_URL}"
DRIVE_FOLDER_ID="${DRIVE_FOLDER_ID:-}"
GOOGLE_PICKER_CLIENT_ID="${GOOGLE_PICKER_CLIENT_ID:?Defina GOOGLE_PICKER_CLIENT_ID}"
GOOGLE_PICKER_APP_ID="${GOOGLE_PICKER_APP_ID:-}"
GOOGLE_DRIVE_OAUTH_REDIRECT_URI="${GOOGLE_DRIVE_OAUTH_REDIRECT_URI:?Defina GOOGLE_DRIVE_OAUTH_REDIRECT_URI}"
GOOGLE_DRIVE_UPLOAD_PRINCIPAL_EMAIL="${GOOGLE_DRIVE_UPLOAD_PRINCIPAL_EMAIL:?Defina GOOGLE_DRIVE_UPLOAD_PRINCIPAL_EMAIL}"
GOOGLE_DRIVE_PUBLIC_READER_EMAIL="${GOOGLE_DRIVE_PUBLIC_READER_EMAIL:?Defina GOOGLE_DRIVE_PUBLIC_READER_EMAIL}"
VPC_NETWORK="${VPC_NETWORK:?Defina VPC_NETWORK para impedir acesso direto ao admin}"
VPC_SUBNET="${VPC_SUBNET:?Defina VPC_SUBNET na mesma região}"
FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:?Defina somente os proxies confiáveis}"
TRUSTED_PROXY_CIDRS="${TRUSTED_PROXY_CIDRS:?Defina somente os proxies confiáveis}"

DATABASE_SECRET="${DATABASE_SECRET:-certificados-database-url}"
POSTGRES_CA_SECRET="${POSTGRES_CA_SECRET:-certificados-postgres-ca}"
GOOGLE_ADMIN_TOKEN_SECRET="${GOOGLE_ADMIN_TOKEN_SECRET:-certificados-google-admin-oauth-token}"
GOOGLE_PUBLIC_TOKEN_SECRET="${GOOGLE_PUBLIC_TOKEN_SECRET:-certificados-google-public-readonly-token}"
GOOGLE_PICKER_CLIENT_SECRET_NAME="${GOOGLE_PICKER_CLIENT_SECRET_NAME:-certificados-google-picker-client-secret}"
GOOGLE_PICKER_API_KEY_NAME="${GOOGLE_PICKER_API_KEY_NAME:-certificados-google-picker-api-key}"
JWT_SECRET_NAME="${JWT_SECRET_NAME:-certificados-jwt-secret}"
DOCUMENT_KEYRING_SECRET="${DOCUMENT_KEYRING_SECRET:-certificados-document-hash-keyring}"
BATCH_KEYRING_SECRET="${BATCH_KEYRING_SECRET:-certificados-batch-payload-keyring}"
DOCUMENT_HASH_ACTIVE_KEY_ID="${DOCUMENT_HASH_ACTIVE_KEY_ID:?Defina DOCUMENT_HASH_ACTIVE_KEY_ID}"
BATCH_PAYLOAD_ACTIVE_KEY_ID="${BATCH_PAYLOAD_ACTIVE_KEY_ID:?Defina BATCH_PAYLOAD_ACTIVE_KEY_ID}"

require_digest() {
  case "$1" in
    *@sha256:????????????????????????????????????????????????????????????????) ;;
    *) echo "Use imagem imutável por digest sha256: $1" >&2; exit 64 ;;
  esac
}
require_digest "$APP_IMAGE"
require_digest "$WEB_IMAGE"
if [[ "$FORWARDED_ALLOW_IPS" == "*" || "$TRUSTED_PROXY_CIDRS" == *"/0"* ]]; then
  echo "Proxies irrestritos não são permitidos." >&2
  exit 64
fi

COMMON_ENV="APP_ENV=production,DATABASE_URL_FILE=/secrets/database/url,DOCUMENT_HASH_KEYRING_FILE=/secrets/document/keyring.json,DOCUMENT_HASH_ACTIVE_KEY_ID=${DOCUMENT_HASH_ACTIVE_KEY_ID},STORAGE_PROVIDER=google_drive,GOOGLE_DRIVE_AUTH_MODE=oauth_user,GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID=${DRIVE_FOLDER_ID},PUBLIC_VALIDATION_BASE_URL=${PUBLIC_VALIDATION_BASE_URL},MINIMIZE_DOCUMENT_PLAINTEXT=true,FORWARDED_ALLOW_IPS=${FORWARDED_ALLOW_IPS},TRUSTED_PROXY_CIDRS=${TRUSTED_PROXY_CIDRS},DB_POOL_SIZE=3,DB_MAX_OVERFLOW=2,DB_POOL_TIMEOUT=30,DB_POOL_RECYCLE=300"
COMMON_SECRETS="/secrets/database/url=${DATABASE_SECRET}:latest,/secrets/database/ca.pem=${POSTGRES_CA_SECRET}:latest,/secrets/document/keyring.json=${DOCUMENT_KEYRING_SECRET}:latest"

deploy_consulta() {
  gcloud run deploy "$CONSULTA_SERVICE" \
    --project "$PROJECT" --region "$REGION" \
    --service-account "$PUBLIC_SERVICE_ACCOUNT" \
    --image "$APP_IMAGE" --allow-unauthenticated --ingress all --port 8080 \
    --cpu 1 --memory 512Mi --concurrency 40 --min-instances 0 \
    --max-instances "${CONSULTA_MAX_INSTANCES:-4}" --timeout 120 \
    --set-env-vars="APP_TARGET=consulta,GOOGLE_DRIVE_ACCESS_MODE=read_only,GOOGLE_PUBLIC_OAUTH_TOKEN_FILE=/secrets/google/public-token.json,PUBLIC_RATE_LIMIT_REQUESTS=60,PUBLIC_RATE_LIMIT_WINDOW_SECONDS=60,PUBLIC_CONFIRM_RATE_LIMIT_REQUESTS=8,PUBLIC_CONFIRM_RATE_LIMIT_WINDOW_SECONDS=900,${COMMON_ENV}" \
    --set-secrets="/secrets/google/public-token.json=${GOOGLE_PUBLIC_TOKEN_SECRET}:latest,${COMMON_SECRETS}" \
    --quiet "$@"
}

deploy_admin() {
  # Unauthenticated at IAM because browser cookies are enforced by the app,
  # but ingress is internal: the run.app endpoint is not directly public.
  gcloud run deploy "$ADMIN_SERVICE" \
    --project "$PROJECT" --region "$REGION" \
    --service-account "$ADMIN_SERVICE_ACCOUNT" \
    --image "$APP_IMAGE" --allow-unauthenticated --ingress internal --port 8080 \
    --cpu 1 --memory 1Gi --concurrency 8 --min-instances 0 \
    --max-instances "${ADMIN_MAX_INSTANCES:-3}" --timeout 120 \
    --set-env-vars="APP_TARGET=admin,GOOGLE_DRIVE_ACCESS_MODE=read_write,GOOGLE_ADMIN_OAUTH_TOKEN_FILE=/secrets/google/admin-token.json,GOOGLE_PICKER_CLIENT_ID=${GOOGLE_PICKER_CLIENT_ID},GOOGLE_PICKER_CLIENT_SECRET_FILE=/secrets/google/picker-client-secret,GOOGLE_PICKER_API_KEY_FILE=/secrets/google/picker-api-key,GOOGLE_PICKER_APP_ID=${GOOGLE_PICKER_APP_ID},GOOGLE_DRIVE_OAUTH_REDIRECT_URI=${GOOGLE_DRIVE_OAUTH_REDIRECT_URI},GOOGLE_DRIVE_UPLOAD_PRINCIPAL_EMAIL=${GOOGLE_DRIVE_UPLOAD_PRINCIPAL_EMAIL},GOOGLE_DRIVE_PUBLIC_READER_EMAIL=${GOOGLE_DRIVE_PUBLIC_READER_EMAIL},JWT_SECRET_FILE=/secrets/jwt/value,BATCH_PAYLOAD_KEYS_FILE=/secrets/batch/keyring.json,BATCH_PAYLOAD_ACTIVE_KEY_ID=${BATCH_PAYLOAD_ACTIVE_KEY_ID},BATCH_WORKER_MODE=external,BATCH_WORKER_DISPATCH_MODE=cloud_run_job,BATCH_WORKER_TRIGGER_URL=https://run.googleapis.com/v2/projects/${PROJECT}/locations/${REGION}/jobs/${WORKER_JOB}:run,AUTH_COOKIE_SECURE=true,AUTH_COOKIE_SAMESITE=lax,ADMIN_FRONTEND_URL=${ADMIN_FRONTEND_URL},CORS_ALLOWED_ORIGINS=${ADMIN_FRONTEND_URL},DOWNLOAD_TEMP_DIR=/tmp/certificados-downloads,MAX_ZIP_CERTIFICATES=100,MAX_ZIP_TOTAL_BYTES=209715200,BULK_DOWNLOAD_REQUESTS_PER_HOUR=12,${COMMON_ENV}" \
    --set-secrets="/secrets/google/admin-token.json=${GOOGLE_ADMIN_TOKEN_SECRET}:latest,/secrets/google/picker-client-secret=${GOOGLE_PICKER_CLIENT_SECRET_NAME}:latest,/secrets/google/picker-api-key=${GOOGLE_PICKER_API_KEY_NAME}:latest,/secrets/jwt/value=${JWT_SECRET_NAME}:latest,/secrets/batch/keyring.json=${BATCH_KEYRING_SECRET}:latest,${COMMON_SECRETS}" \
    --quiet "$@"
}

deploy_web() {
  # Direct VPC egress makes the request to the internal admin service an
  # internal Cloud Run source; no Serverless VPC Access connector is needed.
  gcloud run deploy "$WEB_SERVICE" \
    --project "$PROJECT" --region "$REGION" \
    --service-account "$WEB_SERVICE_ACCOUNT" \
    --image "$WEB_IMAGE" --allow-unauthenticated --ingress all --port 8080 \
    --cpu 1 --memory 256Mi --concurrency 80 --min-instances 0 \
    --max-instances "${WEB_MAX_INSTANCES:-4}" --timeout 120 \
    --network "$VPC_NETWORK" --subnet "$VPC_SUBNET" --vpc-egress all-traffic \
    --set-env-vars="ADMIN_API_HOST=${ADMIN_API_HOST},CONSULTA_API_HOST=${CONSULTA_API_HOST}" \
    --quiet "$@"
}

deploy_migration_job() {
  gcloud run jobs deploy "$MIGRATION_JOB" \
    --project "$PROJECT" --region "$REGION" \
    --service-account "$OPERATIONS_SERVICE_ACCOUNT" \
    --image "$APP_IMAGE" \
    --set-env-vars="APP_TARGET=migrate,APP_ENV=production,DATABASE_URL_FILE=/secrets/database/url" \
    --set-secrets="/secrets/database/url=${DATABASE_SECRET}:latest,/secrets/database/ca.pem=${POSTGRES_CA_SECRET}:latest" \
    --tasks 1 --parallelism 1 --max-retries 0 --task-timeout 10m --quiet
}

run_migrations() {
  deploy_migration_job
  gcloud run jobs execute "$MIGRATION_JOB" \
    --project "$PROJECT" --region "$REGION" --wait
}

stage() {
  # Migration 0009 is additive (OAuth transit state + validated folder grants).
  run_migrations
  deploy_consulta --no-traffic --tag candidate
  deploy_admin --no-traffic --tag candidate
  deploy_web --no-traffic --tag candidate
}

promote() {
  gcloud run services update-traffic "$CONSULTA_SERVICE" --project "$PROJECT" --region "$REGION" --to-latest --quiet
  gcloud run services update-traffic "$ADMIN_SERVICE" --project "$PROJECT" --region "$REGION" --to-latest --quiet
  gcloud run services update-traffic "$WEB_SERVICE" --project "$PROJECT" --region "$REGION" --to-latest --quiet
}

rollback() {
  : "${ADMIN_ROLLBACK_REVISION:?Defina ADMIN_ROLLBACK_REVISION}"
  : "${CONSULTA_ROLLBACK_REVISION:?Defina CONSULTA_ROLLBACK_REVISION}"
  : "${WEB_ROLLBACK_REVISION:?Defina WEB_ROLLBACK_REVISION}"
  # Schema is deliberately not downgraded during rollback.
  gcloud run services update-traffic "$ADMIN_SERVICE" --project "$PROJECT" --region "$REGION" --to-revisions="${ADMIN_ROLLBACK_REVISION}=100" --quiet
  gcloud run services update-traffic "$CONSULTA_SERVICE" --project "$PROJECT" --region "$REGION" --to-revisions="${CONSULTA_ROLLBACK_REVISION}=100" --quiet
  gcloud run services update-traffic "$WEB_SERVICE" --project "$PROJECT" --region "$REGION" --to-revisions="${WEB_ROLLBACK_REVISION}=100" --quiet
}

show_status() {
  for service in "$CONSULTA_SERVICE" "$ADMIN_SERVICE" "$WEB_SERVICE"; do
    gcloud run services describe "$service" --project "$PROJECT" --region "$REGION" \
      --format='table(metadata.name,status.url,status.latestReadyRevisionName,status.traffic[].revisionName,status.traffic[].percent)'
  done
}

usage() {
  echo "Uso: $0 {migrate|stage|promote|rollback|status}" >&2
  echo "stage não recebe tráfego; promote e rollback alteram tráfego explicitamente." >&2
}

case "${1:-status}" in
  migrate) run_migrations ;;
  stage) stage ;;
  promote) promote ;;
  rollback) rollback ;;
  status) show_status ;;
  *) usage; exit 64 ;;
esac
