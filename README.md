# AI CFO — Agentic Financial Intelligence Platform

> CFO-level financial analysis, forecasting, and reporting for SMBs.
> Upload a bank statement → AI analyzes it → Get P&L, cash flow, and a 12-month forecast.

![Stack](https://img.shields.io/badge/FastAPI-0.111-green) ![Stack](https://img.shields.io/badge/Next.js-14-black) ![Stack](https://img.shields.io/badge/LangGraph-0.1-orange) ![Stack](https://img.shields.io/badge/DeepSeek-API-blue)

---

## Features

| Feature | Details |
|---------|---------|
| **Automatic data extraction** | Reads PDF, Excel, and CSV bank statements |
| **Turkish bank support** | Akbank, Garanti BBVA, İş Bankası, Ziraat (structured parsers) |
| **P&L analysis** | Revenue, COGS, gross profit, OpEx breakdown, EBITDA, net income |
| **Cash flow statement** | Operating / Investing / Financing activities, monthly series |
| **12-month forecast** | Optimistic / Base / Pessimistic scenarios, runway calculation |
| **CFO narrative** | LLM-generated executive summary at each analysis step |
| **Category correction** | User corrects category → system learns (CategoryRule feedback loop) |
| **Excel report** | 3-sheet Excel: P&L + Cash Flow + Forecast |
| **Confidence gate** | Requires human approval when LLM confidence drops below 80% |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│              CFO Orchestrator (LangGraph)             │
└──────┬──────┬──────┬──────┬──────────────────────────┘
       │      │      │      │
  ┌────▼──┐ ┌─▼───┐ ┌▼────┐ ┌▼──────────┐ ┌──────────┐
  │ Data  │ │ P&L │ │Cash │ │ Forecast  │ │  Report  │
  │Ingest │ │Agent│ │Flow │ │  Agent    │ │  Agent   │
  └───────┘ └─────┘ └─────┘ └───────────┘ └──────────┘
```

**Stack:**
- **Backend:** FastAPI + LangGraph + SQLAlchemy (PostgreSQL / SQLite)
- **Frontend:** Next.js 14 App Router + Tailwind CSS + Recharts
- **LLM:** DeepSeek API (OpenAI-compatible — works with GPT-4o too)
- **Database:** PostgreSQL (production) / SQLite (development)

---

## Quick Start

### Docker (Recommended)

```bash
git clone https://github.com/your-username/agentic-cfo.git
cd agentic-cfo

cp .env.example .env
# Edit .env: add your OPENAI_API_KEY (or DeepSeek key)

docker-compose up --build
```

- Frontend: http://localhost:3000
- Backend API docs: http://localhost:8000/docs

### Local Development (no Docker)

**Backend:**
```bash
cd backend
pip install fastapi uvicorn sqlalchemy aiosqlite pydantic pydantic-settings python-multipart aiofiles
pip install langchain langchain-openai langgraph openpyxl pymupdf

# Create .env
cp ../.env.example .env
# Set your API key and LLM config

python -m uvicorn app.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
# http://localhost:3000
```

---

## LLM Configuration

The system works with any OpenAI-compatible API. Configure via `.env`:

```env
# DeepSeek (recommended — cost-effective)
OPENAI_API_KEY=sk-...            # Your DeepSeek API key
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com

# OpenAI GPT-4o
# OPENAI_API_KEY=sk-...
# LLM_MODEL=gpt-4o
# LLM_BASE_URL=                  # leave empty for OpenAI default
```

> Get a DeepSeek API key: https://platform.deepseek.com

---

## Usage Flow

1. **http://localhost:3000/upload** → Upload a bank statement (PDF / Excel / CSV)
2. AI processes in the background: extract → P&L → cash flow → forecast → report
3. View results on the Dashboard (KPIs, charts, scenario table)
4. Download the Excel report from `/reports`
5. Correct transaction categories — the classifier learns from corrections

---

## API Reference

Swagger UI available at **http://localhost:8000/docs** when the backend is running.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/v1/upload` | POST | Upload file → returns `job_id` |
| `/api/v1/analyze/{job_id}` | POST | Trigger analysis pipeline |
| `/api/v1/analysis/{job_id}` | GET | Poll job status |
| `/api/v1/analysis/{job_id}/approve` | POST | Human approval (confidence gate) |
| `/api/v1/dashboard/{job_id}` | GET | Dashboard JSON payload |
| `/api/v1/reports/{job_id}` | GET | List generated reports |
| `/api/v1/reports/{report_id}/download` | GET | Download Excel/PDF |
| `/api/v1/transactions/{id}/category` | PATCH | Correct transaction category |

---

## Project Structure

```
agentic-cfo/
├── backend/
│   ├── alembic/             # Database migrations
│   ├── app/
│   │   ├── agents/          # LangGraph agents
│   │   │   ├── orchestrator.py
│   │   │   ├── data_ingestion.py
│   │   │   ├── pnl_agent.py
│   │   │   ├── cashflow_agent.py
│   │   │   ├── forecast_agent.py
│   │   │   └── report_agent.py
│   │   ├── api/             # FastAPI route handlers
│   │   ├── models/          # SQLAlchemy models
│   │   ├── parsers/         # Turkish bank statement parsers
│   │   └── services/        # Classifier, storage
│   └── tests/
└── frontend/
    └── src/
        ├── app/             # Next.js App Router pages
        ├── components/      # UI components
        ├── hooks/           # TanStack Query hooks
        └── types/           # TypeScript types
```

---

## Development

```bash
# Backend tests
cd backend && python -m pytest tests/ -q

# Backend lint
cd backend && python -m ruff check app/ tests/

# Frontend type check
cd frontend && npm run typecheck

# Frontend lint
cd frontend && npm run lint
```

---

## License

MIT
