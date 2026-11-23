#!/usr/bin/env bash
# Static checks for the single-VPS stack, runnable without a server:
# lint the ops scripts, then `docker compose config` on
# docker-compose.prod.yml with throwaway values for its required variables.
# CI runs this; nothing here starts a container.
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

shellcheck scripts/backup.sh scripts/restore-drill.sh scripts/check-prod-compose.sh

[[ -e .env ]] && { echo "check-prod-compose: refusing to overwrite an existing .env" >&2; exit 2; }
trap 'rm -f .env' EXIT
cp .env.example .env
echo "POSTGRES_PASSWORD=$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')" >> .env
printf '%s\n' APP_DOMAIN=app.example.test API_DOMAIN=api.example.test \
  ACME_EMAIL=ops@example.test >> .env
docker compose -f docker-compose.prod.yml config -q

# Structural rules of the stack, checked on the resolved configuration.
RESOLVED="$(mktemp)"
trap 'rm -f .env "$RESOLVED"' EXIT
docker compose -f docker-compose.prod.yml config --format json > "$RESOLVED"
PY=""
for candidate in python3 python; do
  if "$candidate" -c 'import sys' >/dev/null 2>&1; then PY="$candidate"; break; fi
done
[[ -n "$PY" ]] || { echo "check-prod-compose: python is required" >&2; exit 2; }
"$PY" - "$RESOLVED" <<'PYEOF'
import json, sys

cfg = json.load(open(sys.argv[1], encoding="utf-8"))
services, errors = cfg["services"], []

for name, svc in services.items():
    ports = svc.get("ports") or []
    if name != "caddy" and ports:
        errors.append(f"{name} publishes ports")
    for key in ("mem_limit", "cpus"):
        if not svc.get(key):
            errors.append(f"{name} has no {key}")
    if name != "migrate" and (svc.get("logging") or {}).get("options", {}).get("max-size") is None:
        errors.append(f"{name} has no log rotation")

published = {int(p["published"]) for p in services["caddy"].get("ports", [])}
if published != {80, 443}:
    errors.append(f"caddy publishes {sorted(published)}, expected [80, 443]")

for name in ("postgres", "redis"):
    if set(services[name].get("networks", {})) != {"internal"}:
        errors.append(f"{name} must be on the internal network only")
if not cfg["networks"]["internal"].get("internal"):
    errors.append("network 'internal' is not internal: true")

fe = services["frontend"]
if fe.get("env_file"):
    errors.append("frontend must not read env_file (it would receive backend secrets)")
extra = set(fe.get("environment", {})) - {"NEXT_PUBLIC_API_URL", "NEXTAUTH_URL", "NEXTAUTH_SECRET"}
if extra:
    errors.append(f"frontend environment has unexpected keys: {sorted(extra)}")

for name in ("migrate", "backend", "worker", "worker-maintenance"):
    env = services[name]["environment"]
    if env.get("APP_ENV") not in ("production", "staging"):
        errors.append(f"{name}: APP_ENV is {env.get('APP_ENV')!r}")
    if env.get("TRUSTED_PROXY_COUNT") != "1":
        errors.append(f"{name}: TRUSTED_PROXY_COUNT is not 1")
    if env.get("SCHEDULER_PROCESS") != "worker":
        errors.append(f"{name}: SCHEDULER_PROCESS is not worker")
for name in ("backend", "worker", "worker-maintenance"):
    if "app.core.preflight" not in " ".join(services[name].get("entrypoint") or []):
        errors.append(f"{name}: entrypoint does not run the preflight")
for name in ("worker", "worker-maintenance"):
    if not services[name].get("healthcheck") or not services[name].get("stop_grace_period"):
        errors.append(f"{name}: needs a healthcheck and stop_grace_period")

if errors:
    print("check-prod-compose: FAIL", *errors, sep=chr(10) + "  - ", file=sys.stderr)
    sys.exit(1)
PYEOF
echo "check-prod-compose: ok"
