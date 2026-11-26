#!/usr/bin/env bash
# CI driver for the "Production stack (compose)" job (.github/workflows/stack.yml). One phase per workflow step:
#
#   ./scripts/stack-ci.sh <phase>
#
# Phases, in the order the job runs them: env  tls  migrations  preflight  edge  memory  parser  workers  smoke
# onboarding  backup  restore  scheduler. The stack itself is brought up by scripts/up-prod.sh, the same script
# the runbook tells the operator to run. Nothing here is a mock: every phase talks to the real containers.
#
# Throw-away values only: every secret is generated here, masked in the log and never written anywhere but .env
# (git-ignored) inside the runner. TLS: Caddy issues certificates from its own internal CA for hostnames under
# `.internal` (it never asks Let's Encrypt for them); the phase `tls` trusts that CA on the runner. No compose
# override is needed and the stack's own configuration is used unchanged.
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

export COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml:docker-compose.ci.yml}"
APP_HOST="app.ci.internal"
API_HOST="api.ci.internal"
APP_URL="https://${APP_HOST}"
API_URL="https://${API_HOST}"
SCRATCH="${RUNNER_TEMP:-$PWD/.tmp-agent}/stack-ci"
OWNER_EMAIL="owner@yenisirket-ci.com"
COMPANY="CI Pilot Sirketi"

dc() { docker compose "$@"; }
ok() { printf 'ok    %s\n' "$*"; }
bad() { printf 'FAIL  %s\n' "$*" >&2; exit 1; }
env_value() { grep -E "^$1=" .env | tail -n1 | tr -d '\r' | cut -d= -f2-; }
psql_q() { dc exec -T postgres psql -U "$(env_value POSTGRES_USER || echo aicfo)" -d "$(env_value POSTGRES_DB || echo aicfo)" -At -c "$1"; }
mkdir -p "$SCRATCH"

# The settings this job has to put into .env for a PRODUCTION start: the minimal production configuration.
# docs/ops/first-deploy-checklist.md and docs/ops/configuration.md must name every one (phase `env` checks it).
MINIMAL_KEYS=(APP_DOMAIN API_DOMAIN ACME_EMAIL POSTGRES_PASSWORD BACKEND_SECRET_KEY NEXTAUTH_SECRET
  ERASURE_PSEUDONYM_SECRET PRIVACY_NOTICE_URL TERMS_URL SMTP_HOST SMTP_USER SMTP_PASSWORD NOTIFICATION_FROM)
# Set on top of the minimal list because the checklist's operator steps need them (not needed to start).
EXTRA_KEYS=(PLATFORM_OPERATOR_EMAILS SUPPORT_CONTACT AGE_RECIPIENT BACKUP_RCLONE_REMOTE BACKUP_LOCAL_DIR)

setenv() {
  local key="$1" value="$2"
  if [[ "${3:-}" == secret ]]; then printf '::add-mask::%s\n' "$value"; fi
  if grep -qE "^#? *${key}=" .env; then
    sed -i "s|^#\? *${key}=.*|${key}=${value}|" .env
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

phase_env() {
  [[ ! -e .env ]] || bad ".env already exists; the job starts from a clean checkout"
  cp .env.example .env && chmod 600 .env
  setenv APP_DOMAIN "$APP_HOST"
  setenv API_DOMAIN "$API_HOST"
  setenv ACME_EMAIL "ops@example.test"
  setenv POSTGRES_PASSWORD "$(openssl rand -hex 24)" secret
  setenv BACKEND_SECRET_KEY "$(openssl rand -hex 32)" secret
  setenv NEXTAUTH_SECRET "$(openssl rand -hex 32)" secret
  setenv ERASURE_PSEUDONYM_SECRET "$(openssl rand -hex 32)" secret
  setenv PRIVACY_NOTICE_URL "${APP_URL}/aydinlatma"
  setenv TERMS_URL "${APP_URL}/kosullar"
  # Mail: a sender must be CONFIGURED (invite-only registration needs one, the preflight refuses a start without),
  # but CI has no mail server: an address that cannot resolve makes every delivery fail the documented way.
  setenv SMTP_HOST "smtp.invalid"
  setenv SMTP_USER "ci-user"
  setenv SMTP_PASSWORD "$(openssl rand -hex 12)" secret
  setenv NOTIFICATION_FROM "noreply@ci.internal"
  setenv PLATFORM_OPERATOR_EMAILS "operator@yenisirket-ci.com"
  setenv SUPPORT_CONTACT "destek@yenisirket-ci.com"
  # Backups: an age key pair made here (the private half stays in $SCRATCH, as on the owner's laptop) and a local
  # rclone destination in place of the Turkish object store.
  command -v age-keygen >/dev/null || bad "age is not installed"
  age-keygen -o "$SCRATCH/age.key" 2>/dev/null
  chmod 600 "$SCRATCH/age.key"
  mkdir -p "$SCRATCH/remote" "$SCRATCH/backups"
  setenv AGE_RECIPIENT "$(age-keygen -y "$SCRATCH/age.key")"
  setenv BACKUP_RCLONE_REMOTE ":local:$SCRATCH/remote"
  setenv BACKUP_LOCAL_DIR "$SCRATCH/backups"

  {
    echo "### Minimal production configuration (what this job had to set)"
    echo
    printf '`%s`  ' "${MINIMAL_KEYS[@]}"
    echo
    echo
    echo "Also set for the operator steps: $(printf '`%s` ' "${EXTRA_KEYS[@]}")"
  } >> "${GITHUB_STEP_SUMMARY:-/dev/null}"

  # The documents must name every key this job needed.
  for key in "${MINIMAL_KEYS[@]}" "${EXTRA_KEYS[@]}"; do
    grep -q "\`${key}\`" docs/ops/first-deploy-checklist.md || bad "docs/ops/first-deploy-checklist.md does not name $key"
  done
  for key in "${MINIMAL_KEYS[@]}"; do
    grep -q "\`${key}\`" docs/ops/configuration.md || bad "docs/ops/configuration.md does not name $key"
  done
  ok ".env generated from .env.example; ${#MINIMAL_KEYS[@]} minimal keys and ${#EXTRA_KEYS[@]} operator keys, all documented"
}

phase_tls() {
  echo "127.0.0.1 ${APP_HOST} ${API_HOST}" | sudo tee -a /etc/hosts >/dev/null
  local i
  for i in $(seq 1 60); do
    dc cp caddy:/data/caddy/pki/authorities/local/root.crt "$SCRATCH/caddy-root.crt" 2>/dev/null && break
    sleep 2
  done
  [[ -s "$SCRATCH/caddy-root.crt" ]] || bad "Caddy never created its internal root CA"
  sudo cp "$SCRATCH/caddy-root.crt" /usr/local/share/ca-certificates/caddy-ci.crt
  sudo update-ca-certificates >/dev/null
  for i in $(seq 1 30); do
    curl -fsS --max-time 5 "${API_URL}/health" >/dev/null 2>&1 && { ok "TLS through Caddy works (internal CA trusted)"; return; }
    sleep 2
  done
  curl -sS --max-time 5 "${API_URL}/health" || true
  bad "${API_URL}/health never answered through Caddy"
}

phase_migrations() {
  local mid code
  mid="$(dc ps -aq migrate | head -n1)"
  [[ -n "$mid" ]] || bad "no migrate container"
  code="$(docker inspect -f '{{.State.ExitCode}}' "$mid")"
  [[ "$code" == 0 ]] || bad "migrate exited $code"
  ok "migrate one-shot exited 0"
  local current
  current="$(dc exec -T backend alembic current 2>&1 | tail -n1)"
  grep -q '(head)' <<<"$current" || bad "alembic is not at head: $current"
  ok "alembic current: $current"
}

phase_preflight() {
  local out rc
  out="$(dc exec -T backend python -m app.core.preflight --db 2>&1)" && rc=0 || rc=$?
  echo "$out"
  [[ "$rc" == 0 ]] || bad "production preflight failed (exit $rc)"
  grep -q 'PREFLIGHT ok (production)' <<<"$out" || bad "preflight did not say 'PREFLIGHT ok (production)'"
  grep -q '^FATAL' <<<"$out" && bad "preflight printed a FATAL finding"
  grep -q 'parser_memory' <<<"$out" && bad "preflight reports a parser memory finding for the shipped limits"
  ok "production preflight passes inside the backend container"

  # Negative: a required setting removed must fail, and name the finding.
  for pair in "ERASURE_PSEUDONYM_SECRET:no_pseudonym_secret" "SMTP_USER:mail_required_no_sender" "PRIVACY_NOTICE_URL:no_notice_url"; do
    local var="${pair%%:*}" code="${pair##*:}"
    out="$(dc exec -T -e "${var}=" backend python -m app.core.preflight --db 2>&1)" && rc=0 || rc=$?
    [[ "$rc" != 0 ]] || { echo "$out"; bad "preflight accepted a configuration without $var"; }
    grep -q "\[${code}\]" <<<"$out" || { echo "$out"; bad "preflight without $var did not name [$code]"; }
    ok "preflight without $var exits $rc and names [$code]"
  done

  # The container wrapper itself refuses to start (what protects a deploy): no `exec` of the service happens.
  out="$(dc run --rm --no-deps -T -e ERASURE_PSEUDONYM_SECRET= backend echo SERVICE-STARTED 2>&1)" && rc=0 || rc=$?
  [[ "$rc" != 0 ]] || bad "a backend container started without ERASURE_PSEUDONYM_SECRET"
  grep -q 'SERVICE-STARTED' <<<"$out" && bad "the service command ran despite a FATAL finding"
  ok "a backend container without ERASURE_PSEUDONYM_SECRET refuses to start (exit $rc)"

  startup_logs="$(dc logs backend worker worker-maintenance 2>&1)"   # a variable, not a pipe: `grep -q` closing the pipe early fails under pipefail
  if grep -q 'parser_memory' <<<"$startup_logs"; then
    bad "a service logged a parser_memory finding at startup"
  fi
  ok "no parser_memory finding at startup of backend, worker, worker-maintenance"
}

phase_edge() {
  local code ready commit env
  code="$(curl -sS --max-time 15 -o "$SCRATCH/ready.json" -w '%{http_code}' "${API_URL}/api/v1/ready")"
  cat "$SCRATCH/ready.json"; echo
  [[ "$code" == 200 ]] || bad "/api/v1/ready answered $code through Caddy"
  ready="$(jq -r '.data.status' "$SCRATCH/ready.json")"
  [[ "$ready" == ready || "$ready" == degraded ]] || bad "/api/v1/ready status is $ready"
  for check in database migrations redis; do
    [[ "$(jq -r ".data.checks.${check}" "$SCRATCH/ready.json")" == ok ]] || bad "/api/v1/ready: check $check is not ok"
  done
  ok "/api/v1/ready 200 ($ready), database, migrations and redis ok"

  curl -fsS --max-time 15 "${API_URL}/api/v1/version" -o "$SCRATCH/version.json"
  cat "$SCRATCH/version.json"; echo
  commit="$(jq -r '.data.commit' "$SCRATCH/version.json")"
  env="$(jq -r '.data.environment' "$SCRATCH/version.json")"
  [[ "$commit" == "$(env_value IMAGE_TAG)" ]] || bad "/api/v1/version commit '$commit' is not IMAGE_TAG"
  [[ "$env" == production ]] || bad "/api/v1/version environment is '$env'"
  ok "/api/v1/version: commit $commit, environment production"

  code="$(curl -sS --max-time 20 -L -o "$SCRATCH/landing.html" -w '%{http_code}' "${APP_URL}/")"
  [[ "$code" == 200 ]] || bad "the frontend landing page answered $code through Caddy"
  grep -qi '<html' "$SCRATCH/landing.html" || bad "the landing page is not HTML"
  curl -fsS --max-time 10 "${APP_URL}/api/health" | jq -e '.status == "ok"' >/dev/null || bad "frontend /api/health"
  ok "frontend landing page (200) and /api/health through Caddy"

  # The redirect from http to https that Caddy promises.
  code="$(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' "http://${API_HOST}/health")"
  [[ "$code" == 308 || "$code" == 301 || "$code" == 302 ]] || bad "http://${API_HOST}/health answered $code (want a redirect)"
  ok "plain http redirects to https ($code)"
}

phase_memory() {
  # The documented numbers (docs/ops/staging.md section 2, parser-sizing.md): bytes for mem_limit.
  declare -A want=(
    [backend]=2684354560 [worker]=2147483648 [worker-maintenance]=805306368 [postgres]=2147483648
    [redis]=671088640 [frontend]=536870912 [caddy]=268435456 [migrate]=536870912
  )
  local svc cid got
  for svc in "${!want[@]}"; do
    cid="$(dc ps -aq "$svc" | head -n1)"
    [[ -n "$cid" ]] || bad "no container for $svc"
    got="$(docker inspect -f '{{.HostConfig.Memory}}' "$cid")"
    [[ "$got" == "${want[$svc]}" ]] || bad "$svc memory limit is $got, documented ${want[$svc]}"
    ok "$svc memory limit $got bytes"
  done
  got="$(dc exec -T backend cat /sys/fs/cgroup/memory.max 2>/dev/null || dc exec -T backend cat /sys/fs/cgroup/memory/memory.limit_in_bytes)"
  [[ "$got" == 2684354560 ]] || bad "the backend sees a cgroup limit of $got inside the container"
  ok "the backend container sees its 2560m limit in its own cgroup"
}

phase_parser() {
  # Tesseract with the Turkish model must be in the image.
  dc exec -T backend tesseract --list-langs | grep -qx tur || bad "Tesseract has no Turkish model in the backend image"
  dc exec -T worker tesseract --list-langs | grep -qx tur || bad "Tesseract has no Turkish model in the worker image"
  ok "tesseract tur is installed"
  # The repo's own parser probe (the generator the memory measurement uses), run in the backend container under
  # its real 2560m limit and default parser limits: a 20-page text statement and a 2-page scan through OCR.
  dc cp backend/tests/parser_memory_probe.py backend:/tmp/parser_memory_probe.py
  dc exec -T backend python - <<'PY'
import pathlib, sys, tempfile
sys.path.insert(0, "/tmp")
import parser_memory_probe as probe
from app.services import pdf_isolation
from app.services.ocr_service import extract_text_from_pdf

work = pathlib.Path(tempfile.mkdtemp())
pdf_isolation._cache.clear()
text = extract_text_from_pdf(str(probe.statement_pdf(work / "statement.pdf", 20)))
assert text.strategy_used != "failed", (text.strategy_used, text.warnings)
assert text.page_count == 20 and "refusal" not in text.metadata, text.metadata
print("text statement: strategy", text.strategy_used, "pages", text.page_count)
pdf_isolation._cache.clear()
scan = extract_text_from_pdf(str(probe.scanned_pdf(work / "scan.pdf", 2)))
assert scan.strategy_used == "tesseract", (scan.strategy_used, scan.warnings, scan.metadata)
assert scan.page_count == 2 and "refusal" not in scan.metadata and "pages_unread" not in scan.metadata, scan.metadata
assert "HAVALE" in scan.text.upper(), scan.text[:200]
print("scanned statement: OCR ok, pages", scan.page_count)
PY
  ok "parser child runs under the container limit: text PDF and OCR (tur+eng) path"
}

phase_workers() {
  local i out
  # Both ARQ workers' health keys (and Redis) as the API reports them.
  for i in $(seq 1 24); do
    curl -fsS --max-time 15 "${API_URL}/api/v1/ready" -o "$SCRATCH/ready.json" || true
    [[ "$(jq -r '.data.checks.worker' "$SCRATCH/ready.json" 2>/dev/null)" == ok ]] && break
    sleep 5
  done
  [[ "$(jq -r '.data.checks.worker' "$SCRATCH/ready.json")" == ok ]] || { cat "$SCRATCH/ready.json"; bad "/api/v1/ready does not see both workers"; }
  ok "/api/v1/ready sees the analysis worker and the maintenance worker"
  dc ps worker worker-maintenance
  # A real job through the real queue: the maintenance worker's usage-prune task is a no-op on an empty database.
  dc exec -T backend python - <<'PY'
import asyncio

from arq import create_pool
from arq.connections import RedisSettings

from app.config import get_settings


async def main() -> None:
    s = get_settings()
    pool = await create_pool(RedisSettings.from_dsn(s.redis_url))
    job = await pool.enqueue_job("run_usage_prune_maintenance", _queue_name=s.arq_maintenance_queue_name)
    assert job is not None
    result = await job.result(timeout=60)
    assert result["ok"] is True, result
    print("maintenance job result:", result)


asyncio.run(main())
PY
  ok "a job enqueued by the API side is completed by the maintenance worker"
  local worker_logs backend_logs maint_logs
  worker_logs="$(dc logs worker 2>&1)" backend_logs="$(dc logs backend 2>&1)" maint_logs="$(dc logs worker-maintenance 2>&1)"
  grep -q 'CFO Scheduler started' <<<"$worker_logs" || bad "worker log has no 'CFO Scheduler started'"
  grep -qi 'scheduler not started' <<<"$backend_logs" || bad "backend log has no 'Scheduler not started ... owned by worker'"
  if grep -q 'CFO Scheduler started' <<<"$maint_logs"; then bad "the maintenance worker started the scheduler"; fi
  ok "the scheduler runs in the worker only"
}

phase_smoke() {
  ./scripts/smoke-test.sh --api "${API_URL}" --app "${APP_URL}" --expect-commit "$(env_value IMAGE_TAG)"
}

phase_onboarding() {
  local out token body password reg status
  # The first operator, as the runbook says: on the host, inside the container.
  out="$(dc exec -T backend python scripts/issue_pilot_invite.py --email "$OWNER_EMAIL" --company "$COMPANY")"
  echo "$out"
  grep -q '^Invitation pi-' <<<"$out" || bad "issue_pilot_invite.py did not queue an invitation"
  # No SMTP server in CI: the documented behaviour is a row that is retried (and fails after MAX_ATTEMPTS), never a crash.
  local row
  row="$(psql_q "select status || '|' || attempts || '|' || coalesce(last_error,'') from outbox_messages where kind='pilot_invite' and recipient='${OWNER_EMAIL}'")"
  echo "outbox row: $row"
  [[ "$row" == pending\|[1-9]\|?* || "$row" == failed\|* ]] || bad "pilot invite outbox row is '$row' (want pending|1|<reason> or failed|..)"
  ok "mail cannot leave in CI; the outbox row records the failure and retries: $row"
  # Registration is invite-only: the same call without the token is refused.
  status="$(curl -sS -o /dev/null -w '%{http_code}' -X POST "${API_URL}/api/v1/auth/register" -H 'Content-Type: application/json' \
    -d '{"email":"stranger@yenisirket-ci.com","password":"Stranger-pass-123"}')"
  [[ "$status" == 403 ]] || bad "register without an invite answered $status (want 403)"
  ok "register without an invite: 403"
  # The link is only in the (mail) body: in CI that is the outbox row, because the mail could not leave.
  body="$(psql_q "select body from outbox_messages where kind='pilot_invite' and recipient='${OWNER_EMAIL}'")"
  token="$(sed -n 's/.*token=\([A-Za-z0-9_-]*\).*/\1/p' <<<"$body" | head -n1)"
  [[ -n "$token" ]] || bad "no invitation token in the outbox row"
  printf '::add-mask::%s\n' "$token"
  password="Ci-$(openssl rand -hex 10)"
  printf '::add-mask::%s\n' "$password"
  reg="$(curl -sS -w '\n%{http_code}' -X POST "${API_URL}/api/v1/auth/register" -H 'Content-Type: application/json' \
    -d "{\"email\":\"${OWNER_EMAIL}\",\"password\":\"${password}\",\"full_name\":\"CI Owner\",\"invite_token\":\"${token}\"}")"
  status="${reg##*$'\n'}"
  [[ "$status" == 201 ]] || bad "register with the invite answered $status"
  [[ "$(jq -r '.data.org_name' <<<"${reg%$'\n'*}")" == "$COMPANY" ]] || bad "the new company is not named after the invite"
  local access
  access="$(jq -r '.data.access_token' <<<"${reg%$'\n'*}")"
  printf '::add-mask::%s\n' "$access"
  curl -fsS "${API_URL}/api/v1/auth/me" -H "Authorization: Bearer ${access}" -o /dev/null || bad "the new owner's token does not work"
  ok "invite redeemed through the API: owner of '$COMPANY', signed in"
  [[ "$(psql_q "select count(*) from organizations where name='${COMPANY}'")" == 1 ]] || bad "the company is not in the database"
  # The invite is single use.
  status="$(curl -sS -o /dev/null -w '%{http_code}' -X POST "${API_URL}/api/v1/auth/register" -H 'Content-Type: application/json' \
    -d "{\"email\":\"${OWNER_EMAIL}\",\"password\":\"${password}\",\"invite_token\":\"${token}\"}")"
  [[ "$status" != 201 ]] || bad "the invite could be used twice"
  ok "company is in the database; a second use of the invite is refused ($status)"
  # Nothing crashed: the API still answers, the readiness has no required failure.
  curl -fsS "${API_URL}/api/v1/ready" | jq -e '.data.status != "not_ready"' >/dev/null || bad "/ready is not_ready after onboarding"
}

phase_backup() {
  # A file in the uploads volume, so the archive has something to restore.
  dc exec -T backend sh -c 'mkdir -p /app/uploads/ci && echo ci-upload > /app/uploads/ci/hello.txt'
  # The scheduler assertion (phase `scheduler`) starts from a missing heartbeat: only the scheduler (or a mail kick)
  # writes it again.
  dc exec -T redis redis-cli DEL ops:heartbeat:outbox_pass >/dev/null
  ./scripts/backup.sh
  local archive
  archive="$(find "$SCRATCH/remote" -maxdepth 1 -name 'aicfo-*.tar.age' | head -n1)"
  [[ -n "$archive" && -s "$archive" ]] || bad "no encrypted archive at the backup destination"
  [[ -s "$SCRATCH/backups/last-success" ]] || bad "backup.sh wrote no last-success marker"
  head -c 200 "$archive" | grep -aq 'age-encryption.org' || bad "the archive is not age-encrypted"
  ok "backup.sh: encrypted archive $(basename "$archive") at the remote, last-success written"
}

phase_restore() {
  local log="$SCRATCH/drill.log"
  AGE_IDENTITY_FILE="$SCRATCH/age.key" ./scripts/restore-drill.sh 2>&1 | tee "$log"
  grep -q 'RESULT: OK' "$log" || bad "restore drill did not end RESULT: OK"
  grep -Eq '^ +organizations +[1-9][0-9]* +[1-9][0-9]* *$' "$log" || bad "restored database has no organizations"
  grep -Eq '^ +users +[1-9][0-9]* +[1-9][0-9]* *$' "$log" || bad "restored database has no users"
  grep -q 'uploads: 1 files' "$log" || bad "the uploaded file did not come back"
  ok "restore drill OK: restored database holds the pilot company and its owner, uploads restored"
}

phase_scheduler() {
  local i value
  for i in $(seq 1 75); do
    value="$(dc exec -T redis redis-cli GET ops:heartbeat:outbox_pass | tr -d '\r')"
    if [[ -n "$value" ]]; then
      ok "the scheduler's outbox pass wrote its heartbeat again after ${i} polls"
      curl -fsS "${API_URL}/api/v1/ready" | jq -e '.data.checks.scheduler == "ok"' >/dev/null || bad "/ready scheduler check is not ok"
      ok "/api/v1/ready scheduler check ok"
      return
    fi
    sleep 5
  done
  dc logs --tail=80 worker || true
  bad "no scheduler heartbeat within 6 minutes (the outbox pass runs every 5 minutes)"
}

phase="${1:-}"
case "$phase" in
  env|tls|migrations|preflight|edge|memory|parser|workers|smoke|onboarding|backup|restore|scheduler) "phase_$phase" ;;
  *) echo "usage: $0 env|tls|migrations|preflight|edge|memory|parser|workers|smoke|onboarding|backup|restore|scheduler" >&2; exit 2 ;;
esac
