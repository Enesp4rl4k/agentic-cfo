#!/usr/bin/env bash
# Bring the production stack (docker-compose.prod.yml) up from a checkout with a filled-in .env.
#
#   ./scripts/up-prod.sh
#
# This is THE first-deploy and every-deploy "bring it up" step: docs/ops/staging.md section 6 and docs/ops/runbook.md
# call it, and CI (.github/workflows/stack.yml) runs this same script on a clean runner. It does, in order:
#
#   1. checks the tools and that .env holds the values compose cannot start without
#   2. sets IMAGE_TAG in .env to the checkout's short commit (UP_KEEP_IMAGE_TAG=1 keeps the value already there): the
#      images are tagged with it and /api/v1/version shows it
#   3. docker compose build
#   4. migrate: `alembic upgrade head`, then `python -m app.core.preflight --db` (a FATAL finding stops here,
#      before anything is replaced)
#   5. docker compose up -d, then waits (bounded) until every long-running service is healthy; one that exits,
#      restarts or turns unhealthy stops the wait at once
#   6. prints `docker compose ps`; on any failure prints the logs of every service
#
# It does NOT run the smoke test, the backup or the restore drill: those are the next steps of the checklist.
#
# Optional environment:
#   COMPOSE_FILE            default docker-compose.prod.yml (several files: a:b, the compose convention)
#   UP_TIMEOUT_SECONDS      how long step 5 waits for health, default 600
#   UP_KEEP_IMAGE_TAG=1     do not overwrite IMAGE_TAG in .env
#   UP_SKIP_BUILD=1         use the images already on this machine (CI builds them in a cached step)
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# COMPOSE_FILE may name several files (docker-compose.prod.yml:docker-compose.ci.yml); docker compose reads it itself.
export COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
TIMEOUT="${UP_TIMEOUT_SECONDS:-600}"
dc() { docker compose "$@"; }
log() { printf '%s up-prod: %s\n' "$(date -u +%FT%TZ)" "$*"; }
die() { printf '%s up-prod: FAIL %s\n' "$(date -u +%FT%TZ)" "$*" >&2; exit 1; }

dump_logs() {
  echo "----- docker compose ps -a -----"
  dc ps -a || true
  for svc in $(dc config --services 2>/dev/null); do
    echo "----- logs: $svc (last 150 lines) -----"
    dc logs --no-color --tail=150 "$svc" 2>&1 || true
  done
}
trap 'rc=$?; if [[ $rc -ne 0 ]]; then dump_logs; fi' EXIT

command -v docker >/dev/null || die "docker is not installed"
docker compose version >/dev/null 2>&1 || die "the docker compose plugin is not installed"
[[ -f .env ]] || die ".env is missing: cp .env.example .env and fill it in (docs/ops/staging.md section 4, docs/ops/first-deploy-checklist.md)"

env_value() { grep -E "^$1=" .env | tail -n1 | tr -d '\r' | cut -d= -f2- || true; }
for key in APP_DOMAIN API_DOMAIN ACME_EMAIL POSTGRES_PASSWORD BACKEND_SECRET_KEY NEXTAUTH_SECRET; do
  [[ -n "$(env_value "$key")" ]] || die "$key is not set in .env"
done

# IMAGE_TAG is the short commit of this checkout (so a deploy of a newer checkout never keeps the old tag);
# UP_KEEP_IMAGE_TAG=1 keeps the value already in .env.
if [[ "${UP_KEEP_IMAGE_TAG:-0}" != 1 || -z "$(env_value IMAGE_TAG)" ]]; then
  tag="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  if grep -qE '^#? *IMAGE_TAG=' .env; then
    sed -i "s|^#\? *IMAGE_TAG=.*|IMAGE_TAG=${tag}|" .env
  else
    printf 'IMAGE_TAG=%s\n' "$tag" >> .env
  fi
fi
log "IMAGE_TAG=$(env_value IMAGE_TAG)"

dc config -q || die "docker compose config is invalid (a required value in .env is missing?)"

if [[ "${UP_SKIP_BUILD:-0}" != 1 ]]; then
  log "build"
  dc build
fi

log "migrate (alembic upgrade head, then the preflight with --db)"
dc run --rm migrate

log "up -d"
dc up -d

log "waiting up to ${TIMEOUT}s for health"
deadline=$((SECONDS + TIMEOUT))
services=()
while IFS= read -r svc; do
  [[ "$svc" == migrate ]] || services+=("$svc")
done < <(dc config --services)

while :; do
  pending=()
  for svc in "${services[@]}"; do
    cid="$(dc ps -q "$svc" | head -n1)"
    [[ -n "$cid" ]] || { pending+=("$svc(no container)"); continue; }
    state="$(docker inspect -f '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"
    status="${state%%|*}"; health="${state##*|}"
    case "$status|$health" in
      running\|healthy | running\|none) ;;
      running\|starting) pending+=("$svc(starting)") ;;
      *) die "service $svc is $status/$health" ;;
    esac
  done
  if [[ ${#pending[@]} -eq 0 ]]; then break; fi
  (( SECONDS < deadline )) || die "timed out; not healthy: ${pending[*]}"
  sleep 5
done

mid="$(dc ps -aq migrate | head -n1)"
[[ -n "$mid" && "$(docker inspect -f '{{.State.ExitCode}}' "$mid")" == 0 ]] || die "migrate did not exit 0"

dc ps
log "up: every service is healthy, migrate exited 0"
