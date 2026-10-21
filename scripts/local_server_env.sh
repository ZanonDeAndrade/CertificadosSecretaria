#!/usr/bin/env bash

# Read simple KEY=value entries from .env.local-server without executing it.
# Docker Compose performs its own interpolation; these helpers only read the
# literal values that operational scripts need before Compose is running.
local_server_env_value() {
  local key="$1"
  local fallback="${2:-}"
  local env_file="${LOCAL_SERVER_ENV_FILE:-.env.local-server}"
  local value

  [[ "$key" =~ ^[A-Z][A-Z0-9_]*$ ]] || {
    echo "Nome de variável inválido: $key" >&2
    return 64
  }
  [[ -f "$env_file" ]] || {
    printf '%s' "$fallback"
    return 0
  }

  value="$(awk -v key="$key" '
    $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
      sub("^[[:space:]]*" key "[[:space:]]*=[[:space:]]*", "")
      sub(/\r$/, "")
      print
      exit
    }
  ' "$env_file")"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  printf '%s' "${value:-$fallback}"
}

local_server_identifier() {
  local value
  value="$(local_server_env_value "$1" "$2")"
  [[ "$value" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || {
    echo "$1 deve usar somente letras, números e underscore." >&2
    return 64
  }
  printf '%s' "$value"
}
