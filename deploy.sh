#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root_dir"
source "$root_dir/scripts/local_server_env.sh"
compose=(docker compose --env-file .env.local-server -f compose.local-server.yaml)

if [[ ! -f .env.local-server ]]; then
  echo 'Crie .env.local-server a partir de .env.local-server.example e revise LOCAL_SERVER_URL.' >&2
  exit 64
fi

secret_dir="$(local_server_env_value LOCAL_SECRETS_DIR secrets/local-server)"
if [[ ! -f "$secret_dir/database_url" ]]; then
  ./scripts/bootstrap_local_server_secrets.sh "$secret_dir"
fi
chmod 700 "$secret_dir"
chmod 644 "$secret_dir"/*

mkdir -p runtime/storage
docker run --rm -v "$PWD/runtime/storage:/data" alpine:3.24 \
  sh -c 'chown -R 10001:10001 /data && chmod 750 /data'

"${compose[@]}" build
"${compose[@]}" up -d db

for attempt in $(seq 1 30); do
  if "${compose[@]}" exec -T db sh -ec 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null; then
    break
  fi
  [[ "$attempt" -lt 30 ]] || { echo 'PostgreSQL não ficou pronto.' >&2; exit 1; }
  sleep 2
done

"${compose[@]}" run --rm migrate
"${compose[@]}" up -d --force-recreate --remove-orphans admin consulta worker web

web_binding="$("${compose[@]}" port web 8080)"
web_port="${web_binding##*:}"

for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error "http://127.0.0.1:${web_port}/api/health/ready" >/dev/null; then
    echo "Deploy concluído: http://127.0.0.1:${web_port}"
    "${compose[@]}" ps
    exit 0
  fi
  [[ "$attempt" -lt 30 ]] || { echo 'Health check da API falhou.' >&2; exit 1; }
  sleep 2
done
