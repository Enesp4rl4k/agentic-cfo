#!/usr/bin/env bash
# =============================================================================
# tr-governance-e2e.sh — the institutionalisation story, end to end.
#
#   register -> create workspace -> enable TR pack -> upload -> analysis
#     -> THP double-entry journal -> SMMM approves every entry
#     -> hash-sealed defensibility packet (+ PDF)
#     -> delegation-of-authority policy
#     -> institutionalisation index rises
#
# The point is the last check: the score is computed from real platform
# activity, so it can only move if every step above actually did something. A
# run where the journal silently produced nothing scores E and stays there.
#
# Usage:
#   BACKEND_URL=http://localhost:8000 ./scripts/tr-governance-e2e.sh
#
# Optional:
#   TR_EMAIL / TR_PASSWORD  — reuse an existing account instead of registering
#   POLL_TIMEOUT_SEC=300    — max wait for the CFO analysis
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# On Windows `python3` is usually the Microsoft Store stub, which errors out.
# Try `python` first and verify the interpreter actually runs.
_PY_BIN=""
for _c in python python3 py; do
  if command -v "$_c" >/dev/null 2>&1 && "$_c" -c "import sys" >/dev/null 2>&1; then
    _PY_BIN="$_c"; break
  fi
done
if [[ -z "$_PY_BIN" ]]; then
  echo "No working python interpreter found (tried python, python3, py)." >&2
  exit 1
fi

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
OK()   { echo -e "${GREEN}OK${NC}   $*"; }
FAIL() { echo -e "${RED}FAIL${NC} $*"; }
INFO() { echo -e "${CYAN}->${NC}   $*"; }
WARN() { echo -e "${YELLOW}WARN${NC} $*"; }

BACKEND_URL="${BACKEND_URL:-}"
API="${BACKEND_URL%/}/api/v1"
POLL_TIMEOUT_SEC="${POLL_TIMEOUT_SEC:-300}"
CSV_FILE="${CSV_FILE:-$ROOT/scripts/fixtures/golden_path_sample_en_usd.csv}"
POLICY_FILE="$ROOT/scripts/fixtures/authority_policy_default.json"
FAILURES=0

if [[ -z "$BACKEND_URL" ]]; then
  FAIL "BACKEND_URL is required"
  exit 1
fi
if [[ ! -f "$CSV_FILE" ]]; then
  FAIL "Fixture not found: $CSV_FILE"
  exit 1
fi

# Native curl under Git Bash cannot open a POSIX path for -F @file.
CSV_FOR_CURL="$CSV_FILE"
POLICY_FOR_CURL="$POLICY_FILE"
if command -v cygpath >/dev/null 2>&1; then
  CSV_FOR_CURL="$(cygpath -w "$CSV_FILE")"
  POLICY_FOR_CURL="$(cygpath -w "$POLICY_FILE")"
fi

# Read one field out of a JSON response on stdin. Kept as a function so the
# python program is passed with -c: `python - <<PY` would make the heredoc
# stdin, and json.load(sys.stdin) would always read empty.
jqp() { "$_PY_BIN" -c "$1"; }

# ── Account ───────────────────────────────────────────────────────────────────
TR_EMAIL="${TR_EMAIL:-tr-gov-$$@example.com}"
TR_PASSWORD="${TR_PASSWORD:-TrGov1234!x}"

INFO "Registering $TR_EMAIL"
curl -s -X POST "$API/auth/register" -H "Content-Type: application/json" \
  -d "{\"email\":\"$TR_EMAIL\",\"password\":\"$TR_PASSWORD\",\"full_name\":\"TR Governance E2E\"}" \
  >/dev/null || true

login() {
  curl -s -X POST "$API/auth/login" -H "Content-Type: application/json" \
    -d "{\"email\":\"$TR_EMAIL\",\"password\":\"$TR_PASSWORD\"}" \
  | jqp 'import sys,json;print((json.load(sys.stdin).get("data") or {}).get("access_token",""))'
}

TOKEN="$(login)"
if [[ -z "$TOKEN" ]]; then
  FAIL "login failed for $TR_EMAIL"
  exit 1
fi
AUTH=(-H "Authorization: Bearer $TOKEN")
OK "authenticated"

# ── Workspace + TR pack ───────────────────────────────────────────────────────
# Registration does not create an organization, and every TR route is gated on
# one, so without these two calls the whole vertical answers 400.
INFO "POST /org/create"
SLUG=$(curl -s -X POST "$API/org/create" "${AUTH[@]}" -H "Content-Type: application/json" \
  -d '{"name":"Demir Aile Sirketi"}' \
  | jqp 'import sys,json;print((json.load(sys.stdin).get("data") or {}).get("slug",""))')
if [[ -n "$SLUG" ]]; then
  OK "workspace created ($SLUG)"
else
  WARN "workspace not created (already a member?)"
fi

# Creating the org promotes the caller to owner — re-login so the JWT says so.
TOKEN="$(login)"
AUTH=(-H "Authorization: Bearer $TOKEN")

INFO "PATCH /org/me — enable the Turkey pack"
PACKS=$(curl -s -X PATCH "$API/org/me" "${AUTH[@]}" -H "Content-Type: application/json" \
  -d '{"country_code":"TR","base_currency":"TRY","locale":"tr-TR","regional_packs":["tr"]}' \
  | jqp 'import sys,json;print(",".join((json.load(sys.stdin).get("data") or {}).get("regional_packs") or []))')
if [[ "$PACKS" == *tr* ]]; then
  OK "TR pack enabled"
else
  FAIL "TR pack not enabled (got: '$PACKS')"
  FAILURES=$((FAILURES+1))
fi

# ── Baseline index ────────────────────────────────────────────────────────────
score_now() {
  curl -s -X POST "$API/institutionalization/compute" "${AUTH[@]}" \
    -H "Content-Type: application/json" -d '{}' \
  | jqp 'import sys,json;print((json.load(sys.stdin).get("data") or {}).get("overall_score") or 0)'
}

BASELINE=$(score_now)
INFO "Institutionalisation baseline: $BASELINE"

# ── Upload + analysis ─────────────────────────────────────────────────────────
INFO "POST /upload"
JOB_ID=$(curl -s -X POST "$API/upload" "${AUTH[@]}" -F "file=@${CSV_FOR_CURL}" \
  | jqp 'import sys,json;print((json.load(sys.stdin).get("data") or {}).get("job_id",""))')
if [[ -z "$JOB_ID" ]]; then
  FAIL "upload returned no job_id"
  exit 1
fi
OK "uploaded job_id=$JOB_ID"

INFO "Polling GET /analysis/$JOB_ID (timeout=${POLL_TIMEOUT_SEC}s)"
DEADLINE=$(( $(date +%s) + POLL_TIMEOUT_SEC ))
while true; do
  if [[ $(date +%s) -gt $DEADLINE ]]; then
    FAIL "analysis poll timed out"
    exit 1
  fi
  STATUS=$(curl -s "$API/analysis/$JOB_ID" "${AUTH[@]}" \
    | jqp 'import sys,json;print((json.load(sys.stdin).get("data") or {}).get("status",""))' || true)
  [[ "$STATUS" == "completed" ]] && break
  if [[ "$STATUS" == "failed" ]]; then
    FAIL "analysis failed"
    exit 1
  fi
  sleep 5
done
OK "analysis completed"

# ── THP journal ───────────────────────────────────────────────────────────────
INFO "POST /muhasebe/analiz"
MUH=$(curl -s -X POST "$API/muhasebe/analiz" "${AUTH[@]}" -H "Content-Type: application/json" \
  -d "{\"job_id\":\"$JOB_ID\"}")
ENTRIES=$(echo "$MUH" | jqp 'import sys,json;print((json.load(sys.stdin).get("data") or {}).get("kayit_sayisi") or 0)')
BALANCED=$(echo "$MUH" | jqp 'import sys,json;print((json.load(sys.stdin).get("data") or {}).get("dengeli"))')
if [[ "${ENTRIES:-0}" -gt 0 && "$BALANCED" == "True" ]]; then
  OK "journal: $ENTRIES entries, trial balance balanced"
else
  FAIL "journal empty or unbalanced (entries=$ENTRIES balanced=$BALANCED)"
  FAILURES=$((FAILURES+1))
fi

# ── SMMM approval ─────────────────────────────────────────────────────────────
INFO "GET /smmm/onay/queue/$JOB_ID"
KAYIT_IDS=$(curl -s "$API/smmm/onay/queue/$JOB_ID" "${AUTH[@]}" \
  | jqp 'import sys,json;print(" ".join(k["id"] for k in (json.load(sys.stdin).get("data") or {}).get("kayitlar") or []))')
APPROVED=0
for kid in $KAYIT_IDS; do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/smmm/onay/$kid/onayla" \
    "${AUTH[@]}" -H "Content-Type: application/json" -d '{}')
  [[ "$CODE" == "200" ]] && APPROVED=$((APPROVED+1))
done
PENDING=$(curl -s "$API/smmm/onay/queue/$JOB_ID" "${AUTH[@]}" \
  | jqp 'import sys,json;print((json.load(sys.stdin).get("data") or {}).get("bekleyen") or 0)')
if [[ "$APPROVED" -gt 0 && "$PENDING" == "0" ]]; then
  OK "SMMM approved $APPROVED entries, queue empty"
else
  FAIL "approval incomplete (approved=$APPROVED pending=$PENDING)"
  FAILURES=$((FAILURES+1))
fi

# ── Defensibility packet ──────────────────────────────────────────────────────
INFO "POST /smmm/defensibility/$JOB_ID/build"
PACKET_ID=$(curl -s -X POST "$API/smmm/defensibility/$JOB_ID/build" "${AUTH[@]}" \
  -H "Content-Type: application/json" -d '{}' \
  | jqp 'import sys,json;print((json.load(sys.stdin).get("data") or {}).get("id",""))')
if [[ -z "$PACKET_ID" ]]; then
  FAIL "packet build returned no id"
  FAILURES=$((FAILURES+1))
else
  SEALED=$(curl -s -X POST "$API/smmm/defensibility/$PACKET_ID/finalize" "${AUTH[@]}" \
    -H "Content-Type: application/json" \
    -d '{"statement":"Donem kayitlari SMMM tarafindan incelenmis ve onaylanmistir."}' \
    | jqp 'import sys,json;d=(json.load(sys.stdin).get("data") or {});print((d.get("status") or "-")+" "+(d.get("content_hash") or "-")[:16])')
  if [[ "$SEALED" == finalized* ]]; then
    OK "packet sealed (hash ${SEALED#finalized })"
  else
    FAIL "packet not finalized ($SEALED)"
    FAILURES=$((FAILURES+1))
  fi

  PDF_CODE=$(curl -s -o /dev/null -w '%{http_code}:%{size_download}' \
    "$API/smmm/defensibility/$PACKET_ID/export" "${AUTH[@]}")
  if [[ "${PDF_CODE%%:*}" == "200" && "${PDF_CODE##*:}" -gt 500 ]]; then
    OK "packet PDF exported (${PDF_CODE##*:} bytes)"
  else
    FAIL "packet PDF export failed ($PDF_CODE)"
    FAILURES=$((FAILURES+1))
  fi
fi

# ── Delegation of authority ───────────────────────────────────────────────────
INFO "PUT /authority/policy"
if [[ -f "$POLICY_FILE" ]]; then
  PV=$(curl -s -X PUT "$API/authority/policy" "${AUTH[@]}" -H "Content-Type: application/json" \
    --data-binary "@$POLICY_FOR_CURL" \
    | jqp 'import sys,json;print((json.load(sys.stdin).get("data") or {}).get("version") or 0)')
  if [[ "${PV:-0}" -ge 1 ]]; then
    OK "authority policy v$PV active"
  else
    FAIL "authority policy not stored"
    FAILURES=$((FAILURES+1))
  fi
else
  FAIL "policy fixture missing: $POLICY_FILE"
  FAILURES=$((FAILURES+1))
fi

# ── The index has to have moved ───────────────────────────────────────────────
FINAL=$(score_now)
INFO "Institutionalisation: $BASELINE -> $FINAL"
if [[ "${FINAL:-0}" -gt "${BASELINE:-0}" ]]; then
  OK "index rose from real activity ($BASELINE -> $FINAL)"
else
  FAIL "index did not move ($BASELINE -> $FINAL) — a step above had no effect"
  FAILURES=$((FAILURES+1))
fi

echo ""
if [[ $FAILURES -eq 0 ]]; then
  echo -e "${GREEN}  TR GOVERNANCE E2E PASSED (${BASELINE} -> ${FINAL})${NC}\n"
  exit 0
else
  echo -e "${RED}  TR GOVERNANCE E2E FAILED ($FAILURES)${NC}\n"
  exit 1
fi
