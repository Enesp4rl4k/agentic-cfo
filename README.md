# C-Level AI

> **Your entire C-Suite, powered by AI.**  
> Upload your accounting data. Get CFO reports, risk analysis, and 12-month forecasts in 5 minutes.

[![Tests](https://img.shields.io/badge/tests-941%20passing-brightgreen)](backend/)
[![Stack](https://img.shields.io/badge/stack-Next.js%2014%20%2B%20FastAPI%20%2B%20LangGraph-blue)](.)
[![License](https://img.shields.io/badge/license-MIT-gray)](LICENSE)

---

## What is C-Level AI?

C-Level AI is an agentic financial intelligence platform that runs 12 specialized AI agents simultaneously — each covering a different executive role:

| Agent | Coverage |
|-------|----------|
| **CFO** | P&L, cash flow, budget variance, tax calendar, anomaly detection |
| **CEO** | OKR tracking, strategic priorities, board deck synthesis |
| **CTO** | Technical debt, system health, sprint velocity |
| **COO** | Process efficiency, SLA compliance, resource utilization |
| **CMO** | CAC, LTV, campaign ROI, market growth |
| **CHRO** | Attrition risk, compensation analysis, department health |
| **Compliance** | Regulatory coverage, policy gaps, violation tracking |
| **Risk** | KRI monitoring, correlation matrix, cascade simulation |
| **Internal Audit** | Anomaly flagging, audit trail, finding management |

---

## Quick Start

### Prerequisites

- Node.js 18+
- Python 3.11+
- Docker (optional, for full stack)

### 1. Clone & configure

```bash
git clone https://github.com/yourorg/clevelai.git
cd clevelai
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
cp .env.demo .env
docker compose -f docker-compose.demo.yml up
```

Then open http://localhost:3000 — sample data is pre-loaded automatically.

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
│  Upload → Data Ingestion → Agent Orchestrator   │
│                                                 │
│  ┌──────────────────────────────────────────┐   │
│  │           LangGraph Pipeline             │   │
│  │  CFO → CEO → CTO → COO → CMO → CHRO     │   │
│  │  Risk → Compliance → Audit → Synthesis   │   │
│  └──────────────────────────────────────────┘   │
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

### AI & Agents
- **12 specialized agents** running in a LangGraph pipeline
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
OPENAI_API_KEY=sk-...
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
pytest tests/ -v          # run all 941 tests
pytest tests/ -x          # stop on first failure
pytest tests/ --co -q     # list tests only
```

All tests are pure-function — no LLM calls, no database required.

---

## Roadmap

- [ ] Stripe billing integration
- [ ] Scheduled weekly email reports (Resend)
- [ ] SSO / SAML for enterprise
- [ ] WhatsApp / Slack notifications for alerts
- [ ] Mobile-responsive dashboard
- [ ] Custom KPI builder

---

## License

MIT © 2025 C-Level AI
