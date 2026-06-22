#!/usr/bin/env bash
# Reproducible Cloud Run deployment for the production backend.
# Secrets are read by Cloud Run from Secret Manager and are never copied into
# the image or passed as plain environment variables.
set -euo pipefail

# Git Bash on Windows rewrites Linux paths inside these gcloud arguments. Keep
# only those arguments untouched; excluding every argument breaks gcloud's own
# Windows launcher.
export MSYS2_ARG_CONV_EXCL="--set-env-vars;--set-secrets"

PROJECT="${PROJECT:-certificados-prod-2ea4fc}"
REGION="${REGION:-us-east1}"
REPOSITORY="${REPOSITORY:-certificados}"
RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT:-certificados-runtime@${PROJECT}.iam.gserviceaccount.com}"

CONSULTA_SERVICE="${CONSULTA_SERVICE:-certificados-consulta}"
ADMIN_SERVICE="${ADMIN_SERVICE:-certificados-admin-api}"
WEB_SERVICE="${WEB_SERVICE:-certificados-painel}"
MIGRATION_JOB="${MIGRATION_JOB:-certificados-migrate}"

IMAGE_TAG="${IMAGE_TAG:-$(date -u +%Y%m%d-%H%M%S)}"
IMAGE="${IMAGE:-${REGION}-docker.pkg.dev/${PROJECT}/${REPOSITORY}/app:${IMAGE_TAG}}"
WEB_IMAGE="${WEB_IMAGE:-${REGION}-docker.pkg.dev/${PROJECT}/${REPOSITORY}/web:${IMAGE_TAG}}"

DRIVE_FOLDER_ID="${DRIVE_FOLDER_ID:-1aXRVubgM5LC0OStdRr8HJUBjqRtiiizB}"
PUBLIC_VALIDATION_BASE_URL="${PUBLIC_VALIDATION_BASE_URL:-https://certificados-consulta-hj3rwyicha-ue.a.run.app}"

ADMIN_FRONTEND_URL="${ADMIN_FRONTEND_URL:-https://certificados-painel-hj3rwyicha-ue.a.run.app}"
ADMIN_API_HOST="${ADMIN_API_HOST:-certificados-admin-api-hj3rwyicha-ue.a.run.app}"

DATABASE_SECRET="${DATABASE_SECRET:-certificados-database-url}"
GOOGLE_TOKEN_SECRET="${GOOGLE_TOKEN_SECRET:-certificados-google-oauth-token}"
JWT_SECRET="${JWT_SECRET:-certificados-jwt-secret}"
DOCUMENT_SECRET="${DOCUMENT_SECRET:-certificados-document-hash-secret}"

COMMON_ENV="APP_ENV=production,DATABASE_URL_FILE=/secrets/database/url,GOOGLE_OAUTH_TOKEN_FILE=/secrets/google/token.json,DOCUMENT_HASH_SECRET_FILE=/secrets/document/value,STORAGE_PROVIDER=google_drive,GOOGLE_DRIVE_AUTH_MODE=oauth_user,GOOGLE_DRIVE_CERTIFICATES_FOLDER_ID=${DRIVE_FOLDER_ID},PUBLIC_VALIDATION_BASE_URL=${PUBLIC_VALIDATION_BASE_URL},MINIMIZE_DOCUMENT_PLAINTEXT=true,DB_POOL_SIZE=3,DB_MAX_OVERFLOW=2,DB_POOL_RECYCLE=300"
COMMON_SECRETS="/secrets/database/url=${DATABASE_SECRET}:latest,/secrets/google/token.json=${GOOGLE_TOKEN_SECRET}:latest,/secrets/document/value=${DOCUMENT_SECRET}:latest"

build_image() {
  gcloud builds submit \
    --project "$PROJECT" \
    --tag "$IMAGE" \
    .
}

build_web_image() {
  gcloud builds submit \
    --project "$PROJECT" \
    --config deploy/cloudrun/cloudbuild-web.yaml \
    --substitutions "_IMAGE=${WEB_IMAGE}" \
    .
}

deploy_consulta() {
  gcloud run deploy "$CONSULTA_SERVICE" \
    --project "$PROJECT" \
    --region "$REGION" \
    --service-account "$RUNTIME_SERVICE_ACCOUNT" \
    --image "$IMAGE" \
    --allow-unauthenticated \
    --port 8080 \
    --cpu 1 \
    --memory 512Mi \
    --min-instances 0 \
    --max-instances 4 \
    --timeout 120 \
    --set-env-vars="APP_TARGET=consulta,PUBLIC_RATE_LIMIT_REQUESTS=60,PUBLIC_RATE_LIMIT_WINDOW_SECONDS=60,${COMMON_ENV}" \
    --set-secrets="$COMMON_SECRETS" \
    --quiet
}

deploy_admin() {
  gcloud run deploy "$ADMIN_SERVICE" \
    --project "$PROJECT" \
    --region "$REGION" \
    --service-account "$RUNTIME_SERVICE_ACCOUNT" \
    --image "$IMAGE" \
    --allow-unauthenticated \
    --port 8080 \
    --cpu 1 \
    --memory 1Gi \
    --min-instances 0 \
    --max-instances 4 \
    --timeout 900 \
    --set-env-vars="APP_TARGET=admin,JWT_SECRET_FILE=/secrets/jwt/value,AUTH_COOKIE_SECURE=true,AUTH_COOKIE_SAMESITE=lax,ADMIN_FRONTEND_URL=${ADMIN_FRONTEND_URL},CORS_ALLOWED_ORIGINS=${ADMIN_FRONTEND_URL},LOGIN_RATE_LIMIT_WINDOW_SECONDS=900,LOGIN_MAX_FAILURES_PER_IP=20,LOGIN_MAX_FAILURES_PER_USER=8,LOGIN_LOCKOUT_SECONDS=900,${COMMON_ENV}" \
    --set-secrets="/secrets/jwt/value=${JWT_SECRET}:latest,${COMMON_SECRETS}" \
    --quiet
}

deploy_web() {
  gcloud run deploy "$WEB_SERVICE" \
    --project "$PROJECT" \
    --region "$REGION" \
    --service-account "$RUNTIME_SERVICE_ACCOUNT" \
    --image "$WEB_IMAGE" \
    --allow-unauthenticated \
    --port 8080 \
    --cpu 1 \
    --memory 256Mi \
    --min-instances 0 \
    --max-instances 4 \
    --timeout 900 \
    --set-env-vars="ADMIN_API_HOST=${ADMIN_API_HOST}" \
    --quiet
}

deploy_migration_job() {
  gcloud run jobs deploy "$MIGRATION_JOB" \
    --project "$PROJECT" \
    --region "$REGION" \
    --service-account "$RUNTIME_SERVICE_ACCOUNT" \
    --image "$IMAGE" \
    --set-env-vars="APP_TARGET=migrate,APP_ENV=production,DATABASE_URL_FILE=/secrets/database/url" \
    --set-secrets="/secrets/database/url=${DATABASE_SECRET}:latest" \
    --tasks 1 \
    --max-retries 0 \
    --quiet
}

run_migrations() {
  deploy_migration_job
  gcloud run jobs execute "$MIGRATION_JOB" \
    --project "$PROJECT" \
    --region "$REGION" \
    --wait
}

show_status() {
  gcloud run services describe "$CONSULTA_SERVICE" \
    --project "$PROJECT" --region "$REGION" \
    --format='table(metadata.name,status.url,status.latestReadyRevisionName,status.traffic[0].percent)'
  gcloud run services describe "$ADMIN_SERVICE" \
    --project "$PROJECT" --region "$REGION" \
    --format='table(metadata.name,status.url,status.latestReadyRevisionName,status.traffic[0].percent)'
  gcloud run services describe "$WEB_SERVICE" \
    --project "$PROJECT" --region "$REGION" \
    --format='table(metadata.name,status.url,status.latestReadyRevisionName,status.traffic[0].percent)'
}

usage() {
  cat <<EOF
Usage: $0 {build|build-web|migrate|consulta|admin|web|deploy|release|status}

  build     Build and push a uniquely tagged image with Cloud Build.
  build-web Build and push the administrative panel image.
  migrate   Create/update the migration job and execute it once.
  consulta  Deploy only the public validation API.
  admin     Deploy only the administrative API.
  web       Deploy only the administrative panel.
  deploy    Deploy both APIs and the panel (does not build or migrate).
  release   Build both images, migrate and deploy all three services.
  status    Show URLs, ready revisions and traffic percentages.

Override configuration with environment variables such as IMAGE,
ADMIN_FRONTEND_URL, PUBLIC_VALIDATION_BASE_URL, PROJECT and REGION.
EOF
}

case "${1:-status}" in
  build) build_image ;;
  build-web) build_web_image ;;
  migrate) run_migrations ;;
  consulta) deploy_consulta ;;
  admin) deploy_admin ;;
  web) deploy_web ;;
  deploy) deploy_consulta && deploy_admin && deploy_web ;;
  release) build_image && build_web_image && run_migrations && deploy_consulta && deploy_admin && deploy_web ;;
  status) show_status ;;
  *) usage; exit 64 ;;
esac
