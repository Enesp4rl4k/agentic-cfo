# Semantic Company Model

Canonical org+period metrics for C-level decisions. Agent `last_*_result` blobs remain for compatibility; the semantic layer is the preferred read path.

## Rebuild contract

`rebuild_semantic_snapshot(org_id, db)`:

1. Loads `CompanyContext` + org `base_currency` / `locale`
2. Projects deterministic metrics from CFO/CMO/CTO/CHRO/COO/risk blobs + `canonical_transactions`
3. Builds a rule-based `DecisionBrief` (confidence gate 0.80)
4. Persists `company_semantic_snapshots` (+ Redis mirror)
5. Mirrors `decision_brief` onto `last_ceo_result`
6. Indexes a `semantic_snapshot` RAG chunk (non-fatal)

Triggered after: `POST /context/{org}`, `auto_chain.on_agent_complete`, CFO ARQ worker persist, `POST /semantic/me/rebuild`.

## Metric catalog (stable IDs)

See `backend/app/services/semantic/catalog.py`. Never rename IDs — add new ones.

Key IDs: `finance.revenue`, `finance.runway_months`, `growth.overall_roas`, `tech.health_score`, `people.headcount`, `risk.overall_score`, …

## APIs

- `GET /api/v1/semantic/me`
- `GET /api/v1/semantic/me/metrics/{metric_id}`
- `POST /api/v1/semantic/me/rebuild` (admin/owner/cfo)
- `GET /api/v1/semantic/me/brief`
