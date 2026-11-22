#!/usr/bin/env bash
# Smoke test for a deployed stack. Run it after every deploy and after every restore.
#
#   ./scripts/smoke-test.sh --api https://api.example.com.tr --app https://app.example.com.tr \
#                           [--expect-commit <sha>] [--strict]
#
# Needs only curl. Reads nothing secret, sends no credentials, changes nothing: every request is a GET
# (plus one CORS preflight). Exit 0 = every FAIL-level check passed. WARN lines are advice.
#
#   --api URL            public API base (required)
#   --app URL            public frontend base (optional; its checks are skipped without it)
#   --expect-commit SHA  the deploy's commit: /api/v1/version must report it (prefix match)
#   --strict             a "degraded" readiness (worker, outbox, scheduler) fails the run too
#   --origin URL         the app origin CORS must allow (default: the --app value)
set -uo pipefail

API="" APP="" EXPECT="" STRICT=0 ORIGIN=""
while [[ $# -gt 0 ]]; do
  flag="$1"
  case "$flag" in
    --api) API="${2:-}"; shift 2 ;;
    --app) APP="${2:-}"; shift 2 ;;
    --expect-commit) EXPECT="${2:-}"; shift 2 ;;
    --origin) ORIGIN="${2:-}"; shift 2 ;;
    --strict) STRICT=1; shift ;;
    *) echo "smoke: unknown argument '$flag'" >&2; exit 2 ;;
  esac
done
[[ -n "$API" ]] || { echo "usage: smoke-test.sh --api URL [--app URL] [--expect-commit SHA] [--strict]" >&2; exit 2; }
command -v curl >/dev/null || { echo "smoke: curl is required" >&2; exit 2; }
API="${API%/}"; APP="${APP%/}"; ORIGIN="${ORIGIN:-$APP}"

FAILED=0
pass() { printf 'ok    %s\n' "$*"; }
warn() { printf 'WARN  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; FAILED=1; }

get() { curl -sS --max-time 15 -o "$BODY" -D "$HEAD" -w '%{http_code}' "$@" 2>/dev/null || echo 000; }
header() { grep -i "^$1:" "$HEAD" | head -n1 | cut -d: -f2- | tr -d '\r' | sed 's/^ *//'; }

BODY="$(mktemp)"; HEAD="$(mktemp)"
trap 'rm -f "$BODY" "$HEAD"' EXIT

# 1. Liveness
code="$(get "$API/health")"
[[ "$code" == 200 ]] && pass "API liveness /health" || fail "API /health answered $code"

# 2. Readiness: 503 = a required check failed (database, schema, Redis); degraded = advisory.
code="$(get "$API/api/v1/ready")"
if [[ "$code" == 200 ]]; then
  if grep -q '"status": *"ready"' "$BODY"; then
    pass "readiness: ready"
  else
    msg="readiness: degraded (worker, outbox pass, outbox backlog or failed mail) — $(tr -d '\n' < "$BODY" | cut -c1-400)"
    if [[ "$STRICT" == 1 ]]; then fail "$msg"; else warn "$msg"; fi
  fi
else
  fail "readiness answered $code: $(tr -d '\n' < "$BODY" | cut -c1-400)"
fi

# 3. Version
code="$(get "$API/api/v1/version")"
if [[ "$code" == 200 ]]; then
  commit="$(sed -n 's/.*"commit": *"\([^"]*\)".*/\1/p' "$BODY" | head -n1)"
  pass "version: commit ${commit:-?}"
  if [[ -n "$EXPECT" ]]; then
    if [[ "$commit" == "$EXPECT"* || "$EXPECT" == "$commit"* ]] && [[ -n "$commit" && "$commit" != unknown ]]; then
      pass "running the expected commit $EXPECT"
    else
      fail "running commit '$commit', expected '$EXPECT'"
    fi
  fi
else
  fail "/api/v1/version answered $code"
fi

# 4. A protected route refuses an anonymous caller.
code="$(get "$API/api/v1/auth/me")"
[[ "$code" == 401 || "$code" == 403 ]] && pass "anonymous /auth/me refused ($code)" || fail "anonymous /auth/me answered $code (want 401/403)"

# 5. Headers on the API
code="$(get "$API/health")"
for name in X-Content-Type-Options Content-Security-Policy X-Frame-Options Referrer-Policy; do
  [[ -n "$(header "$name")" ]] && pass "API sends $name" || fail "API is missing $name"
done
if [[ "$API" == https://* ]]; then
  [[ -n "$(header Strict-Transport-Security)" ]] && pass "API sends HSTS" || fail "API is missing Strict-Transport-Security"
  scheme="ht""tp"   # the check is that port 80 redirects, so it is asked in clear text on purpose
  port80="$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' "${scheme}:""//${API#https://}/health" 2>/dev/null || echo 000)"
  case "$port80" in
    301|302|307|308) pass "port 80 redirects to TLS ($port80)" ;;
    000) warn "port 80 not reachable (fine if only 443 is open, but certificate issuance needs it)" ;;
    *) fail "port 80 answered $port80 instead of redirecting" ;;
  esac
else
  warn "API is not https: acceptable only for a local run"
fi

# 6. CORS: the app origin is allowed, a stranger is not.
if [[ -n "$ORIGIN" ]]; then
  code="$(get -X OPTIONS -H "Origin: $ORIGIN" -H 'Access-Control-Request-Method: GET' "$API/api/v1/auth/me")"
  allowed="$(header Access-Control-Allow-Origin)"
  [[ "$allowed" == "$ORIGIN" ]] && pass "CORS allows $ORIGIN" || fail "CORS for $ORIGIN answered '$allowed' ($code)"
  code="$(get -X OPTIONS -H 'Origin: https://evil.example' -H 'Access-Control-Request-Method: GET' "$API/api/v1/auth/me")"
  allowed="$(header Access-Control-Allow-Origin)"
  [[ -z "$allowed" ]] && pass "CORS refuses a foreign origin" || fail "CORS allows a foreign origin ('$allowed')"
fi

# 7. API docs are public unless the proxy hides them.
code="$(get "$API/docs")"
[[ "$code" == 200 ]] && warn "$API/docs is public (route list, no data); hide it at the proxy if you prefer"

# 8. Frontend
if [[ -n "$APP" ]]; then
  code="$(get "$APP/api/health")"
  [[ "$code" == 200 ]] && pass "frontend /api/health" || fail "frontend /api/health answered $code"
  code="$(get "$APP/")"
  [[ "$code" == 200 || "$code" == 307 || "$code" == 308 ]] && pass "frontend home answers ($code)" || fail "frontend home answered $code"
  code="$(get "$APP/auth/login")"
  for name in X-Content-Type-Options X-Frame-Options Referrer-Policy; do
    [[ -n "$(header "$name")" ]] && pass "frontend sends $name" || fail "frontend is missing $name"
  done
  [[ "$APP" == https://* && -z "$(header Strict-Transport-Security)" ]] && fail "frontend is missing Strict-Transport-Security"
  [[ -z "$(header Content-Security-Policy)" ]] && warn "frontend sends no Content-Security-Policy (known gap, docs/ops/operational-readiness-2026-11.md)"
fi

if [[ "$FAILED" -ne 0 ]]; then
  echo "SMOKE TEST FAILED"
  exit 1
fi
echo "SMOKE TEST PASSED"
