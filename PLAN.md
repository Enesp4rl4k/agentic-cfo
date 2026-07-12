# AI CFO — Tam Proje Planı

> KOBİ'ler için CFO seviyesi finansal analiz, tahmin ve iş akışı yönetimi yapan agentic AI sistemi.
> Stack: FastAPI + LangGraph (backend) · Next.js 14 + shadcn/ui (frontend) · PostgreSQL · Redis · Docker

---

## Karpathy Prensipleri (bu projede uygulanacak)

- **Simplicity First** — Her agent tek bir sorumluluğa sahip. Gereksiz abstraction yok.
- **Surgical Changes** — Yeni özellik eklenirken sadece ilgili dosyalar değiştirilir.
- **Goal-Driven** — Her görevin `done_when` kriteri var. Kendi kendini değerlendirmez.
- **Nothing grades its own homework** — Orchestrator planlar, worker'lar çalışır, verifier ayrı doğrular.

---

## Agent-Loop Mimarisi

```
┌─────────────────────────────────────────────────────┐
│              CFO Orchestrator (Conductor)             │
│         LangGraph StateGraph · GPT-4o · xhigh        │
└──────┬──────┬──────┬──────┬──────────────────────────┘
       │      │      │      │
  ┌────▼──┐ ┌─▼───┐ ┌▼────┐ ┌▼──────────┐ ┌──────────┐
  │ Data  │ │ P&L │ │Cash │ │ Forecast  │ │  Report  │
  │Ingest │ │Agent│ │Flow │ │  Agent    │ │  Agent   │
  │Agent  │ │     │ │Agent│ │           │ │          │
  └───────┘ └─────┘ └─────┘ └───────────┘ └──────────┘
                                    │
                          ┌─────────▼──────────┐
                          │   Verifier (Gate)   │
                          │  verify.sh → exit 0 │
                          └─────────────────────┘
```

### Agent Sorumlulukları

| Agent | Sorumluluk | Input | Output |
|-------|-----------|-------|--------|
| **Orchestrator** | Görev planla, agent'ları yönlendir | Kullanıcı isteği | Work orders |
| **DataIngestion** | PDF/Excel/CSV oku, OCR, DB'ye kaydet | Dosya | Structured transactions |
| **PnL** | Gelir-gider analizi, margin hesapla | Transactions | P&L statement |
| **CashFlow** | Nakit akış tablosu, likidite riski | Transactions | Cash flow statement |
| **Forecast** | 3/6/12 aylık tahmin, senaryo analizi | Historical data | Forecast + alerts |
| **Report** | Excel/PDF rapor üret, dashboard JSON | All statements | Reports + JSON |

---

## Proje Dosya Yapısı

```
ai-cfo/
├── PLAN.md                          ← Bu dosya
├── CLAUDE.md                        ← Proje kuralları (laws-lint uyumlu)
├── verify.sh                        ← Deterministic done gate
├── docker-compose.yml
├── .env.example
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── app/
│   │   ├── main.py                  ← FastAPI app
│   │   ├── config.py                ← Pydantic Settings
│   │   ├── database.py              ← SQLAlchemy async engine
│   │   │
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── state.py             ← LangGraph CFOState TypedDict
│   │   │   ├── orchestrator.py      ← Ana graph, node routing
│   │   │   ├── data_ingestion.py    ← OCR + parse + DB save
│   │   │   ├── pnl_agent.py         ← P&L hesaplama
│   │   │   ├── cashflow_agent.py    ← Nakit akış analizi
│   │   │   ├── forecast_agent.py    ← ML + LLM tahmin
│   │   │   └── report_agent.py      ← Excel/PDF/JSON üretimi
│   │   │
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── deps.py              ← FastAPI dependencies
│   │   │   ├── upload.py            ← POST /upload
│   │   │   ├── analysis.py          ← POST /analyze, GET /status/{id}
│   │   │   ├── reports.py           ← GET /reports, GET /reports/{id}/download
│   │   │   └── dashboard.py         ← GET /dashboard/summary
│   │   │
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── transaction.py       ← Transaction SQLAlchemy model
│   │   │   ├── analysis_job.py      ← AnalysisJob model
│   │   │   └── report.py            ← Report model
│   │   │
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── transaction.py       ← TransactionCreate, TransactionRead
│   │   │   ├── analysis.py          ← AnalysisRequest, AnalysisResult
│   │   │   └── report.py            ← ReportRead, DashboardSummary
│   │   │
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── ocr_service.py       ← PyMuPDF + pytesseract
│   │   │   ├── excel_service.py     ← openpyxl okuma
│   │   │   ├── report_generator.py  ← Excel/PDF üretimi
│   │   │   └── storage_service.py   ← Dosya kaydetme/okuma
│   │   │
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── financial_tools.py   ← LangChain @tool: hesaplamalar
│   │       └── db_tools.py          ← LangChain @tool: DB sorguları
│   │
│   └── tests/
│       ├── __init__.py
│       ├── test_agents/
│       │   ├── test_pnl_agent.py
│       │   └── test_forecast_agent.py
│       ├── test_api/
│       │   ├── test_upload.py
│       │   └── test_dashboard.py
│       └── test_services/
│           └── test_ocr_service.py
│
└── frontend/
    ├── Dockerfile
    ├── package.json
    ├── tsconfig.json
    ├── tailwind.config.ts
    ├── next.config.ts
    └── src/
        ├── app/
        │   ├── layout.tsx           ← Root layout, globals.css import
        │   ├── page.tsx             ← Landing / redirect
        │   ├── (dashboard)/
        │   │   ├── layout.tsx       ← Sidebar + header layout
        │   │   ├── page.tsx         ← Ana dashboard (KPI + charts)
        │   │   ├── upload/
        │   │   │   └── page.tsx     ← Dosya yükleme
        │   │   ├── cashflow/
        │   │   │   └── page.tsx     ← Nakit akış görünümü
        │   │   ├── forecast/
        │   │   │   └── page.tsx     ← Tahmin & senaryo
        │   │   └── reports/
        │   │       └── page.tsx     ← Raporlar listesi + indirme
        │   └── api/
        │       └── [...proxy]/
        │           └── route.ts     ← Backend proxy
        │
        ├── components/
        │   ├── ui/                  ← shadcn/ui primitives
        │   │   ├── button.tsx
        │   │   ├── card.tsx
        │   │   ├── skeleton.tsx
        │   │   ├── badge.tsx
        │   │   └── ...
        │   ├── charts/
        │   │   ├── CashflowChart.tsx    ← Recharts AreaChart
        │   │   ├── PnLChart.tsx         ← Recharts BarChart
        │   │   └── ForecastChart.tsx    ← Recharts ComposedChart
        │   ├── dashboard/
        │   │   ├── KPICard.tsx          ← Metrik kartı
        │   │   ├── AlertBanner.tsx      ← Nakit riski uyarısı
        │   │   ├── RecentTransactions.tsx
        │   │   └── ScenarioSelector.tsx ← İyi/Baz/Kötü senaryo
        │   ├── upload/
        │   │   └── FileDropzone.tsx     ← react-dropzone
        │   └── layouts/
        │       ├── Sidebar.tsx
        │       └── Header.tsx
        │
        ├── hooks/
        │   ├── useDashboard.ts      ← TanStack Query
        │   ├── useUpload.ts
        │   ├── useReports.ts
        │   └── useForecast.ts
        │
        ├── lib/
        │   ├── utils.ts             ← cn() utility
        │   └── api/
        │       ├── client.ts        ← Axios instance
        │       ├── dashboard.ts
        │       ├── upload.ts
        │       └── reports.ts
        │
        ├── types/
        │   └── index.ts             ← Transaction, Report, DashboardSummary types
        │
        └── styles/
            └── globals.css          ← Tailwind + CSS variables
```

---

## UI/UX Design System (ui-ux-pro-max skill)

### Seçilen Stil: **Modern Fintech SaaS — Dark Professional**

```
Ürün tipi:    Fintech SaaS Dashboard
Stil:         Minimal + Dark mode default
Endüstri:     B2B Finance / KOBİ
```

### Renk Paleti

```css
:root {
  /* Dark mode default (fintech için) */
  --background:    224 71% 4%;     /* #060B18 — derin lacivert */
  --foreground:    213 31% 91%;    /* açık gri-beyaz */
  --card:          224 47% 8%;     /* hafif açık panel */
  --muted:         223 47% 11%;
  --muted-foreground: 215 16% 47%;
  --border:        216 34% 17%;
  --primary:       221 83% 53%;    /* #2563EB mavi — CTA */
  --primary-foreground: 0 0% 100%;
  --accent:        262 80% 60%;    /* #7C3AED mor — vurgu */
  --success:       142 76% 36%;    /* #16A34A yeşil — pozitif */
  --warning:       38 92% 50%;     /* #F59E0B sarı — uyarı */
  --destructive:   0 84% 60%;      /* #EF4444 kırmızı — risk */
  --radius:        0.5rem;
}
```

### Tipografi

```
Başlıklar:  Inter (700) — tracking-tight
Gövde:      Inter (400/500) — line-height 1.6
Sayılar:    tabular-nums — finansal veri hizalama
Mono:       JetBrains Mono — kod, ID'ler
```

### Chart Seçimleri (chart domain)

| Veri | Chart Tipi | Kütüphane |
|------|-----------|-----------|
| Nakit akış trendi | AreaChart (gradient) | Recharts |
| Gelir/gider karşılaştırma | GroupedBarChart | Recharts |
| Kategori dağılımı | DonutChart | Recharts |
| Tahmin + gerçekleşme | ComposedChart | Recharts |
| KPI delta | SparkLine | Recharts |

---

## Agent-Loop Kuralları (agent-loop skill)

### Conductor / Worker / Verifier Ayrımı

```
Orchestrator (Conductor):
  - effort: high (xhigh sadece uzun overnight run için)
  - Planlar, yönlendirir, hiçbir şeyi doğrulamaz
  - max_tokens: 16k (düşünce + yanıt için)

Sub-agents (Workers):
  - effort: medium
  - Sadece kendine verilen görevi yapar
  - Kendi çıktısını doğrulamaz

Verifier:
  - verify.sh → exit 0 = done
  - pytest + ruff + mypy + tsc --noEmit
```

### Standing Goals (re-verified daily)

1. `pytest backend/tests/ -q` → 0 hata
2. `ruff check backend/` → 0 warning
3. `mypy backend/app/` → 0 error
4. `npm run typecheck --prefix frontend` → 0 error
5. `docker-compose up --build` → tüm servisler healthy

---

## Geliştirme Sırası (done_when kriterleriyle)

### Faz 1 — Foundation (Gün 1-2)

| Görev | done_when |
|-------|-----------|
| docker-compose.yml | `docker-compose up` → postgres + redis healthy |
| backend/requirements.txt | `pip install -r requirements.txt` → 0 error |
| backend/app/main.py | `GET /health` → `{"status": "ok"}` |
| backend/app/config.py | `pytest tests/test_config.py` → pass |
| database.py + models | `alembic upgrade head` → 0 error |

### Faz 2 — Data Ingestion (Gün 3-4)

| Görev | done_when |
|-------|-----------|
| ocr_service.py | Örnek PDF'den tarih+tutar çıkarır |
| excel_service.py | Örnek Excel'den işlem listesi döner |
| DataIngestion agent | `test_data_ingestion.py` → pass |
| POST /upload endpoint | 200 + job_id döner |

### Faz 3 — Core Agents (Gün 5-7)

| Görev | done_when |
|-------|-----------|
| LangGraph state + orchestrator | Graph compile olur, state akışı çalışır |
| pnl_agent.py | `test_pnl_agent.py` → gross_margin doğru |
| cashflow_agent.py | `test_cashflow_agent.py` → nakit pozisyon doğru |
| forecast_agent.py | 3 senaryo üretir, hepsi sayısal |
| report_agent.py | Excel dosyası oluşturur, indirilebilir |

### Faz 4 — API + Frontend (Gün 8-10)

| Görev | done_when |
|-------|-----------|
| Tüm FastAPI endpoint'leri | `pytest tests/test_api/` → pass |
| Next.js iskeleti | `npm run build` → 0 error |
| Dashboard sayfası | KPI card'lar + 2 chart render eder |
| Upload sayfası | Dosya yüklenince job_id alır |
| Reports sayfası | PDF/Excel indirme çalışır |

### Faz 5 — Polish + Gate (Gün 11-12)

| Görev | done_when |
|-------|-----------|
| verify.sh | `./verify.sh` → exit 0 |
| CLAUDE.md | Tüm kurallar law formatında |
| README.md | `docker-compose up` ile proje ayağa kalkar |

---

## Teknoloji Seçim Gerekçeleri

| Teknoloji | Alternatif | Neden Seçildi |
|-----------|-----------|---------------|
| LangGraph | LangChain LCEL | Stateful, döngüsel workflow; daha güvenilir agent orchestration |
| GPT-4o | Claude, Gemini | Vision desteği (fatura görseli), function calling güvenilirliği |
| FastAPI | Django, Flask | Async, tip güvenliği, otomatik OpenAPI dökümantasyonu |
| PostgreSQL | MySQL, MongoDB | ACID, pgvector (RAG için), finansal veri güvenilirliği |
| Redis | RabbitMQ | Job queue + cache tek serviste, az kompleksite |
| PyMuPDF | pdfplumber | Daha hızlı, image extraction desteği |
| Recharts | Chart.js, D3 | React-native, TypeScript desteği, hafif bundle |
| shadcn/ui | MUI, Chakra | Copy-paste, tam kontrol, Tailwind uyumlu |

---

## Güvenlik Notları

- `.env` dosyası asla commit edilmez
- API key'ler sadece backend'de, frontend'e asla geçmez
- File upload: sadece PDF/Excel/CSV, max 10MB, virüs scan
- DB: parameterized queries (SQLAlchemy ORM, raw SQL yok)
- Rate limiting: POST /upload → 10 req/min/user

---

## Başlangıç Komutu

```bash
# Projeyi klonla ve başlat
cd ai-cfo
cp .env.example .env
# .env içine OPENAI_API_KEY ekle
docker-compose up --build
# → http://localhost:3000 (frontend)
# → http://localhost:8000/docs (backend API)
```
