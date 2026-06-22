#!/usr/bin/env sh
set -eu

ENV_FILE="${ENV_FILE:-.env.production}"
COMPOSE="docker compose --env-file $ENV_FILE -f compose.production.yaml"

$COMPOSE config --quiet
$COMPOSE build
$COMPOSE --profile tools run --rm migrate
$COMPOSE up -d --remove-orphans
$COMPOSE ps
