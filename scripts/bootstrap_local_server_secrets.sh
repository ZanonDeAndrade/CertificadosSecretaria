#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/local_server_env.sh"

secret_dir="${1:-$(local_server_env_value LOCAL_SECRETS_DIR secrets/local-server)}"
postgres_user="$(local_server_identifier POSTGRES_USER certificados)"
postgres_db="$(local_server_identifier POSTGRES_DB certificados)"
umask 077
mkdir -p "$secret_dir"
chmod 700 "$secret_dir"

write_if_missing() {
  local name="$1"
  local value="$2"
  local path="$secret_dir/$name"
  if [[ ! -e "$path" ]]; then
    printf '%s\n' "$value" >"$path"
    # Docker Compose mounts file-based secrets as bind mounts and does not map
    # UID/GID for local files. The directory remains 0700; readable files let
    # the non-root PostgreSQL and application users read their mounted secret.
    chmod 644 "$path"
    printf 'Criado: %s\n' "$path"
  fi
}

random_base64() {
  openssl rand -base64 48 | tr -d '\n'
}

postgres_password="$(cat "$secret_dir/postgres_password" 2>/dev/null || openssl rand -hex 32)"
write_if_missing postgres_password "$postgres_password"
write_if_missing database_url "postgresql+psycopg://${postgres_user}:${postgres_password}@db:5432/${postgres_db}?sslmode=disable"
write_if_missing jwt_secret "$(random_base64)"
write_if_missing document_hash_keyring "{\"v1\":\"$(random_base64)\"}"

if [[ ! -e "$secret_dir/batch_payload_keys" ]]; then
  batch_key="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\n')"
  write_if_missing batch_payload_keys "{\"v1\":\"${batch_key}\"}"
fi

if [[ ! -e "$secret_dir/admin_initial_password" ]]; then
  read -r -s -p 'Senha inicial do administrador: ' admin_password
  printf '\n'
  if [[ -z "$admin_password" ]]; then
    echo 'A senha inicial não pode ser vazia.' >&2
    exit 64
  fi
  write_if_missing admin_initial_password "$admin_password"
fi

echo 'Segredos prontos. Guarde uma cópia segura fora do servidor.'
