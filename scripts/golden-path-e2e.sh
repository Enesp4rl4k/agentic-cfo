#!/usr/bin/env bash
# =============================================================================
# golden-path-e2e.sh — Upload → analysis poll → CEO deck → ops health
#
# Usage:
#   BACKEND_URL=http://localhost:8000 AUTH_TOKEN=<jwt> ./scripts/golden-path-e2e.sh
#
# Optional:
#   GOLDEN_EMAIL / GOLDEN_PASSWORD  — login if AUTH_TOKEN unset
#   POLL_TIMEOUT_SEC=300            — max wait for analysis (default 300)
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
OK()   { echo -e "${GREEN}✓${NC} $*"; }
FAIL() { echo -e "${RED}✗${NC} $*"; }
INFO() { echo -e "${CYAN}→${NC} $*"; }
WARN() { echo -e "${YELLOW}⚠${NC} $*"; }

BACKEND_URL="${BACKEND_URL:-}"
API="${BACKEND_URL%/}/api/v1"
POLL_TIMEOUT_SEC="${POLL_TIMEOUT_SEC:-300}"
CSV_FILE="${CSV_FILE:-$ROOT/scripts/fixtures/golden_path_sample_en_usd.csv}"
P95_TARGET_SEC="${P95_TARGET_SEC:-120}"
FAILURES=0

if [[ -z "$BACKEND_URL" ]]; then
  FAIL "BACKEND_URL is required"
  exit 1
fi

if [[ ! -f "$CSV_FILE" ]]; then
  # Fallback to legacy TR fixture if EN missing
  CSV_FILE="$ROOT/scripts/fixtures/golden_path_sample.csv"
fi

if [[ ! -f "$CSV_FILE" ]]; then
  FAIL "Sample CSV missing"
  exit 1
fi

INFO "Using fixture: $CSV_FILE"

# ── Auth ──────────────────────────────────────────────────────────────────────
if [[ -z "${AUTH_TOKEN:-}" ]]; then
  if [[ -n "${GOLDEN_EMAIL:-}" && -n "${GOLDEN_PASSWORD:-}" ]]; then
    INFO "Logging in as $GOLDEN_EMAIL"
    LOGIN_BODY=$(curl -sf --max-time 20 -X POST "$API/auth/login" \
      -H "Content-Type: application/json" \
      -d "{\"email\":\"$GOLDEN_EMAIL\",\"password\":\"$GOLDEN_PASSWORD\"}" || true)
    AUTH_TOKEN=$(echo "$LOGIN_BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token') or d.get('data',{}).get('access_token',''))" 2>/dev/null || true)
  fi
fi

if [[ -z "${AUTH_TOKEN:-}" ]]; then
  FAIL "AUTH_TOKEN (or GOLDEN_EMAIL+GOLDEN_PASSWORD) required"
  exit 1
fi

AUTH_HDR=( -H "Authorization: Bearer $AUTH_TOKEN" )
START_TS=$(date +%s)

# ── Health ────────────────────────────────────────────────────────────────────
INFO "GET /system/health"
if curl -sf --max-time 10 "${AUTH_HDR[@]}" "$API/system/health" | grep -q schema_version; then
  OK "system/health"
else
  # health may be unauthenticated
  if curl -sf --max-time 10 "$API/system/health" | grep -q schema_version; then
    OK "system/health (public)"
  else
    FAIL "system/health"
    FAILURES=$((FAILURES+1))
  fi
fi

# ── Upload ────────────────────────────────────────────────────────────────────
INFO "POST /upload"
UPLOAD_RESP=$(curl -sf --max-time 60 -X POST "$API/upload" \
  "${AUTH_HDR[@]}" \
  -F "file=@${CSV_FILE};type=text/csv" || true)

JOB_ID=$(echo "$UPLOAD_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('job_id') or d.get('job_id',''))" 2>/dev/null || true)

if [[ -z "$JOB_ID" ]]; then
  FAIL "upload did not return job_id — response: ${UPLOAD_RESP:0:200}"
  exit 1
fi
OK "uploaded job_id=$JOB_ID"

# ── Poll analysis ─────────────────────────────────────────────────────────────
INFO "Polling GET /analysis/$JOB_ID (timeout=${POLL_TIMEOUT_SEC}s)"
STATUS=""
DEADLINE=$((START_TS + POLL_TIMEOUT_SEC))
while true; do
  NOW=$(date +%s)
  if [[ $NOW -gt $DEADLINE ]]; then
    FAIL "analysis poll timed out (last status=$STATUS)"
    FAILURES=$((FAILURES+1))
    break
  fi
  RESP=$(curl -sf --max-time 15 "${AUTH_HDR[@]}" "$API/analysis/$JOB_ID" || true)
  STATUS=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print((d.get('data') or d).get('status',''))" 2>/dev/null || true)
  if [[ "$STATUS" == "completed" || "$STATUS" == "awaiting_review" ]]; then
    OK "analysis status=$STATUS"
    break
  fi
  if [[ "$STATUS" == "failed" ]]; then
    FAIL "analysis failed"
    FAILURES=$((FAILURES+1))
    break
  fi
  sleep 5
done

# ── CEO from job (board deck path) ────────────────────────────────────────────
INFO "POST /ceo/analyze-from-job/$JOB_ID"
CEO_RESP=$(curl -sf --max-time 180 -X POST "$API/ceo/analyze-from-job/$JOB_ID" \
  "${AUTH_HDR[@]}" \
  -H "Content-Type: application/json" \
  -d '{}' || true)

HAS_DECK=$(echo "$CEO_RESP" | python3 - <<'PY'
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    print("0"); raise SystemExit
data = d.get("data") or d
deck = data.get("board_deck") or (data.get("result") or {}).get("board_deck")
if deck:
    print("1")
else:
    # async path?
    jid = data.get("job_id") or ""
    print("async:"+jid if jid else "0")
PY
)

if [[ "$HAS_DECK" == "1" ]]; then
  OK "board deck present in CEO response"
elif [[ "$HAS_DECK" == async:* ]]; then
  CEO_JOB_ID="${HAS_DECK#async:}"
  INFO "Polling CEO async job $CEO_JOB_ID"
  CEO_DEADLINE=$(( $(date +%s) + POLL_TIMEOUT_SEC ))
  while true; do
    NOW=$(date +%s)
    if [[ $NOW -gt $CEO_DEADLINE ]]; then
      FAIL "CEO poll timed out"
      FAILURES=$((FAILURES+1))
      break
    fi
    CSTAT=$(curl -sf --max-time 15 "${AUTH_HDR[@]}" "$API/ceo/status/$CEO_JOB_ID" || true)
    CSTATUS=$(echo "$CSTAT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status') or (d.get('data') or {}).get('status',''))" 2>/dev/null || true)
    if [[ "$CSTATUS" == "completed" ]]; then
      DECK_OK=$(echo "$CSTAT" | python3 -c "import sys,json; d=json.load(sys.stdin); r=(d.get('result') or (d.get('data') or {}).get('result') or {}); print('1' if r.get('board_deck') else '0')" 2>/dev/null || true)
      if [[ "$DECK_OK" == "1" ]]; then
        OK "CEO board deck completed"
      else
        FAIL "CEO completed without board_deck"
        FAILURES=$((FAILURES+1))
      fi
      break
    fi
    if [[ "$CSTATUS" == "failed" ]]; then
      FAIL "CEO job failed"
      FAILURES=$((FAILURES+1))
      break
    fi
    sleep 5
  done
else
  WARN "CEO analyze-from-job did not return deck (may need worker); continuing"
  FAILURES=$((FAILURES+1))
fi

# ── Ops ───────────────────────────────────────────────────────────────────────
INFO "GET /system/ops"
if curl -sf --max-time 10 "$API/system/ops" | grep -q schema_version; then
  OK "system/ops"
else
  FAIL "system/ops"
  FAILURES=$((FAILURES+1))
fi

ELAPSED=$(( $(date +%s) - START_TS ))
INFO "Golden path elapsed: ${ELAPSED}s (SLA target P95 < ${P95_TARGET_SEC}s for deck path)"

if [[ "$ELAPSED" -gt "$P95_TARGET_SEC" ]]; then
  WARN "Elapsed ${ELAPSED}s exceeds SLA target ${P95_TARGET_SEC}s (non-fatal for CI; track P95 in staging)"
fi

echo ""
if [[ $FAILURES -eq 0 ]]; then
  echo -e "${GREEN}  ✓ GOLDEN PATH E2E PASSED (${ELAPSED}s)${NC}\n"
  exit 0
else
  echo -e "${RED}  ✗ GOLDEN PATH E2E FAILED ($FAILURES)${NC}\n"
  exit 1
fi
