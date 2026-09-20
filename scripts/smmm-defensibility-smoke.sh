#!/usr/bin/env bash
# SMMM Defensibility Packet (#4) smoke — structural check (no network)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FAIL=0
ok() { echo "✓ $1"; }
bad() { echo "✗ $1"; FAIL=1; }

test -f backend/app/models/defensibility_packet.py && ok "defensibility_packet model" || bad "model"
test -f backend/alembic/versions/029_defensibility_packet.py && ok "migration 029" || bad "migration 029"
test -f backend/app/services/smmm_defensibility.py && ok "assembly service" || bad "assembly service"
grep -q "async def build_packet" backend/app/services/smmm_defensibility.py && ok "build_packet" || bad "build_packet"
grep -q "async def finalize_packet" backend/app/services/smmm_defensibility.py && ok "finalize_packet" || bad "finalize_packet"
grep -q "def content_hash" backend/app/services/smmm_defensibility.py && ok "content_hash (tamper seal)" || bad "content_hash"
grep -q "ai_auto_posted\|human_approved\|human_corrected" backend/app/services/smmm_defensibility.py && ok "per-entry decision source" || bad "decision source"
grep -q "yevmiye_kayitlari" backend/app/api/muhasebe.py && ok "full journal persisted for packet" || bad "journal not persisted"
grep -q "to_full_dict" backend/app/agents/accounting/orchestrator.py && ok "MuhasebeSonucu.to_full_dict" || bad "to_full_dict"
grep -q '"/smmm/defensibility/{job_id}/build"' backend/app/api/smmm_defensibility.py && ok "build endpoint" || bad "build endpoint"
grep -q '"/smmm/defensibility/{packet_id}/finalize"' backend/app/api/smmm_defensibility.py && ok "finalize endpoint" || bad "finalize endpoint"
grep -q '"/smmm/defensibility/{packet_id}/export"' backend/app/api/smmm_defensibility.py && ok "export endpoint" || bad "export endpoint"
grep -q "require_tr_pack" backend/app/api/smmm_defensibility.py && ok "gated by TR pack" || bad "not TR-gated"
grep -q "app.api.smmm_defensibility" backend/app/api/registry.py && ok "router registered" || bad "router not registered"
test -f frontend/src/lib/api/smmm.ts && ok "frontend api lib" || bad "frontend lib"
test -f frontend/src/components/smmm/DefensibilityPacketCard.tsx && ok "DefensibilityPacketCard component" || bad "component"
grep -q "DefensibilityPacketCard" "frontend/src/app/(dashboard)/tr-vertical/page.tsx" && ok "mounted on /tr-vertical" || bad "not mounted"

( cd backend && python -c "from app.services.smmm_defensibility import build_packet, finalize_packet, content_hash; from app.models.defensibility_packet import DefensibilityPacket; print('imports ok')" ) \
  && ok "service import" || bad "service import"

if [[ $FAIL -eq 0 ]]; then
  echo "✓ SMMM DEFENSIBILITY SMOKE PASSED"
  exit 0
else
  echo "✗ SMMM DEFENSIBILITY SMOKE FAILED"
  exit 1
fi
