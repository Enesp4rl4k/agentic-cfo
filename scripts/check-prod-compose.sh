#!/usr/bin/env bash
# Static checks for the single-VPS stack, runnable without a server:
# shellcheck on the ops scripts, then `docker compose config` on
# docker-compose.prod.yml with throwaway values for its required variables.
# CI runs this; nothing here starts a container.
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

shellcheck scripts/backup.sh scripts/restore-drill.sh scripts/check-prod-compose.sh

[[ -e .env ]] && { echo "check-prod-compose: refusing to overwrite an existing .env" >&2; exit 2; }
trap 'rm -f .env' EXIT
cp .env.example .env
for key in POSTGRES_PASSWORD REDIS_PASSWORD; do
  echo "$key=$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')" >> .env
done
printf '%s\n' APP_DOMAIN=app.example.test API_DOMAIN=api.example.test \
  ACME_EMAIL=ops@example.test >> .env
docker compose -f docker-compose.prod.yml config -q
echo "check-prod-compose: ok"
