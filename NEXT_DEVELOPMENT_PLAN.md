# Next development plan — prove the stack, then deepen it

**Horizon:** 3 sprints (≈ 6 weeks)  
**Law:** `CLAUDE.md` — Done = `./verify.sh` or `python scripts/verify.py` exits 0. Confidence gate 0.80. No new C-level roles.  
**North star:** One data plane → canonical txs → semantic snapshot → conflict → grounded chat → Command Center. If any hop is unproven, it is not done.

This plan exists because unit tests for projectors / eval / connectors pass in isolation, but the **end-to-end semantic architecture** must stay proven against a real DB + shared chat pack. Structural grep (`scripts/golden-path-check.sh`) is not proof by itself.

---

## Current state (as of 2026-08-24)

### Phase 0 implemented in this checkout

- Windows gate: `scripts/verify.py` (`--fast --backend` mirrors `verify.sh`)
- `CATEGORY_KEYWORDS` re-exported from `data_ingestion.py` (collection no longer dies)
- `rebuild_semantic_snapshot(..., strict=True)` — tests cannot swallow None
- DB integration: `backend/tests/test_agents/test_semantic_rebuild_integration.py`
- `auto_chain` top-level `get_company_context` / `rebuild_semantic_snapshot` (patches hit)
- REST `/chat/agent` uses `prepare_grounded_chat` + `finalize_grounded_answer` (same pack as WS)
- Negotiation conflict list/resolve is ORM (`list_org_conflicts`)
- Debounce skip enqueues trailing rebuild (`enqueue_trailing_semantic_rebuild` / ARQ `run_semantic_rebuild`)

### Still later (Phase 1+)

Live connectors, Playwright Command Center, eval in CI as a hard fail, Kafka, new roles — out of Phase 0.

---

## Phase 0 — Prove it works  (implemented)

### 0.1 Windows test gate

- [x] `scripts/verify.py` mirroring `verify.sh --fast --backend`
- [x] `CATEGORY_KEYWORDS` collection fix
- [x] `CLAUDE.md` documents Windows gate

**DoD:** `python scripts/verify.py --fast --backend` is the Windows done command.

### 0.2 Integration test: rebuild is a real write

- [x] `test_semantic_rebuild_integration.py` — sqlite, ORM only
- [x] `strict=True` on rebuild

### 0.3 `auto_chain` tests

- [x] Top-level imports so existing patches work
- [x] Assert `rebuild_semantic_snapshot` is awaited on CFO complete
- [x] Conductor `should_run=false` skips chained agents

### 0.4 Unify chat grounding

- [x] `/chat/agent` calls shared pack helpers
- [x] Shared invented-number case in `test_chat_grounding.py`
- [x] Golden-path requires `prepare_grounded_chat` in `chat.py`

### 0.5 Conflict + debounce

- [x] `list_org_conflicts` ORM; negotiation list/resolve no raw SQL
- [x] Trailing rebuild instead of drop-last-agent
- [x] Command Center still wires `ConflictCard` + `getDecisionBrief` (golden-path)

### Phase 0 exit

```text
python scripts/verify.py --fast --backend
pytest backend/tests/test_agents/test_semantic_rebuild_integration.py -q
pytest backend/tests/test_agents/test_auto_chain.py -q
pytest backend/tests/test_agents/test_grounding_eval.py -q
pytest backend/tests/test_agents/test_chat_grounding.py -q
```

---

## Phase 1 — Semantic spine on a demo org (days 6–10)

Goal: one seeded organization where a developer can watch the hop list without Stripe keys.

### 1.1 Fixture: "contradiction org"

Integration seed already uses inflow 1_000_000 vs revenue 1_600_000 cents, runway 3.0, ROAS 4.0. Promote to a demo-org script / API contract tests next.

### 1.2 API contract test (httpx + TestClient)

- [ ] `POST /semantic/me/rebuild` → 200, metrics length > 0
- [ ] `GET /semantic/me` → snapshot.period.key set
- [ ] `GET /semantic/me/brief` → findings include runway + conflict
- [ ] `GET /negotiation/conflicts/{org}` → at least one open metric conflict (ORM list is ready)
- [ ] `POST /chat/agent` runway question with stubbed LLM

### 1.3 Command Center UI pass

Manual or Playwright against `localhost:3000`:

- [ ] Decision Brief headline + health score render
- [ ] Semantic metrics panel shows `finance.runway_months`
- [ ] Conflict card shows CFO vs canonical
- [ ] Intelligence page shows the same snapshot

---

## Phase 2 — Live connectors, one vertical (days 11–16)

Do **one** live source end-to-end before enabling the rest. Prefer CRM closed-won CSV then Stripe if keys exist.

---

## Phase 3 — Trust loop (days 17–22)

Brief approval API test, eval in CI (`hallucination_cases > 0` fails), rebuild JobLog line.

---

## Explicitly out of scope (until Phase 0–2 are green)

- New agents / roles (CPO, CLO, …)
- Kafka / sub-100ms roadmap items
- LangGraph version upgrade
- Expanding TR parsers
- New dashboard pages

---

## Daily check (do not skip)

```powershell
cd backend
python -m pytest tests/test_agents/test_semantic_model.py tests/test_agents/test_semantic_rebuild_integration.py tests/test_agents/test_grounding_eval.py tests/test_agents/test_chat_grounding.py tests/test_agents/test_auto_chain.py -q
```

When this is red, the sprint is red. New UI is not progress.
