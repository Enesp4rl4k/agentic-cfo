# Agentic + RAG Engineering Specification

> **Status:** v1.0 — authoritative design for multi-role management platform  
> **Scope:** Agent orchestration, verification, RAG grounding, management conductor  
> **Law:** See `CLAUDE.md` — confidence gate, verifier separation, audit trail

---

## 1. Design Goals

| Goal | Engineering requirement |
|------|-------------------------|
| **Multi-role management** | One data plane, many executive lenses — not many siloed products |
| **Trust in finance** | No skill grades its own homework; human review when confidence < 0.80 |
| **Grounded answers** | Chat/synthesis must cite retrievable evidence or declare absence |
| **Depth follows data** | Roles run at L0–L3 based on available integrations, not uniform depth |
| **Production throughput** | Analysis vs maintenance queues; lazy agent execution |
| **Observable** | Every run → logs, verifier verdict, ops metrics |

---

## 2. Layered Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  MANAGEMENT LAYER (Frontend + Command Center)                            │
│  CEO synthesis home · role drill-down · SLA/conflict cards               │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────────┐
│  CONDUCTOR (platform/conductor.py)                                       │
│  Execution plan: which roles · what depth · which queue                  │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌───────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ LangGraph     │     │ ARQ Workers     │     │ Agent Bus       │
│ Orchestrators │     │ analysis / maint│     │ (Redis pub/sub) │
│ per domain    │     │                 │     │                 │
└───────┬───────┘     └────────┬────────┘     └────────┬────────┘
        │                      │                       │
        └──────────────────────┼───────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  PLATFORM KERNEL                                                         │
│  CompanyContext · AgentContextBridge · CapabilityRouter · AutoChain      │
└───────────────────────────────┬─────────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  DATA PLANE + RAG                                                        │
│  canonical_transactions · sync_runs · quality_gate · RagRetriever        │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Agentic Engineering Contracts

### 3.1 Module layout

| Path | Responsibility |
|------|----------------|
| `backend/app/platform/contracts.py` | Stable types: `EvidenceBundle`, `VerifierVerdict`, `PlatformHandoff` |
| `backend/app/platform/policies.py` | Thresholds — **single source of truth** |
| `backend/app/platform/conductor.py` | Management execution planning |
| `backend/app/agents/state.py` | Per-pipeline TypedDict state |
| `backend/app/agents/verifier_node.py` | Independent verification node |
| `backend/app/agents/orchestrator.py` | CFO LangGraph (reference implementation) |
| `backend/app/services/rag/retriever.py` | Pluggable RAG backend |

### 3.2 Skill contract (every agent node)

Every skill MUST return `SkillResult`:

```python
@dataclass
class SkillResult:
    ok: bool
    patch: dict[str, Any]
    confidence: float | None      # 0–1
    needs_review: bool = False    # forces awaiting_review
    halt: bool = False            # fatal — stops pipeline
    detail: str | None = None
```

**Rules:**
1. `confidence` is mandatory for any LLM-generated narrative step.
2. `needs_review=True` when OCR quality low, critical alert, or policy violation.
3. Skills MUST NOT set `awaiting_review=False` after another skill set it True.

### 3.3 Confidence gate (pre-effect)

After `data_ingestion`, conditional edge:

- `min_confidence < CONFIDENCE_AUTO_PROCEED_MIN (0.80)` → `hold_for_review`
- `awaiting_review=True` → `hold_for_review`
- `halted=True` → END

Constant: `app.platform.policies.CONFIDENCE_AUTO_PROCEED_MIN`

### 3.4 Verifier node (post-compute, pre-report)

**Separate LangGraph node** — `alert → verifier → report | hold_for_review`

Implemented in `verifier_node.py`. Checks:
- Pipeline not halted
- `min_confidence` threshold
- `reflection_scores` for pnl / cashflow / forecast vs `REFLECTION_HOLD_THRESHOLD`
- Respects `AgentRunConfig.require_review`

Verifier output stored in `CFOState.verifier_verdict`.

**Worker MUST use** `AgentRunConfig(require_review=True)` (fixed in worker.py).

### 3.5 Role depth model

| Level | Name | Behavior |
|-------|------|----------|
| L0 | Lens | KPI + trend + 3 insights (no LLM or template only) |
| L1 | Agent | Structured analysis + recommendations |
| L2 | Kernel | Cross-role signals + validators + RAG grounding |
| L3 | Autopilot | Approved actions → external systems (future) |

Default depths: `platform/policies.py → ROLE_DEFAULT_DEPTH`

Conductor skips roles when data signals missing — **no hallucinated depth**.

---

## 4. RAG Engineering Specification

### 4.1 Retriever interface

```python
class RagRetriever(Protocol):
    async def retrieve(...) -> EvidenceBundle: ...
```

Implementations:
- **v1:** `TfidfRagRetriever` (current — TF-IDF on `rag_chunks`)
- **v2 (planned):** `EmbeddingRagRetriever` (pgvector + hybrid + rerank)

Callers MUST use `get_rag_retriever()` — never call TF-IDF directly from API layer.

### 4.2 Indexing policy

| Source type | When indexed | Producer |
|-------------|--------------|----------|
| `cfo_transactions_raw` | After CFO job completes | ARQ worker |
| `cfo_dashboard_json` | After report node (planned) | worker |
| `domain_{role}_{job_id}` | After domain agent completes (planned) | domain worker |

Maintenance backfill: `run_rag_backfill_maintenance` on **maintenance queue only**.

### 4.3 Retrieval policy

From `platform/policies.py`:

- `RAG_DEFAULT_TOP_K = 5`
- `RAG_DEFAULT_CANDIDATE_LIMIT = 120`
- `RAG_MIN_SCORE = 0.06`
- Job-scoped first → org-wide fallback (already in rag_service)

### 4.4 Grounding rules (chat / synthesis)

1. If `EvidenceBundle.found == False` → response MUST include safe fallback; no fabricated numbers.
2. API returns `evidence_found`, `evidence_job_scope` metadata.
3. Citations MUST map to `job_id + chunk_index + source_type`.
4. Future: grounding validator compares numeric claims vs retrieved chunks.

### 4.5 Cache

- In-process TTL cache (45s) — acceptable for single worker; v2 → Redis cache keyed by `(org_id, query_hash, job_scope)`.

---

## 5. Management Conductor

`ManagementConductor.plan()` inputs:
- `org_id`
- `trigger` (e.g. `upload_complete`, `scheduled_daily`, `manual`)
- `available_signals` (derived from CompanyContext)
- optional `force_roles`

Outputs: `ConductorPlan` with per-role `should_run`, `depth_level`, `queue`.

**Integration points (roadmap):**
1. `auto_chain.py` — consult conductor before firing domain agents
2. `worker.py` — enqueue only runnable roles
3. Command Center — display plan + blockers (“CHRO waiting for HR CSV”)

---

## 6. Cross-Role Handoff Schema

After each agent run, write `PlatformHandoff` to CompanyContext:

```python
{
  "schema_version": "platform_handoff_v1",
  "org_id": "...",
  "role": "cfo",
  "job_id": "...",
  "depth_level": 2,
  "confidence": 0.91,
  "awaiting_review": false,
  "summary": { ... trimmed dashboard ... },
  "evidence_bundle_id": null,
  "produced_at": "2026-08-19T18:00:00Z"
}
```

CEO synthesis reads all handoffs — not raw domain state blobs.

---

## 7. Queue & Execution Policy

| Queue | Workloads | max_jobs |
|-------|-----------|----------|
| `arq:queue:analysis` | CFO, CEO, user-triggered domain runs | 10 |
| `arq:queue:maintenance` | RAG backfill, usage prune, scheduled heavy jobs | 3 |

Scheduler **enqueues only** — never runs heavy work inline on API process.

---

## 8. Quality Gates (Definition of Done)

Every agentic/RAG change MUST pass:

```bash
./scripts/proof.sh --fast
pytest backend/tests/test_agents/test_platform_engineering.py -q
pytest backend/tests/test_agents/ -q --ignore=tests/test_parsers
```

Agent orchestrator changes additionally require agent test suite green.

---

## 9. Implementation Roadmap

### Phase A — Foundation ✅ (this sprint)
- [x] `platform/contracts.py`, `policies.py`, `conductor.py`
- [x] `verifier_node` wired into CFO graph
- [x] `RagRetriever` abstraction
- [x] Worker `require_review=True`
- [x] Unit tests

### Phase B — Multi-role execution (2–3 weeks)
- [ ] All domain agents on ARQ with unified `AgentJob` model
- [ ] Conductor integrated into `auto_chain`
- [ ] Index domain outputs into RAG (`domain_*` source types)
- [ ] CEO synthesis reads `PlatformHandoff` list

### Phase C — RAG v2 (2–4 weeks)
- [ ] pgvector embeddings + hybrid retrieval
- [ ] Redis evidence cache
- [ ] Grounding validator (numeric claim check)
- [ ] Citation UI in frontend chat

### Phase D — Management Layer v2 (3–5 weeks)
- [ ] Cross-role conflict cards
- [ ] Role-based permissions
- [ ] Negotiation arbiter for conflicting recommendations
- [ ] Board deck from multi-handoff snapshot

---

## 10. Anti-Patterns (Never Do)

1. **Inline secrets or sk-* placeholders in repo** — use `llm-placeholder-*` or GitHub Secrets
2. **Disable `require_review` in worker** for production paths
3. **LLM verifier in same node as narrative generator**
4. **Run domain agents synchronously in API** for heavy analysis
5. **Hardcode thresholds** outside `platform/policies.py`
6. **RAG-less chat** for factual financial claims without disclaimer
7. **Depth without data** — CHRO deep analysis without HRIS signal

---

## 11. File Index

| File | Purpose |
|------|---------|
| `AGENTIC_RAG_ENGINEERING.md` | This document |
| `CLAUDE.md` | Project laws |
| `PLATFORM_ARCHITECTURE.md` | Product-level architecture v2 |
| `backend/app/platform/` | Engineering kernel |
| `backend/app/agents/verifier_node.py` | Verifier |
| `backend/app/services/rag/retriever.py` | RAG interface |
| `backend/tests/test_agents/test_platform_engineering.py` | Contract tests |

---

*Last updated: 2026-08-19 — aligns with feat/platform-scalability-v1 branch*
