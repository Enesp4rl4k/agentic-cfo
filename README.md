# AI CFO

Agentic AI financial analysis platform for SMBs. Upload a bank statement, invoice export, or CSV — get CFO-level P&L analysis, cash flow statement, 12-month forecast with scenario planning, and a downloadable Excel report.

## Stack

- **Backend**: FastAPI + LangGraph (Python 3.11)
- **AI**: GPT-4o via LangChain — 5-agent pipeline with confidence gate
- **Frontend**: Next.js 14 App Router + shadcn/ui + Recharts
- **Database**: PostgreSQL 16
- **Queue/Cache**: Redis 7
- **Infrastructure**: Docker Compose

## Agent Pipeline

```
Upload → Data Ingestion → [Confidence Gate] → P&L → Cash Flow → Forecast → Report
                                ↓ (confidence < 0.80)
                          Hold for Human Review
```

Each agent is a LangGraph node. The confidence gate stops before analysis if OCR quality is low — a human approves before the pipeline continues.

## Quick Start

```bash
# 1. Clone and configure
git clone <repo>
cd ai-cfo
cp .env.example .env
# Edit .env — add your OPENAI_API_KEY

# 2. Start all services
docker-compose up --build

# 3. Open the app
# Frontend: http://localhost:3000
# Backend API docs: http://localhost:8000/docs
```

## Local Development

**Backend:**
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

## Verify Gate

```bash
./verify.sh   # exits 0 = safe to ship
```

Runs: ruff lint → mypy → pytest → tsc → eslint

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/upload` | Upload financial document |
| POST | `/api/v1/analyze/{job_id}` | Start CFO pipeline |
| GET | `/api/v1/analysis/{job_id}` | Poll job status |
| POST | `/api/v1/analysis/{job_id}/approve` | Human review approval |
| GET | `/api/v1/dashboard/{job_id}` | Dashboard JSON |
| GET | `/api/v1/reports/{job_id}` | List reports |
| GET | `/api/v1/reports/{report_id}/download` | Download Excel/PDF |

## Project Structure

```
ai-cfo/
├── backend/app/
│   ├── agents/          # LangGraph pipeline (5 agents)
│   ├── api/             # FastAPI routers
│   ├── models/          # SQLAlchemy models
│   └── services/        # OCR, Excel, Storage
├── frontend/src/
│   ├── app/(dashboard)/ # Next.js pages
│   ├── components/      # UI components
│   ├── hooks/           # TanStack Query hooks
│   └── lib/api/         # API client
├── PLAN.md              # Architecture decisions
├── CLAUDE.md            # Agent laws (laws-lint compliant)
└── verify.sh            # Done gate
```

## Key Design Decisions

- **Amounts stored as integers** (cents) — no floating point rounding errors
- **Confidence gate** — agent stops at < 0.80 confidence, requires human approval
- **Audit trail** — every agent run writes a `StepLog` array to `analysis_jobs.logs`
- **Nothing grades its own homework** — verifier is a separate LangGraph node
