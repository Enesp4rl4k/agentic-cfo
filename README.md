# Agentic Management OS

> **A management operating system for the growing family business.**
> Runs finance, accounting and reporting with a real approval structure and a
> full decision trail — so the company can outgrow its founder.

[![Tests](https://img.shields.io/badge/tests-2538%20passing-brightgreen)](backend/)
[![Stack](https://img.shields.io/badge/stack-Next.js%2014%20%2B%20FastAPI%20%2B%20LangGraph-blue)](.)
[![License](https://img.shields.io/badge/license-MIT-gray)](LICENSE)

---

## The problem

Most Turkish companies are family businesses. Roughly a third survive into the
second generation, and far fewer into the third — and what usually kills them is
**governance, not the market**: every decision routes through the founder, there
is no delegated authority, no audit-ready record of why anything was booked, and
no institutional memory when a key person leaves.

This is the *institutionalisation* ("kurumsallaşma") problem. Software cannot do
the human half of it — that is advisory, legal and family work. What software
**can** do is make the disciplined half automatic: a delegation policy that
decides and escalates, a defensible record of every entry, and a measurable
score for how far along you are.

The wedge in is the boring, painful, daily work: **CFO-grade financial analysis
plus deep Turkish accounting** (THP/SMMM, GİB e-Fatura, bank statement parsers)
for companies that cannot hire a CFO.

---

## The two halves

### 1. The executive lenses — what the data says

| Agent | Coverage | Data basis |
|-------|----------|------------|
| **CFO** | P&L, cash flow, forecast, budget variance, tax calendar, anomaly detection | **Your uploaded data** |
| **Accounting (TR)** | THP classification, double-entry journal, trial balance, SMMM review queue | **Your uploaded data** |
| **CEO** | Strategic priorities, SWOT, OKR, board deck synthesis | Aggregates the other agents |
| **Risk / Audit / Compliance** | KRI monitoring, cascade simulation, anomaly flagging, TR regulation catalog | Derived + rule-based |
| **CTO** | Tech debt, incidents, engineering velocity | **Connect GitHub** for real data, otherwise estimated |
| **CMO / CHRO / COO** | CAC/LTV, attrition, SLA, resource utilisation | Paste CSV for real data, otherwise estimated |

**About "estimated":** with no connected domain source, the CTO/CMO/CHRO/COO
kernels extrapolate from your CFO financials times fixed sector benchmarks. The
platform labels that everywhere it appears (`data_source: real | estimated |
benchmark`), badges it red in the UI, and **refuses to let a synthetic result
auto-trigger any downstream agent**. See `app/platform/provenance.py`.

### 2. The governance layer — why you can trust it

| Capability | What it does |
|---|---|
| **Yetki Matrisi** (delegation of authority) | Ordered policy rules — amount bands, confidence, related-party, fixed asset → auto-approve, require named approvers, or block. Versioned per org, edited by the owner. Replaces "ask the boss". |
| **Kurumsallaşma Endeksi** | 0–100 institutionalisation score across financial discipline, delegated authority, decision traceability, human oversight, process cadence and key-person risk — computed from real platform activity, tracked over time. |
| **SMMM Savunulabilirlik Paketi** | One hash-sealed record per period: every journal entry with its basis, AI confidence, and whether a human approved/corrected it or the AI posted it automatically. Built for a tax inspection. |
| **Confidence gate + decomposition** | Runs below the confidence threshold hold for a human — and the UI shows *which step* dragged the score down, not just that it did. |
| **Independent reconciliation** | A separate graph step re-checks the arithmetic identities and flags narrative figures unsupported by computed values. Nothing grades its own homework. |
| **Durable run ledger** | Every pipeline run is recorded, resumable, and reported on (`/runs/slo` — success rate, p50/p95 latency, cost). |

See [INTERNATIONAL_PLATFORM.md](INTERNATIONAL_PLATFORM.md) for the locale /
regional-pack contracts — the Turkish pack is the deepest, but the data plane is
locale-agnostic.

## Quick Start

### Prerequisites

- Node.js 18+
- Python 3.11+
- Docker (optional, for full stack)

### 1. Clone & configure

```bash
git clone https://github.com/Enesp4rl4k/agentic-cfo.git
cd agentic-cfo
cp .env.example .env
# Edit .env — add your LLM API key and NEXTAUTH_SECRET
```

### 2. Backend

```bash
cd backend
pip install -r requirements.txt
alembic upgrade head          # run migrations
uvicorn app.main:app --reload  # start API on :8000
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev   # start on :3000
```

### 4. Open

- **Landing page:** http://localhost:3000
- **Login:** http://localhost:3000/auth/login
- **Register:** http://localhost:3000/auth/register
- **API docs:** http://localhost:8000/docs

---

## One-command demo (Docker)

```bash
docker compose -f docker-compose.demo.yml up
```

Brings up Postgres, Redis, the API, the worker and the frontend. Configuration is
read from `.env.demo.example` directly — no copy step needed. Then open
http://localhost:3000.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                 Next.js 14 Frontend              │
│  Landing · Auth · Dashboard · Chat · Settings   │
└──────────────────┬──────────────────────────────┘
                   │ REST + SSE
┌──────────────────▼──────────────────────────────┐
│                FastAPI Backend                  │
│                                                 │
│  ┌──────────────────────────────────────────┐   │
│  │   CFO pipeline (LangGraph, checkpointed) │   │
│  │   ingest → pnl → cashflow → forecast →   │   │
│  │   anomaly → tax → budget → alert →       │   │
│  │   reconcile → verifier → report          │   │
│  └───────────────┬──────────────────────────┘   │
│                  │ approval gate (human)        │
│  ┌───────────────▼──────────────────────────┐   │
│  │   TR accounting → board deck  (L3 auto)  │   │
│  └──────────────────────────────────────────┘   │
│                                                 │
│  Other roles (CEO/Risk/CTO/…) are separate      │
│  graphs, composed by the conductor.             │
│                                                 │
│  Model Gateway — the single LLM egress point:   │
│  routing · retry · cost ledger · org budget     │
│                                                 │
│  Connector Platform — ports & adapters for      │
│  external sources → canonical tables            │
│                                                 │
│  PostgreSQL · Redis · Alembic migrations        │
└─────────────────────────────────────────────────┘
```

---

## Features

### Financial Intelligence
- **P&L Statement** — revenue, COGS, OPEX breakdown, waterfall chart
- **Cash Flow** — operating/investing/financing with running balance table
- **12-Month Forecast** — Monte Carlo fan chart, 3 scenarios, monthly breakdown
- **Budget Variance** — planned vs actual with alert thresholds
- **Tax Calendar** — VAT, withholding, corporate tax payment schedule

### Governance & trust
- **Delegation of authority** — versioned per-org policy decides auto-approve vs named approvers vs block
- **Institutionalisation index** — 0–100 across six dimensions, tracked over time
- **Defensibility packet** — hash-sealed, per-period audit-defence record for the SMMM
- **Provenance labelling** — every metric carries `real | estimated | benchmark`; synthetic results cannot auto-trigger downstream agents
- **Confidence gate + decomposition** — low-confidence runs hold for a human, and the weakest step is named
- **Independent reconciliation** — a separate step re-checks arithmetic and flags ungrounded narrative figures
- **Durable runs** — resumable pipelines, run ledger, `/runs/slo` latency + cost reporting

### AI & Agents
- **Specialised agents** across finance, accounting and the C-suite lenses
- **Model Gateway** — one LLM egress point with routing, retry, per-org budget and a cost ledger
- **Real-time SSE streaming** — watch each agent step live
- **Natural language queries** — ask anything about your finances
- **Structured LLM output** — Pydantic schemas, template fallbacks for dev mode
- **Anomaly detection** — duplicate payments, unusual amounts, vendor concentration

### Platform
- **Multi-tenant workspaces** — invite team members, role-based access (owner/admin/analyst/viewer)
- **NextAuth.js authentication** — JWT, refresh tokens, API key support
- **OCR pipeline** — PyMuPDF + pdfplumber + Tesseract for PDF invoices
- **Turkish accounting parsers** — Logo Tiger, Paraşüt, GİB e-Fatura, Akbank, Garanti, İş Bankası
- **OpenTelemetry** — structured JSON logs, LangSmith traces
- **Audit trail** — every action logged with user + org context

### UI/UX
- **Command Center** — all agents, cross-domain risks, quick wins
- **Transactions** — sortable columns, pagination, CSV export
- **Anomalies** — grouped by severity, collapsible sections, confidence bars
- **Risk dashboard** — KRI gauge cards, heatmap, risk matrix scatter plot
- **Chat** — markdown rendering, follow-up chips, typing indicator

---

## Environment Variables

```env
# LLM
OPENAI_API_KEY=your-llm-api-key-here
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com

# Database (SQLite for dev, PostgreSQL for prod)
USE_SQLITE=true

# Auth
NEXTAUTH_SECRET=your-32-char-secret
NEXTAUTH_URL=http://localhost:3000
NEXT_PUBLIC_API_URL=http://localhost:8000
```

See `.env.example` for all options.

---

## Testing

```bash
cd backend
pytest tests/ -q          # run all 2538 tests
pytest tests/ -m eval     # golden-case evaluation gate only
pytest tests/ -x          # stop on first failure
```

No test makes a live LLM call — the Model Gateway short-circuits on a placeholder
key and agents fall back to deterministic templates. Tests that need persistence
use an in-memory SQLite database.

Full gate — unit tests, lint, the strict-typing allowlist, structural checks and
the golden-case eval:

```bash
./scripts/proof.sh --fast          # 34 checks; 38 with BACKEND_URL set
python scripts/verify.py --backend # backend only (Windows-friendly)
```

### Live checks against a running instance

`proof.sh` has live checks that are **skipped unless `BACKEND_URL` is set** — and
skipped checks hide real bugs. You do not need a deployment to run them: the API
boots standalone on SQLite with no Postgres, Redis or Docker.

```bash
cd backend
USE_SQLITE=true BACKEND_SECRET_KEY=<32+ chars> OPENAI_API_KEY=llm-placeholder   uvicorn app.main:app --port 8000

# in another shell, from the repo root
BACKEND_URL=http://127.0.0.1:8000 ./scripts/staging-smoke.sh
BACKEND_URL=http://127.0.0.1:8000 ./scripts/proof.sh --fast   # 38 checks
```

The **worker path** (upload → queued analysis) needs no broker either. If Redis
is unreachable, `enqueue_analysis` runs the pipeline inline in the API process
instead of dropping the job — loudly, and only for connection errors:

```
WARNING app.worker  Broker unreachable (...) — running CFO analysis inline for
job=... No durability: this run will not survive a restart and is not retried.
```

That is a laptop convenience, not a production mode: an inline run dies with the
process and is never retried. Set `ALLOW_INLINE_JOB_FALLBACK=false` in any
deployment that has a worker, so a broker outage fails loudly instead of quietly
degrading. The full path end to end:

```bash
BACKEND_URL=http://127.0.0.1:8000 GOLDEN_EMAIL=you@example.com   GOLDEN_PASSWORD=... ./scripts/golden-path-e2e.sh
```

### The governance chain, end to end

`scripts/tr-governance-e2e.sh` runs the institutionalisation story against a live
instance and needs nothing but the API:

```bash
BACKEND_URL=http://127.0.0.1:8000 ./scripts/tr-governance-e2e.sh
```

register → create workspace → enable the TR pack → upload → CFO analysis → THP
double-entry journal → SMMM approves every entry → hash-sealed defensibility
packet (+ PDF) → delegation-of-authority policy → institutionalisation index.

The last assertion is the one that matters: the index is computed from real
platform activity, so it can only rise if every step above actually did
something. On the sample fixture it goes **26 (E) → 61 (C)**. `proof.sh` runs
this whenever `BACKEND_URL` is set.

### Route liveness sweep

```bash
BACKEND_URL=http://127.0.0.1:8000 python scripts/route_sweep.py
```

Reads `/openapi.json`, calls every registered route once, and reports only the
500s — a 401/404/422 means the route is alive and rejecting input properly. It
registers a user, creates a workspace and enables the TR pack first, because the
gated routes are the ones most worth probing. Destructive and outbound routes
(DELETE, webhooks, anything that sends mail or money) are skipped by name, each
with its reason in `SKIP`.

This is the check that finds handlers nobody has ever called. Its first run over
309 routes turned up ten, including a board deck that had always come back blank
and a workspace endpoint no user could call twice.

It does not retry and has no tolerance band. Every `database is locked` the
sweep produced turned out to be a single missing commit in the semantic rebuild
that held a write transaction open for the life of the process — after one
rebuild the instance accepted no further writes at all. Smoothing that over as
"probably contention" is exactly how it stayed hidden.

If a previously-created `backend/aicfo_dev.db` predates a migration, endpoints
will 500 with `no such column` — `create_all` never alters existing tables.
Delete the file and let it rebuild.

---

## Roadmap

**Now — getting it in front of real users**
- [ ] Deploy a live environment (the live checks in `proof.sh` are skipped without one)
- [ ] One polished end-to-end demo path: upload → analysis → journal → approval → sealed packet → index moves
- [ ] Process a real company's bank statement and e-Fatura

**Next — governance depth**
- [ ] Governance calendar — monthly board pack with action-item tracking
- [ ] Related-party (ilişkili taraf) register — detect, disclose, monitor
- [ ] Owner vs operator dashboard split
- [ ] Decision provenance graph — click any board-deck figure down to its source row

**Later**
- [ ] Second connector (accounting/payroll) to take another C-level off estimated data
- [ ] Eval corpora for every L2+ agent, with per-agent calibration in CI
- [ ] Stripe billing, SSO/SAML, Slack alerts

---

## License

MIT © 2025 C-Level AI
