#!/usr/bin/env bash
# =============================================================================
# load-baseline.sh — Lightweight load baseline for ops endpoints (no Locust required)
#
# Usage:
#   BACKEND_URL=http://localhost:8000 ./scripts/load-baseline.sh
#
# Env:
#   LOAD_REQUESTS=50       total requests (default 50)
#   LOAD_CONCURRENCY=10    parallel workers (default 10)
#   LOAD_P95_MS=800        fail if p95 latency exceeds this (default 800ms)
#
# Exit 0 = baseline within threshold
# =============================================================================
set -euo pipefail

# Detect a working python. On Windows `python3` is often the Microsoft Store
# stub that errors out, so try `python` first and verify it actually runs.
_PY_BIN=""
for _c in python "$_PY_BIN" py; do
  if command -v "$_c" >/dev/null 2>&1 && "$_c" -c "import sys" >/dev/null 2>&1; then
    _PY_BIN="$_c"; break
  fi
done
if [[ -z "$_PY_BIN" ]]; then
  echo "No working python interpreter found (tried python, python3, py)." >&2
  exit 1
fi

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
OK()   { echo -e "${GREEN}✓${NC} $*"; }
FAIL() { echo -e "${RED}✗${NC} $*"; }
INFO() { echo -e "${CYAN}→${NC} $*"; }
WARN() { echo -e "${YELLOW}⚠${NC} $*"; }

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
API_PREFIX="${API_PREFIX:-/api/v1}"
TARGET="${BACKEND_URL}${API_PREFIX}/system/ops"
LOAD_REQUESTS="${LOAD_REQUESTS:-50}"
LOAD_CONCURRENCY="${LOAD_CONCURRENCY:-10}"
LOAD_P95_MS="${LOAD_P95_MS:-800}"

TMPDIR="${TMPDIR:-/tmp}"
LATENCY_FILE=$(mktemp "${TMPDIR}/load-baseline.XXXXXX")
trap 'rm -f "$LATENCY_FILE"' EXIT

single_request() {
  local start_ms end_ms elapsed
  start_ms=$(date +%s%3N 2>/dev/null || "$_PY_BIN" -c 'import time; print(int(time.time()*1000))')
  if curl -sf --max-time 10 "$TARGET" > /dev/null; then
    end_ms=$(date +%s%3N 2>/dev/null || "$_PY_BIN" -c 'import time; print(int(time.time()*1000))')
    elapsed=$((end_ms - start_ms))
    echo "$elapsed" >> "$LATENCY_FILE"
  else
    echo "-1" >> "$LATENCY_FILE"
  fi
}

export -f single_request
export TARGET LATENCY_FILE

INFO "Load baseline: $LOAD_REQUESTS requests, concurrency=$LOAD_CONCURRENCY → $TARGET"

seq 1 "$LOAD_REQUESTS" | xargs -P "$LOAD_CONCURRENCY" -I{} bash -c 'single_request' || true

if [[ ! -s "$LATENCY_FILE" ]]; then
  FAIL "No latency samples collected"
  exit 1
fi

# Compute stats with python (portable)
read -r TOTAL OK_COUNT FAIL_COUNT P50 P95 MAX <<< "$(
"$_PY_BIN" - "$LATENCY_FILE" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
samples = [int(x) for x in path.read_text().splitlines() if x.strip()]
ok = [x for x in samples if x >= 0]
fail = len(samples) - len(ok)
if not ok:
    print(len(samples), 0, fail, 0, 0, 0)
    sys.exit(0)
ok.sort()

def pct(p: float) -> int:
    k = max(0, min(len(ok) - 1, int(round((p / 100) * (len(ok) - 1)))))
    return ok[k]

print(len(samples), len(ok), fail, pct(50), pct(95), ok[-1])
PY
)"

echo ""
INFO "Results: total=$TOTAL ok=$OK_COUNT fail=$FAIL_COUNT p50=${P50}ms p95=${P95}ms max=${MAX}ms"

if [[ "$OK_COUNT" -eq 0 ]]; then
  FAIL "All requests failed"
  exit 1
fi

if [[ "$P95" -gt "$LOAD_P95_MS" ]]; then
  FAIL "p95 ${P95}ms exceeds threshold ${LOAD_P95_MS}ms"
  exit 1
fi

OK "Load baseline passed (p95=${P95}ms ≤ ${LOAD_P95_MS}ms)"
exit 0
