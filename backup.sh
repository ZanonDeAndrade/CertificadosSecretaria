#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root_dir"
source "$root_dir/scripts/local_server_env.sh"
[[ -f .env.local-server ]] || { echo 'Arquivo .env.local-server ausente.' >&2; exit 64; }

secret_dir="$(local_server_env_value LOCAL_SECRETS_DIR secrets/local-server)"

backup_dir="${1:-$root_dir/backups}"
timestamp="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_dir"
umask 077
database_backup="$backup_dir/postgres-$timestamp.dump"
storage_backup="$backup_dir/storage-$timestamp.tar.gz"
config_backup="$backup_dir/config-$timestamp.tar.gz"
compose=(docker compose --env-file .env.local-server -f compose.local-server.yaml)

[[ ! -e "$database_backup" && ! -e "$storage_backup" && ! -e "$config_backup" ]] || {
  echo 'Já existe um backup com este timestamp; tente novamente.' >&2
  exit 1
}

"${compose[@]}" exec -T db sh -ec 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl' >"$database_backup"
# O volume pertence ao UID não-root da aplicação; crie o tar dentro do
# container em vez de abrir os PDFs diretamente como usuário do host.
"${compose[@]}" exec -T admin tar -C /data -czf - storage >"$storage_backup"
tar -czf "$config_backup" .env.local-server "$secret_dir"

printf 'Backup criado:\n- %s\n- %s\n- %s\n' "$database_backup" "$storage_backup" "$config_backup"
