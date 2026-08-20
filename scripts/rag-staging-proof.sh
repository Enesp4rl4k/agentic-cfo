#!/usr/bin/env bash
# RAG / pgvector staging proof — structural + optional live checks
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
OK()   { echo -e "${GREEN}✓${NC} $*"; }
FAIL() { echo -e "${RED}✗${NC} $*"; }
INFO() { echo -e "${CYAN}→${NC} $*"; }

FAILURES=0

check_file() {
  local name="$1" path="$2"
  if [[ -f "$path" ]]; then OK "$name"; else FAIL "$name missing: $path"; FAILURES=$((FAILURES+1)); fi
}

check_grep() {
  local name="$1" pattern="$2" path="$3"
  if grep -q "$pattern" "$path"; then OK "$name"; else FAIL "$name"; FAILURES=$((FAILURES+1)); fi
}

echo ""
echo -e "${CYAN}  RAG STAGING PROOF${NC}"
echo ""

check_file "migration 023" "backend/alembic/versions/023_rag_embeddings.py"
check_grep "pgvector dependency" "pgvector" "backend/requirements.txt"
check_grep "EmbeddingRagRetriever" "class EmbeddingRagRetriever" "backend/app/services/rag/retriever.py"
check_grep "index writes embedding" "embedding=" "backend/app/services/rag_service.py"
check_grep "conductor_plan metadata" "conductor_plan" "backend/app/worker.py"
check_grep "chat retriever version" "evidence_retriever_version" "backend/app/api/chat.py"
check_grep "grounding validator" "validate_grounding" "backend/app/api/chat.py"

if [[ -n "${BACKEND_URL:-}" ]]; then
  INFO "Live checks against $BACKEND_URL"
  if curl -sf --max-time 10 "$BACKEND_URL/api/v1/system/health" | grep -q schema_version; then
    OK "system/health live"
  else
    FAIL "system/health live"
    FAILURES=$((FAILURES+1))
  fi
else
  INFO "BACKEND_URL not set — skipping live RAG checks"
fi

echo ""
if [[ $FAILURES -eq 0 ]]; then
  echo -e "${GREEN}  ✓ RAG STAGING PROOF PASSED${NC}\n"
  exit 0
else
  echo -e "${RED}  ✗ RAG STAGING PROOF FAILED ($FAILURES)${NC}\n"
  exit 1
fi
