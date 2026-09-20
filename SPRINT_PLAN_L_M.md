# Agentic CFO Platform — Sprint Planı L1–M3

> Mevcut durum incelemesi: SSE streaming ✅, rule-based anomaly ✅, compliance pipeline ✅,
> GDPR endpoints ✅, alert digest ✅, rate limit middleware ✅, Redis ✅, WebSocket chat ✅
>
> Stack: FastAPI + LangGraph · Next.js 14 + shadcn/ui · PostgreSQL · Redis · ARQ worker
> Tamamlanan sprint'ler: I3, J2, J3, K1, K2, K3

---

## Sprint L1 — Advanced Analytics

**Hedef:** Rule-based anomaly detection'ı ML tabanlıya yükselt; time-series forecasting'i güçlendir.
**Süre:** 2 hafta
**Önkoşul:** `anomaly_agent.py`, `analytics.py` mevcut — üzerine inşa edilecek.

---

### 1. Gereksinimler Analizi

Mevcut durum:
- `anomaly_agent.py` — 6 rule-based detector (duplicates, unusual amounts, vendor concentration,
  expense spikes, round numbers, negative cashflow streak)
- `analytics.py` — Monte Carlo (stochastic, numpy-free), working capital, break-even, cohort
- Anomaly confidence skoru statik kurallardan geliyor

Eksikler ve yükseltme hedefleri:

| Alan | Mevcut | Hedef |
|------|--------|-------|
| Anomaly detection | Z-score rule-based | Isolation Forest + DBSCAN hibrit |
| Forecasting | Lineer ekstrapolasyon | statsmodels STL decomposition |
| Time-series insight | Yok | Seasonality, trend change detection |
| Anomaly explanation | Basit string | Evidence zinciri + confidence interval |
| Streaming | Yok (sync scan) | SSE üzerinden anomaly scan progress |

---

### 2. Backend API Design

Yeni endpoint'ler:

```
POST /api/v1/analytics/advanced-anomaly
     Body: { job_id, method: "isolation_forest"|"dbscan"|"ensemble", sensitivity: 0.1-0.9 }
     Response: anomaly list + confidence_lower + confidence_upper + detector_type

POST /api/v1/analytics/forecast-v2
     Body: { job_id, periods: 12, method: "stl"|"arima"|"linear", include_seasonality: bool }
     Response: { historical, forecast: [{date, p10, p50, p90}], change_points, seasonality }

GET  /api/v1/analytics/trend-analysis/{job_id}
     Query: ?metric=revenue&window=90
     Response: trend_direction, velocity, acceleration, anomaly_markers

GET  /api/v1/analytics/anomaly-stream/{job_id}
     → SSE endpoint — scan adım adım progress
```

Değiştirilecek dosyalar:

```
backend/app/agents/anomaly_agent.py
  + isolation_forest_detector()    # scikit-learn IsolationForest
  + dbscan_detector()              # density-based outlier
  + ensemble_score()               # weighted voting
  + confidence_interval()          # bootstrap bounds

backend/app/api/analytics.py
  + POST /analytics/advanced-anomaly
  + POST /analytics/forecast-v2

backend/app/services/
  + forecasting_service.py         # STL / statsmodels
  + anomaly_ml_service.py          # ML detector sınıfları

backend/alembic/versions/015_anomaly_ml_metadata.py
  # anomaly tablosuna: detector_type, confidence_lower, confidence_upper
```

Yeni bağımlılıklar (requirements.txt):

```
scikit-learn>=1.4.0
statsmodels>=0.14.0
# prophet>=1.1.5  — opsiyonel, sadece prod Docker image
```

AnomalyMLService mimarisi:

```python
# backend/app/services/anomaly_ml_service.py
class AnomalyMLService:
    """
    Hibrit anomaly detector.
    Öncelik: 1) Isolation Forest  2) DBSCAN  3) Rule-based  4) Ensemble voting

    Feature vektörü:
    [amount_normalized, day_of_week, vendor_frequency, category_pct,
     amount_vs_category_mean, month_position, amount_zscore]
    """
    def fit_and_detect(
        self,
        transactions: list[dict],
        contamination: float = 0.05,
    ) -> list[AnomalyResult]: ...

    def _build_feature_matrix(self, txs: list[dict]) -> np.ndarray: ...

    def _compute_confidence_interval(
        self, scores: np.ndarray, n_bootstrap: int = 100,
    ) -> tuple[float, float]: ...
```

ForecastingService mimarisi:

```python
# backend/app/services/forecasting_service.py
class ForecastingService:
    """
    STL (Seasonal-Trend decomposition) — mevsimsellik + trend ayrıştırma.
    ARIMA/SARIMA — kısa vadeli tahmin, otomatik parametre seçimi.
    Linear — fallback (< 12 nokta).
    """
    def forecast(
        self,
        series: list[float],
        dates: list[str],
        periods: int = 12,
        method: Literal["stl", "arima", "linear"] = "stl",
    ) -> ForecastResult: ...

    def detect_trend_changes(self, series: list[float]) -> list[TrendChangePoint]:
        # PELT (Pruned Exact Linear Time) change point detection
        ...
```

---

### 3. Frontend Component Blueprint

```
frontend/src/app/(dashboard)/analytics/
├── advanced/page.tsx              ← Advanced Analytics hub
└── anomalies/page.tsx             ← ML anomaly sonuçları + confidence chart

frontend/src/components/analytics/
├── AnomalyHeatmap.tsx             ← Recharts: tarih × kategori × severity
├── ForecastBandChart.tsx          ← P10/P50/P90 fan chart (AreaChart)
├── TrendChangeMarker.tsx          ← Change point annotation overlay
├── AnomalyMLScoreCard.tsx         ← Detector breakdown: IF vs DBSCAN vs Rule
└── SeasonalityDecomposition.tsx   ← Trend + seasonal + residual stacked

frontend/src/hooks/
├── useAdvancedAnomaly.ts          ← SSE + polling hybrid
└── useForecastV2.ts               ← TanStack Query + streaming

frontend/src/lib/api/
└── analytics_advanced.ts          ← Typed API client
```

ForecastBandChart bileşeni:

```tsx
// ComposedChart:
//   Area: P10–P90 confidence band (yarı şeffaf)
//   Line: P50 median forecast (solid)
//   Line: Gerçekleşen değerler
//   ReferenceLine: trend change points (dikey kesik çizgi)

interface ForecastBandChartProps {
  historical: { date: string; value: number }[];
  forecast: { date: string; p10: number; p50: number; p90: number }[];
  changePoints?: { date: string; direction: "up" | "down" }[];
}
```

AnomalyHeatmap bileşeni:

```tsx
// X-axis: haftalar | Y-axis: kategori | Renk: severity yoğunluğu
// Hover: anomaly detayı tooltip | Click: AnomalyDetail drawer
interface AnomalyHeatmapProps {
  jobId: string;
  onAnomalySelect?: (anomaly: AnomalyResult) => void;
}
```

---

### 4. Testing Stratejisi

```python
# backend/tests/test_analytics/
├── test_anomaly_ml.py
│   ├── test_isolation_forest_detects_outlier()
│   ├── test_dbscan_clusters_normal_transactions()
│   ├── test_ensemble_voting_weights()
│   ├── test_confidence_interval_bounds()
│   └── test_feature_matrix_normalization()
│
├── test_forecasting.py
│   ├── test_stl_decomposition_seasonality()
│   ├── test_arima_forecast_horizon()
│   ├── test_trend_change_detection()
│   ├── test_linear_fallback_small_series()
│   └── test_forecast_prediction_intervals()
│
└── test_analytics_endpoints.py
    ├── test_advanced_anomaly_endpoint_200()
    ├── test_forecast_v2_returns_bands()
    └── test_trend_analysis_with_job_id()
```

Integration test hedefleri:
- ML recall ≥ rule-based recall (her rule-based anomaly ML tarafından da yakalanmalı)
- Forecast MAE < %15 (24-aylık fixture üzerinde split test)

Done-when kriterleri:
- [ ] `pytest backend/tests/test_analytics/ -q` → 0 hata
- [ ] `/analytics/advanced-anomaly` → 200, `confidence_lower` + `confidence_upper` mevcut
- [ ] `ForecastBandChart` P10/P50/P90 render ediyor
- [ ] ML scan SSE stream çalışıyor (progress 0→100)

---

### 5. Deployment Checklist

```yaml
pre_deploy:
  - [ ] scikit-learn + statsmodels Docker image'a eklendi
  - [ ] Migration 015 staging'de test edildi
  - [ ] Feature flag: ENABLE_ML_ANOMALY=true (rollback → false = rule-based)
  - [ ] Env vars: ANOMALY_CONTAMINATION=0.05, FORECAST_METHOD=stl

deploy:
  - [ ] alembic upgrade head (015)
  - [ ] Smoke test: POST /analytics/advanced-anomaly → 200

post_deploy:
  - [ ] Production'da 50 job üzerinde recall karşılaştırması
  - [ ] P95 latency < 3s (ML scan kabul edilebilir sınır)
  - [ ] Sentry: anomaly_ml_service error rate > 1% alert
```

---

## Sprint L2 — Agent Negotiation (Multi-Agent Consensus)

**Hedef:** Çelişen ajan analizleri üzerinde consensus protokolü — güven skorlu nihai karar üretimi.
**Süre:** 2 hafta
**Önkoşul:** `CompanyContext` servisi, `agent_jobs.py`, LangGraph pipeline mevcut.

---

### 1. Gereksinimler Analizi

Problem: CFO ajanı "nakit riski düşük" derken Risk ajanı "kritik" diyebiliyor.
Kullanıcı hangisine güveneceğini bilmiyor.

Çözüm: Consensus engine — çelişen sinyalleri tespit et, ağırlıklı oylama yap,
anlaşmazlığı kullanıcıya şeffaf göster.

Kullanım senaryoları:

| Senaryo | Agent A | Agent B | Consensus |
|---------|---------|---------|-----------|
| Nakit riski | CFO: düşük | Risk: kritik | Weighted vote CFO 60% + Risk 40% |
| Büyüme tahmini | CFO: +%15 | CMO: +%8 | Farklı metrikler → context split |
| İşe alım | CHRO: evet | CFO: hayır (bütçe) | Hard conflict → escalate |

---

### 2. Backend API Design

Yeni endpoint'ler:

```
POST /api/v1/negotiation/consensus
     Body: { org_id, topic, agents: ["cfo","risk","cmo"],
             resolution: "weighted"|"majority"|"escalate" }
     Response: { agreement_score, winning_view, dissenting_views, evidence_map }

POST /api/v1/negotiation/debate
     Body: { org_id, topic, rounds: 3 }
     Response: yapılandırılmış tartışma — her ajan argüman sunar, karşı cevaplar

GET  /api/v1/negotiation/conflicts/{org_id}
     Response: aktif çelişkiler listesi (open + resolved)

POST /api/v1/negotiation/resolve/{conflict_id}
     Body: { resolution: "accept_cfo"|"accept_risk"|"custom", note: str }
     Response: conflict resolved olarak işaretlenir
```

Yeni dosyalar:

```
backend/app/services/negotiation/
├── consensus_engine.py       ← Ana consensus protokolü
├── conflict_detector.py      ← Çelişki tespiti (threshold tabanlı)
├── debate_moderator.py       ← LLM tabanlı yapılandırılmış tartışma
└── resolution_store.py       ← Çözüm geçmişi (Redis TTL + DB)

backend/app/models/
└── agent_conflict.py         ← Yeni DB modeli

backend/app/api/
└── negotiation.py            ← Router

backend/alembic/versions/
└── 016_agent_conflicts.py
```

ConsensusEngine mimarisi:

```python
# backend/app/services/negotiation/consensus_engine.py

class ConsensusEngine:
    """
    Multi-agent consensus protokolü.

    Adımlar:
    1. CompanyContext'ten ilgili agent sonuçlarını çek
    2. ConflictDetector ile çelişen claim'leri tespit et
    3. Claim'leri kanıt + confidence ile ağırlıklandır
    4. WeightedVoting / MajorityVoting / EscalateToHuman
    5. ConsensusResult üret + CompanyContext'e kaydet

    Topic bazlı ağırlıklar:
    cash_risk:       cfo=0.45, risk=0.40, audit=0.15
    growth_forecast: cfo=0.35, cmo=0.40, ceo=0.25
    headcount:       chro=0.50, cfo=0.35, coo=0.15
    tech_risk:       cto=0.50, risk=0.30, cfo=0.20
    """
    TOPIC_WEIGHTS: dict[str, dict[str, float]] = {
        "cash_risk":       {"cfo": 0.45, "risk": 0.40, "audit": 0.15},
        "growth_forecast": {"cfo": 0.35, "cmo": 0.40, "ceo": 0.25},
        "headcount":       {"chro": 0.50, "cfo": 0.35, "coo": 0.15},
        "tech_risk":       {"cto": 0.50, "risk": 0.30, "cfo": 0.20},
    }

    async def run_consensus(
        self, org_id: str, topic: str,
        resolution_mode: Literal["weighted", "majority", "escalate"],
    ) -> ConsensusResult: ...

    def _detect_conflicts(
        self, claims: dict[str, AgentClaim]
    ) -> list[Conflict]: ...

    async def _llm_arbitrate(
        self, conflict: Conflict, context: dict
    ) -> ArbitrationResult:
        # GPT-4o: iki ajan görüşü arasında hakem
        ...
```

DB modeli:

```python
# backend/app/models/agent_conflict.py
class AgentConflict(Base):
    __tablename__ = "agent_conflicts"

    id              = Column(UUID, primary_key=True, default=uuid4)
    org_id          = Column(UUID, nullable=False, index=True)
    topic           = Column(String(100))       # "cash_risk"
    agent_a         = Column(String(50))         # "cfo"
    agent_b         = Column(String(50))         # "risk"
    claim_a         = Column(JSONB)
    claim_b         = Column(JSONB)
    consensus_score = Column(Float)              # 0–1 agreement level
    resolution      = Column(JSONB)
    status          = Column(String(20), default="open")  # open|resolved|escalated
    created_at      = Column(TIMESTAMPTZ, default=utcnow)
    resolved_at     = Column(TIMESTAMPTZ, nullable=True)
```

---

### 3. Frontend Component Blueprint

```
frontend/src/app/(dashboard)/negotiation/
└── page.tsx                     ← Conflict center

frontend/src/components/negotiation/
├── ConflictCard.tsx             ← A vs B görsel karşılaştırma (yan yana)
├── ConsensusGauge.tsx           ← 0–100 agreement gauge (RadialBar)
├── DebateTimeline.tsx           ← Ajan argümanları zaman çizelgesi
├── ResolutionPanel.tsx          ← Kullanıcı karar paneli
└── AgentWeightEditor.tsx        ← Admin: topic bazlı ajan ağırlık ayarı

frontend/src/hooks/
└── useNegotiation.ts            ← Consensus API + real-time updates

frontend/src/lib/api/
└── negotiation.ts               ← Typed API client
```

ConflictCard tasarım:

```tsx
// Yan yana iki kolon: CFO görüşü | Risk görüşü
// Ortada: "vs" badge + agreement score
// Alt: collapsible kanıt listesi
// Aksiyon butonları: "CFO'yu kabul et" | "Risk'i kabul et" | "Daha fazla analiz iste"

interface ConflictCardProps {
  conflict: AgentConflict;
  onResolve: (resolution: ResolutionChoice) => void;
}
```

---

### 4. Testing Stratejisi

```python
# backend/tests/test_negotiation/
├── test_conflict_detector.py
│   ├── test_detects_cash_risk_conflict()       # CFO low + Risk critical
│   ├── test_no_conflict_on_agreement()
│   └── test_partial_conflict_threshold()       # %30 fark altı → conflict değil
│
├── test_consensus_engine.py
│   ├── test_weighted_vote_correct_winner()
│   ├── test_majority_vote_3_agents()
│   ├── test_escalate_on_tie()
│   └── test_topic_weights_sum_to_one()
│
└── test_negotiation_api.py
    ├── test_consensus_endpoint_200()
    └── test_conflict_list_scoped_to_org()
```

Done-when kriterleri:
- [ ] `POST /negotiation/consensus` → `agreement_score` (0–1) + `winning_view` + `dissenting_views`
- [ ] CFO vs Risk çelişkisi → DB'ye conflict kaydediliyor
- [ ] `ConflictCard` iki görüşü yan yana render ediyor, resolve butonları çalışıyor
- [ ] "CFO'yu kabul et" → conflict `resolved` statüsüne geçiyor
- [ ] `pytest backend/tests/test_negotiation/ -q` → 0 hata

---

### 5. Deployment Checklist

```yaml
pre_deploy:
  - [ ] Migration 016 staging'de test edildi
  - [ ] LLM arbitration prompt güvenlik review (hallucination riski)
  - [ ] Feature flag: ENABLE_AGENT_NEGOTIATION=true
  - [ ] Topic weight config env'den okunuyor (CONSENSUS_WEIGHTS_JSON)

deploy:
  - [ ] alembic upgrade head (016)
  - [ ] Smoke test: POST /negotiation/consensus → 200

post_deploy:
  - [ ] İlk 10 org için conflict detection oranı izle
  - [ ] LLM arbitration token kullanımı Sentry'de izle (maliyet)
  - [ ] P95 consensus latency < 5s (LLM call içeriyor)
  - [ ] Conflict resolution rate haftalık dashboard'da izle
```

---

## Sprint L3 — Compliance & Audit (GDPR, SOX)

**Hedef:** Mevcut KVKK/GDPR endpoint'lerini SOX ve ISO 27001 kontrollerine genişlet; otomatik compliance rapor üretimi ekle.
**Süre:** 2 hafta
**Önkoşul:** `compliance.py`, `compliance_gdpr.py`, `audit_compliance_kernel.py` mevcut.

---

### 1. Gereksinimler Analizi

Mevcut olanlar:
- KVKK/GDPR: data inventory, erasure request, data export, retention report (`compliance_gdpr.py`)
- SOC2/ISO/GDPR framework listesi `health-check`'te var (sadece liste, implementasyon yok)
- `audit_compliance_kernel.py` — Türkiye mevzuatı uyum değerlendirmesi
- `RETENTION_POLICY` dict tanımlı, auto-deletion TODO olarak işaretli

Eksikler:

| Framework | Mevcut | Hedef |
|-----------|--------|-------|
| GDPR | Temel endpoint'ler | Article 25 (privacy by design), Article 30 (processing records), Article 33 (breach 72h) |
| SOX | Yok | Section 302 (CEO/CFO certification), 404 (internal controls), 409 (real-time disclosure) |
| ISO 27001 | Yok | Annex A kontrolleri, risk assessment, ISMS scope |
| Audit trail | Middleware var | Query-able audit log + compliance mapping |
| Otomatik raporlama | Yok | Scheduled compliance report + email digest |

---

### 2. Backend API Design

Yeni endpoint'ler:

```
GET  /api/v1/compliance/sox/status
     Response: SOX Section 302/404/409 uyum durumu + açık bulgular

POST /api/v1/compliance/sox/certify
     Body: { period, certifier_name, certifier_role, statements: [...] }
     Response: signature_hash + certification record

GET  /api/v1/compliance/gdpr/article30-register
     Response: Article 30 — veri işleme faaliyetleri kayıt defteri

POST /api/v1/compliance/gdpr/breach-notification
     Body: { description, affected_users, discovered_at, severity }
     Response: breach_id + 72h deadline tracker

GET  /api/v1/compliance/iso27001/controls
     Query: ?domain=access_control|cryptography|incident_management
     Response: Annex A kontrol listesi + uyum durumu

POST /api/v1/compliance/report/generate
     Body: { org_id, framework: "gdpr"|"sox"|"iso27001"|"all", period }
     Response: job_id (async → SSE stream)

GET  /api/v1/compliance/dashboard/{org_id}
     Response: tüm framework'ler için özet skor + kritik açıklar
```

Yeni dosyalar:

```
backend/app/services/compliance/
├── sox_assessor.py          ← SOX Section 302/404/409
├── gdpr_article30.py        ← Processing records otomatik oluşturma
├── iso27001_checker.py      ← Annex A kontrol değerlendirmesi
├── compliance_scorer.py     ← Cross-framework birleşik skor
└── breach_tracker.py        ← GDPR Article 33 — 72h deadline yönetimi

backend/app/models/
└── compliance_record.py     ← Sertifikasyon + breach kayıtları

backend/alembic/versions/
└── 017_compliance_extended.py
```

SOXAssessor mimarisi:

```python
# backend/app/services/compliance/sox_assessor.py
class SOXAssessor:
    """
    Section 302 — CEO/CFO Certification:
      Finansal raporların doğruluğunu beyan eder; iç kontrol etkinliğini onaylar.

    Section 404 — Internal Controls:
      Material weakness = kritik anomaly 30+ gün unacknowledged
      Significant deficiency = medium anomaly cluster

    Section 409 — Real-time Disclosure:
      Tetikleyiciler: kritik anomaly, nakit riski, büyük işlem (>%10 gelir)
      Süre: 4 iş günü içinde açıklama yükümlülüğü
    """
    async def assess_section_302(self, org_id: str, period: str) -> SOXSection302Result: ...

    async def assess_section_404(
        self, org_id: str, cfo_data: dict, anomalies: list[dict],
    ) -> SOXSection404Result:
        # internal_control_gaps = unacknowledged critical anomaly count
        ...

    async def check_section_409_triggers(self, org_id: str) -> list[SOXDisclosureTrigger]: ...
```

BreachTracker mimarisi:

```python
# backend/app/services/compliance/breach_tracker.py
class BreachTracker:
    """
    GDPR Article 33: 72 saatlik ihlal bildirimi takibi.
    Breach kaydedilir → 71. saatte ARQ reminder task → overdue alert.
    """
    async def register_breach(self, breach: BreachNotification) -> BreachRecord:
        deadline = breach.discovered_at + timedelta(hours=72)
        # ARQ scheduled task: 71. saatte InAppNotification gönder
        ...

    async def get_overdue_breaches(self, org_id: str) -> list[BreachRecord]: ...
```

DB schema eklemeleri:

```sql
-- Migration: 017_compliance_extended.py

CREATE TABLE compliance_certifications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL,
    framework       VARCHAR(20),       -- 'sox_302', 'sox_404'
    period          VARCHAR(20),       -- '2024-Q2'
    certifier_name  VARCHAR(200),
    certifier_role  VARCHAR(100),
    statements      JSONB,
    signature_hash  VARCHAR(64),       -- SHA-256 of statements
    certified_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE breach_notifications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL,
    description     TEXT,
    severity        VARCHAR(20),       -- 'low'|'medium'|'high'|'critical'
    affected_users  INT,
    discovered_at   TIMESTAMPTZ,
    deadline_72h    TIMESTAMPTZ,
    notified_at     TIMESTAMPTZ,
    status          VARCHAR(20) DEFAULT 'pending',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_breach_notifications_org ON breach_notifications(org_id);
CREATE INDEX idx_compliance_certifications_org ON compliance_certifications(org_id, framework);
```

---

### 3. Frontend Component Blueprint

```
frontend/src/app/(dashboard)/compliance/
├── page.tsx                      ← Compliance dashboard hub
├── sox/page.tsx                  ← SOX Section 302/404/409 detay
├── gdpr/page.tsx                 ← GDPR inventory + breach tracker
└── iso27001/page.tsx             ← ISO 27001 Annex A kontrol listesi

frontend/src/components/compliance/
├── ComplianceScoreRing.tsx       ← Framework bazlı donut score (0–100)
├── SOXCertificationForm.tsx      ← CEO/CFO imzalama formu (React Hook Form + Zod)
├── BreachTimeline.tsx            ← Breach listesi + 72h countdown
├── ControlChecklistTable.tsx     ← ISO 27001 Annex A kontrolleri tablo
├── GDPRArticle30Register.tsx     ← Veri işleme kayıt defteri görünümü
└── ComplianceDashboardCard.tsx   ← Tek framework özet kartı

frontend/src/hooks/
└── useCompliance.ts              ← Compliance API calls + polling

frontend/src/lib/api/
└── compliance_extended.ts        ← Yeni endpoint'ler typed client
```

SOXCertificationForm tasarım:

```tsx
// CEO/CFO sertifikasyon akışı:
// 1. Dönem seçimi (quarter picker)
// 2. Certification statements (checkbox listesi — SOX 302 maddeleri)
// 3. İmzalayan adı + rolü
// 4. "Sertifika İmzala" → POST /compliance/sox/certify → signature_hash göster
// 5. PDF indirme (M2 sprintiyle entegre)

const certificationSchema = z.object({
  period: z.string(),
  certifier_name: z.string().min(3),
  certifier_role: z.enum(["CEO", "CFO", "Audit Committee"]),
  statements: z.array(z.boolean()).length(5).refine(s => s.every(Boolean)),
});
```

BreachTimeline tasarım:

```tsx
// Her breach için:
// - Severity badge (critical/high/medium/low)
// - Discovered at + Deadline countdown (red if < 12h)
// - Status: pending / notified / overdue
// - "Bildirimi Kaydet" butonu (notified_at günceller)
```

---

### 4. Testing Stratejisi

```python
# backend/tests/test_compliance/
├── test_sox_assessor.py
│   ├── test_section_302_creates_certification()
│   ├── test_section_404_detects_material_weakness()  # critical anomaly > 30d
│   ├── test_section_409_triggers_on_large_transaction()
│   └── test_signature_hash_deterministic()
│
├── test_breach_tracker.py
│   ├── test_breach_registers_72h_deadline()
│   ├── test_overdue_breach_detected_after_72h()
│   └── test_notified_at_clears_overdue_status()
│
├── test_iso27001.py
│   ├── test_annex_a_controls_complete()   # tüm domain'ler mevcut
│   └── test_control_status_mapping()
│
└── test_compliance_endpoints.py
    ├── test_sox_status_200()
    ├── test_certify_creates_record()
    ├── test_breach_notification_sets_deadline()
    └── test_compliance_dashboard_all_frameworks()
```

Done-when kriterleri:
- [ ] `POST /compliance/sox/certify` → `signature_hash` + DB'de certification record
- [ ] Breach kaydedilince `deadline_72h` otomatik hesaplanıyor
- [ ] `GET /compliance/dashboard/{org_id}` → GDPR + SOX + ISO 27001 için score
- [ ] `ComplianceScoreRing` 3 framework için render ediyor
- [ ] `SOXCertificationForm` validation + submit çalışıyor
- [ ] `pytest backend/tests/test_compliance/ -q` → 0 hata

---

### 5. Deployment Checklist

```yaml
pre_deploy:
  - [ ] Migration 017 staging'de test edildi
  - [ ] Breach tracker ARQ job test edildi (72h timer mock ile)
  - [ ] SOX certification PDF şablonu hazır (M2 sprintiyle koordine)
  - [ ] Feature flag: ENABLE_SOX_COMPLIANCE=true

deploy:
  - [ ] alembic upgrade head (017)
  - [ ] Smoke test: GET /compliance/dashboard/{test_org_id} → 200

post_deploy:
  - [ ] Açık breach notification'ları için backfill çalıştır
  - [ ] GDPR Article 30 register ilk 5 org için doğrula
  - [ ] SOX 409 trigger threshold ayarı (default: %10 gelir değişimi)
  - [ ] Retention policy auto-deletion cron job ekle (TODO'yu kapat)
```

---

## Sprint M1 — Real-time Alerts (WebSocket İyileştirmeleri)

**Hedef:** Mevcut SSE + WebSocket altyapısını multi-channel alert delivery sistemine dönüştür; alert önceliklendirme ve acknowledgement akışını güçlendir.
**Süre:** 1.5 hafta
**Önkoşul:** `streaming/sse.py`, `alerts.py`, `notification-bell.tsx`, `ws-chat-panel.tsx` mevcut.

---

### 1. Gereksinimler Analizi

Mevcut durum:
- SSE: job bazlı `subscribe(job_id)` — pipeline progress için çalışıyor
- WebSocket: chat panel için ayrı `ws-chat-panel.tsx` var
- Alert digest: job tabanlı, HTTP polling (GET /alerts/digest)
- InAppNotification modeli var, DB'ye yazılıyor
- `notification-bell.tsx` badge + dropdown mevcut
- Alert acknowledgement Redis'e yazıyor (24h TTL, DB'ye gitmiyor)

Eksikler:

| Alan | Mevcut | Hedef |
|------|--------|-------|
| Alert delivery | HTTP polling | WebSocket push (org bazlı broadcast) |
| Alert persistence | Redis TTL | DB'ye kalıcı kayıt |
| Slack/Email routing | Stub | Gerçek webhook gönderimi |
| Alert önceliklendirme | Score tabanlı (alerts.py) | UI'da drag-reorder + mute |
| Multi-channel | Sadece in-app | in-app + Slack + Email + webhook |
| Alert rules | Yok | Kullanıcı tanımlı alert kuralları |

---

### 2. Backend API Design

Yeni ve değiştirilecek endpoint'ler:

```
WebSocket: ws://api/v1/ws/alerts/{org_id}
  → Org bazlı alert channel — tüm org üyeleri dinler
  → Event türleri: new_alert, alert_acknowledged, alert_resolved
  → Auth: JWT query param (?token=...)

POST /api/v1/alerts/rules
     Body: { name, condition: { metric, operator, threshold }, channels: [...], severity }
     Response: alert rule oluşturulur

GET  /api/v1/alerts/rules
     Response: org'un alert rule listesi

DELETE /api/v1/alerts/rules/{rule_id}

POST /api/v1/alerts/channels/test
     Body: { channel: "slack"|"email"|"webhook", destination }
     Response: test mesajı gönderildi mi?

GET  /api/v1/alerts/history/{org_id}
     Query: ?severity=critical&days=7&acknowledged=false
     Response: alert geçmişi (DB kalıcı)

PATCH /api/v1/alerts/{alert_id}/acknowledge
     Body: { note?: str }
     Response: alert DB'de acknowledged=true olarak güncellenir
```

Yeni dosyalar:

```
backend/app/services/
├── ws_alert_manager.py      ← WebSocket org-channel yönetimi
├── alert_delivery.py        ← Slack + Email + webhook gönderimi
└── alert_rules_engine.py    ← Kural değerlendirme motoru

backend/app/models/
├── alert_rule.py            ← Kullanıcı tanımlı alert kuralları
└── alert_history.py         ← Kalıcı alert log (Redis TTL yerine)

backend/app/api/
└── ws_alerts.py             ← WebSocket router

backend/alembic/versions/
└── 018_alert_tables.py
```

WebSocket Alert Manager:

```python
# backend/app/services/ws_alert_manager.py
class WSAlertManager:
    """
    Org bazlı WebSocket broadcast — SSEManager'ın WS karşılığı.

    Mevcut SSE: job-scoped (pipeline progress)
    Bu servis: org-scoped (alert push) — farklı amaç, paralel çalışır.

    Bağlantı: ws://.../ws/alerts/{org_id}?token={jwt}
    Mesaj formatı:
      { "type": "new_alert", "alert": {...}, "ts": "..." }
      { "type": "alert_acknowledged", "alert_id": "...", "by": "user@..." }
    """
    def __init__(self):
        # org_id → set of WebSocket connections
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, org_id: str, ws: WebSocket) -> None: ...
    async def disconnect(self, org_id: str, ws: WebSocket) -> None: ...

    async def broadcast_alert(self, org_id: str, alert: dict) -> None:
        """Org'daki tüm bağlı kullanıcılara alert gönder."""
        ...

    async def broadcast_acknowledgement(
        self, org_id: str, alert_id: str, by_user: str
    ) -> None: ...
```

Alert Delivery Service:

```python
# backend/app/services/alert_delivery.py
class AlertDeliveryService:
    """
    Multi-channel alert gönderimi.
    Mevcut AlertRouter (dedup + aggregation) çıktısını kanalara iletir.

    Kanallar:
    - in_app: WSAlertManager.broadcast_alert()
    - slack:  POST webhook URL (httpx async)
    - email:  Resend API (mevcut email servisi varsa entegre et)
    - webhook: Generic POST (custom URL, org tarafından ayarlanır)
    """
    async def deliver(self, alert: ProcessedAlert, org_id: str) -> DeliveryResult:
        prefs = await get_org_alert_prefs(org_id)
        results = []
        if "in_app" in prefs.channels:
            await self._deliver_in_app(alert, org_id)
        if "slack" in prefs.channels and prefs.slack_webhook:
            await self._deliver_slack(alert, prefs.slack_webhook)
        if "email" in prefs.channels and prefs.email_addresses:
            await self._deliver_email(alert, prefs.email_addresses)
        return DeliveryResult(channels=results)

    async def _deliver_slack(self, alert: ProcessedAlert, webhook_url: str) -> None:
        # Slack Block Kit formatı — renkli attachment + action button
        ...
```

Alert Rules Engine:

```python
# backend/app/services/alert_rules_engine.py
class AlertRulesEngine:
    """
    Kullanıcı tanımlı kuralları değerlendirir.

    Örnek kural:
    { "metric": "cash_runway_months", "operator": "<", "threshold": 3,
      "channels": ["slack", "in_app"], "severity": "critical" }

    Değerlendirme zamanı:
    - Her CFO analizi tamamlandığında
    - Her anomaly scan sonrasında
    """
    async def evaluate(self, org_id: str, context: dict) -> list[TriggeredAlert]: ...

    def _check_condition(
        self, rule: AlertRule, context: dict
    ) -> bool:
        value = self._extract_metric(rule.metric, context)
        return self._compare(value, rule.operator, rule.threshold)
```

DB schema:

```sql
-- Migration: 018_alert_tables.py

CREATE TABLE alert_rules (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL,
    name        VARCHAR(200),
    metric      VARCHAR(100),      -- 'cash_runway_months', 'anomaly_count_critical'
    operator    VARCHAR(10),       -- '<', '>', '==', '>='
    threshold   FLOAT,
    channels    TEXT[],            -- ['slack', 'email', 'in_app']
    severity    VARCHAR(20) DEFAULT 'warning',
    enabled     BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE alert_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL,
    rule_id         UUID REFERENCES alert_rules(id) ON DELETE SET NULL,
    message         TEXT,
    severity        VARCHAR(20),
    source          VARCHAR(50),
    channels_sent   TEXT[],
    acknowledged    BOOLEAN DEFAULT FALSE,
    acknowledged_by VARCHAR(200),
    acknowledged_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_alert_history_org_severity ON alert_history(org_id, severity);
CREATE INDEX idx_alert_history_unacked ON alert_history(org_id, acknowledged)
    WHERE acknowledged = FALSE;
```

---

### 3. Frontend Component Blueprint

```
frontend/src/app/(dashboard)/alerts/
├── page.tsx                     ← Alert history + rule yönetimi
└── rules/page.tsx               ← Alert kuralları CRUD

frontend/src/components/alerts/
├── AlertFeed.tsx                ← WebSocket ile real-time alert akışı
├── AlertRuleBuilder.tsx         ← Kural oluşturma formu (metric/operator/threshold)
├── AlertChannelConfig.tsx       ← Slack webhook + email ayarları
├── AlertHistoryTable.tsx        ← Filtrelenebilir alert geçmişi tablosu
└── AlertSeverityBadge.tsx       ← critical/high/medium/low badge (mevcut pattern)

frontend/src/hooks/
└── useAlertWebSocket.ts         ← WS bağlantısı + reconnect logic

frontend/src/lib/api/
└── alerts_v2.ts                 ← Yeni endpoint'ler typed client
```

`useAlertWebSocket` hook:

```typescript
// frontend/src/hooks/useAlertWebSocket.ts
// WebSocket bağlantısı, reconnect backoff, mesaj dispatch

interface AlertWebSocketState {
  status: "idle" | "connecting" | "connected" | "error" | "closed";
  alerts: AlertMessage[];           // son 50 alert (ring buffer)
  unreadCount: number;
  acknowledgeAlert: (id: string) => void;
}

export function useAlertWebSocket(orgId: string): AlertWebSocketState {
  // Exponential backoff reconnect: 1s → 2s → 4s → max 30s
  // Heartbeat ping her 20s
  // alerts array: FIFO, max 50, oldest drop edilir
  ...
}
```

`AlertFeed` tasarım:

```tsx
// Real-time feed — yeni alert gelince toast + feed'e eklenir
// Severity bazlı renk: critical=red, high=amber, medium=yellow, low=slate
// Acknowledge butonu: optimistic update + WS broadcast
// Empty state: "Aktif alert yok — sistem sağlıklı"
```

Mevcut `notification-bell.tsx` güncellemesi:
- HTTP polling yerine `useAlertWebSocket` hook'una bağlanır
- `unreadCount` WebSocket state'inden gelir
- Dropdown'da son 10 alert gösterilir

---

### 4. Testing Stratejisi

```python
# backend/tests/test_alerts/
├── test_ws_alert_manager.py
│   ├── test_connect_creates_org_channel()
│   ├── test_broadcast_reaches_all_connections()
│   ├── test_disconnect_removes_from_channel()
│   └── test_broadcast_empty_channel_no_error()
│
├── test_alert_delivery.py
│   ├── test_slack_delivery_posts_to_webhook()
│   ├── test_email_delivery_sends_to_list()
│   └── test_in_app_delivery_persists_to_db()
│
├── test_alert_rules_engine.py
│   ├── test_cash_runway_rule_triggers()
│   ├── test_threshold_not_exceeded_no_trigger()
│   └── test_disabled_rule_not_evaluated()
│
└── test_alert_history.py
    ├── test_acknowledge_updates_db()
    └── test_history_filtered_by_severity()
```

Frontend testler:

```typescript
// frontend/src/__tests__/
├── hooks/useAlertWebSocket.test.ts
│   ├── test reconnect on close
│   ├── test ring buffer max 50 alerts
│   └── test unreadCount increments on new alert
└── alerts/AlertFeed.test.tsx
    ├── renders empty state correctly
    └── shows new alert on WS message
```

Done-when kriterleri:
- [ ] WS endpoint `ws://.../ws/alerts/{org_id}` bağlantı kuruyor
- [ ] Yeni anomaly tamamlandığında WS push in-app'e geliyor (< 2s)
- [ ] Slack test gönderimi `/alerts/channels/test` üzerinden çalışıyor
- [ ] Alert rules UI'da kural oluşturulabiliyor + DB'ye kaydediliyor
- [ ] Alert history DB'de kalıcı (Redis TTL kaldırıldı)
- [ ] `notification-bell.tsx` WS'den unreadCount okuyor (polling kaldırıldı)
- [ ] `pytest backend/tests/test_alerts/ -q` → 0 hata

---

### 5. Deployment Checklist

```yaml
pre_deploy:
  - [ ] Migration 018 staging'de test edildi
  - [ ] Slack webhook test URL'i ile entegrasyon testi
  - [ ] WS load test: 100 concurrent connection / org
  - [ ] Feature flag: ENABLE_WS_ALERTS=true (fallback → SSE polling)

deploy:
  - [ ] alembic upgrade head (018)
  - [ ] WS endpoint smoke test: wscat bağlantı testi
  - [ ] Slack test message gönder

post_deploy:
  - [ ] Active WS connection sayısı Sentry'de izle
  - [ ] Alert delivery latency P95 < 2s
  - [ ] Unacknowledged critical alert SLA: < 5dk (izle + uyar)
  - [ ] Redis'teki eski ack key'leri temizle (migration script)
```

---

## Sprint M2 — Executive Reports (PDF Generation)

**Hedef:** C-suite için otomatik PDF rapor üretimi — board deck, CFO summary, compliance sertifikası.
**Süre:** 1.5 hafta
**Önkoşul:** `report_agent.py`, `analytics.py`, `compliance_gdpr.py`, `audit_compliance_kernel.py` mevcut.

---

### 1. Gereksinimler Analizi

Mevcut durum:
- `report_agent.py` — Excel raporu üretiyor (openpyxl)
- `ceo/BoardDeckViewer.tsx` — frontend'de board deck görünümü var (PDF değil)
- `OKRScorecard.tsx`, `SWOTWidget.tsx` — bileşenler var
- Compliance sertifikası (L3 sprint) PDF çıktı gerektiriyor

Eksikler:

| Rapor tipi | Mevcut | Hedef |
|-----------|--------|-------|
| CFO Summary | Excel | PDF (A4 branded) |
| Board Deck | HTML görünüm | PDF export (multi-page) |
| Compliance Cert | Yok | PDF + imza hash |
| Executive Brief | Yok | 1-sayfa C-level özet |
| Scheduled Report | Yok | Haftalık otomatik email |

---

### 2. Backend API Design

Yeni endpoint'ler:

```
POST /api/v1/reports/pdf/cfo-summary
     Body: { job_id, branding?: { logo_url, company_color } }
     Response: SSE stream → job_id, sonra GET /reports/{report_id}/download

POST /api/v1/reports/pdf/board-deck
     Body: { org_id, period, include_sections: ["pnl","cashflow","forecast","risks"] }
     Response: SSE stream → PDF hazır olunca download URL

POST /api/v1/reports/pdf/compliance-cert
     Body: { certification_id }   ← L3'ten gelen SOX/GDPR sertifikasyonu
     Response: imzalı PDF

POST /api/v1/reports/pdf/executive-brief
     Body: { org_id, max_pages: 1 }
     Response: tek sayfa C-suite özet PDF

POST /api/v1/reports/schedule
     Body: { org_id, report_type, frequency: "weekly"|"monthly", recipients: [...] }
     Response: schedule kaydedildi

GET  /api/v1/reports/schedule
     Response: org'un aktif rapor programları

DELETE /api/v1/reports/schedule/{schedule_id}
```

Yeni dosyalar:

```
backend/app/services/pdf/
├── pdf_engine.py           ← Weasyprint veya ReportLab seçimi + base renderer
├── cfo_summary_pdf.py      ← CFO summary şablonu
├── board_deck_pdf.py       ← Board deck multi-page şablonu
├── compliance_cert_pdf.py  ← Sertifikasyon PDF + QR kod (imza doğrulama)
└── executive_brief_pdf.py  ← 1-sayfa özet şablonu

backend/app/services/
└── report_scheduler.py     ← ARQ tabanlı haftalık/aylık gönderim

backend/app/models/
└── report_schedule.py      ← Zamanlanmış rapor konfigürasyonu

backend/alembic/versions/
└── 019_report_schedules.py
```

PDF Engine kararı:

```python
# backend/app/services/pdf/pdf_engine.py
"""
Seçim: WeasyPrint (HTML→PDF) — Jinja2 şablonları + CSS styling
Alternatif: ReportLab (programmatic) — daha fazla kod, daha az esneklik

WeasyPrint tercih nedenleri:
- Mevcut Tailwind/CSS bilgisiyle şablon yazılabilir
- HTML şablonları version control'da okunabilir
- Recharts chart → SVG → PDF embed edilebilir
- Türkçe karakter desteği (otomatik font embedding)

Bağımlılık: weasyprint>=62.0 (Docker'da libpango1.0-dev gerektirir)
"""

class PDFEngine:
    def __init__(self, template_dir: Path): ...

    async def render(
        self,
        template_name: str,
        context: dict,
        output_path: Path | None = None,
    ) -> bytes:
        # Jinja2 → HTML → WeasyPrint → PDF bytes
        ...
```

CFO Summary PDF şablonu içeriği:

```
Sayfa 1: Cover — şirket adı, dönem, hazırlayan, tarih
Sayfa 2: Executive Summary — top 3 KPI, top 3 alert, risk seviyesi
Sayfa 3: P&L — gelir/gider tablosu + gross margin chart (SVG)
Sayfa 4: Cash Flow — nakit akış tablosu + runway bar chart
Sayfa 5: Forecast — 6 aylık tahmin + P10/P50/P90 band
Sayfa 6: Anomalies — kritik + yüksek anomaly listesi
Sayfa 7: Recommendations — top 5 aksiyon maddesi
```

Board Deck şablonu:

```
16:9 landscape format (sunum formatı)
Slide 1:  Cover
Slide 2:  Agenda
Slide 3:  Financial Highlights (3 KPI)
Slide 4:  P&L Overview
Slide 5:  Cash Position & Runway
Slide 6:  Growth & Forecast
Slide 7:  Risk Heatmap
Slide 8:  Key Actions
```

---

### 3. Frontend Component Blueprint

```
frontend/src/app/(dashboard)/reports/
├── page.tsx                        ← Rapor listesi + oluşturma
└── schedule/page.tsx               ← Zamanlanmış raporlar

frontend/src/components/reports/
├── PDFGeneratorCard.tsx            ← Rapor tipi seçimi + parametreler + oluştur butonu
├── PDFPreviewModal.tsx             ← iframe embed PDF preview
├── ReportScheduleForm.tsx          ← Frekans + alıcılar formu
├── ReportHistoryTable.tsx          ← Geçmiş raporlar + indirme linkleri
└── BrandingConfigPanel.tsx         ← Logo URL + renk ayarları

frontend/src/hooks/
└── usePDFGeneration.ts             ← SSE stream + download trigger

frontend/src/lib/api/
└── reports_pdf.ts                  ← Typed API client
```

`PDFGeneratorCard` tasarım:

```tsx
// Rapor tipi seçimi: CFO Summary | Board Deck | Compliance Cert | Executive Brief
// Parametre formu (tip bazlı dinamik): dönem, bölümler, branding
// "PDF Oluştur" → SSE bağlan → progress bar
// Tamamlandığında: "PDF İndir" butonu + preview modal

interface PDFGeneratorCardProps {
  defaultType?: "cfo_summary" | "board_deck" | "compliance_cert" | "executive_brief";
  onGenerated?: (reportId: string, downloadUrl: string) => void;
}
```

`usePDFGeneration` hook:

```typescript
// SSE stream → progress (0–100) → download URL
// Hata durumunda retry (max 2)
// Tamamlanan rapor URL'i localStorage'da cache (30dk)

export function usePDFGeneration() {
  const generate = async (params: PDFGenerateParams) => {
    // POST → job_id → SSE subscribe → done → download URL
  };
  return { generate, progress, downloadUrl, isGenerating, error };
}
```

---

### 4. Testing Stratejisi

```python
# backend/tests/test_reports/
├── test_pdf_engine.py
│   ├── test_render_cfo_summary_returns_bytes()
│   ├── test_render_board_deck_multipage()
│   ├── test_turkish_characters_encoded()
│   └── test_svg_chart_embedded_in_pdf()
│
├── test_report_scheduler.py
│   ├── test_weekly_schedule_creates_arq_job()
│   ├── test_monthly_schedule_correct_next_run()
│   └── test_schedule_delete_cancels_job()
│
└── test_pdf_endpoints.py
    ├── test_cfo_summary_endpoint_returns_job_id()
    ├── test_board_deck_streams_progress()
    └── test_compliance_cert_includes_signature_hash()
```

Done-when kriterleri:
- [ ] `POST /reports/pdf/cfo-summary` → PDF bytes (valid, openable)
- [ ] Türkçe karakter (ğ, ş, ı) PDF'de görünüyor
- [ ] Board deck 16:9 landscape formatında üretiliyor
- [ ] Compliance sertifikasında signature_hash + QR kod var
- [ ] `ReportScheduleForm` submit → DB'ye schedule kaydediliyor
- [ ] Haftalık ARQ job email gönderiyor (test mode)
- [ ] `pytest backend/tests/test_reports/ -q` → 0 hata

---

### 5. Deployment Checklist

```yaml
pre_deploy:
  - [ ] weasyprint Docker image'a eklendi (libpango bağımlılığı)
  - [ ] Migration 019 staging'de test edildi
  - [ ] PDF şablonları design review'dan geçti
  - [ ] Branding config env: DEFAULT_REPORT_LOGO_URL

deploy:
  - [ ] alembic upgrade head (019)
  - [ ] Smoke test: POST /reports/pdf/executive-brief → valid PDF

post_deploy:
  - [ ] PDF generation P95 latency < 15s (kabul edilebilir sınır)
  - [ ] PDF boyutu P95 < 5MB (büyük rapor için)
  - [ ] Haftalık email zamanlamasını prod'da verify et (ARQ log)
  - [ ] Branding logo URL güvenlik check (SSRF koruması — allowlist)
```

---

## Sprint M3 — API Rate Limiting & Caching

**Hedef:** Mevcut rate limit middleware'i katmanlı sisteme yükselt; Redis tabanlı akıllı caching ile pahalı LLM/ML çağrılarını optimize et.
**Süre:** 1 hafta
**Önkoşul:** `middleware/rate_limit.py` mevcut, Redis ✅, `analytics.py` endpoint'leri mevcut.

---

### 1. Gereksinimler Analizi

Mevcut durum:
- `middleware/rate_limit.py` — `RateLimitMiddleware` mevcut (PLAN.md'de bahsedilen)
- Redis mevcut (ARQ worker aynı instance kullanıyor)
- LLM çağrıları her request'te fresh (cache yok)
- Endpoint bazlı limit konfigürasyonu yok
- Plan bazlı (free/pro/enterprise) limit farklılaştırması yok

Eksikler:

| Alan | Mevcut | Hedef |
|------|--------|-------|
| Rate limiting | Global middleware | Endpoint + plan bazlı katmanlı |
| LLM cache | Yok | Redis semantic cache (ttl=1saat) |
| Analytics cache | Yok | Query sonuçları Redis'te (ttl=15dk) |
| Cache invalidation | Yok | CFO analizi bitince ilgili cache temizle |
| Rate limit response | Generic 429 | Retry-After header + kalan limit bilgisi |
| Burst allowance | Yok | Token bucket algorithm |

---

### 2. Backend API Design

Yeni endpoint'ler:

```
GET  /api/v1/system/rate-limit-status
     Response: { limit, remaining, reset_at, plan }
     Header: X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset

GET  /api/v1/system/cache-stats
     Query: ?namespace=analytics|llm|context
     Response: hit_rate, miss_rate, key_count, memory_bytes (admin only)

POST /api/v1/system/cache-invalidate
     Body: { namespace, key_pattern? }
     Response: invalidated_count (admin only)
```

Güncellenen middleware:

```python
# backend/app/middleware/rate_limit.py — mevcut dosyayı güçlendir

class RateLimitConfig:
    """
    Endpoint + plan bazlı rate limit konfigürasyonu.
    
    Token bucket algoritması:
    - Her istek 1 token tüketir
    - Bucket, rate/saniye ile dolar
    - Burst: kısa süreli yoğunluğa izin verir
    
    Plan sınırları:
    free:       60 req/saat, 10 req/dk burst
    pro:        600 req/saat, 60 req/dk burst
    enterprise: 6000 req/saat, 300 req/dk burst
    """
    
    PLAN_LIMITS: dict[str, dict] = {
        "free":       {"per_hour": 60,   "burst": 10,  "llm_per_day": 10},
        "pro":        {"per_hour": 600,  "burst": 60,  "llm_per_day": 100},
        "enterprise": {"per_hour": 6000, "burst": 300, "llm_per_day": 1000},
    }
    
    # Endpoint-specific overrides (pahalı endpoint'ler için daha düşük limit)
    ENDPOINT_MULTIPLIERS: dict[str, float] = {
        "/api/v1/analysis":              0.1,   # ağır LLM call — 10x daha kısıtlı
        "/api/v1/analytics/monte-carlo": 0.2,
        "/api/v1/analytics/advanced-anomaly": 0.2,
        "/api/v1/reports/pdf":           0.1,
        "/api/v1/negotiation/debate":    0.1,
    }
```

Cache Service mimarisi:

```python
# backend/app/services/cache_service.py

class CacheService:
    """
    Katmanlı Redis cache stratejisi.

    Namespace'ler ve TTL'ler:
    - analytics:{org_id}:{endpoint_hash}  → 15 dakika
    - llm:{prompt_hash}                   → 60 dakika
    - context:{org_id}                    → 5 dakika (mevcut CompanyContext)
    - benchmark:{sector}                  → 24 saat
    - tcmb:{date}                         → 6 saat (makro veri günde bir güncellenir)

    Cache invalidation:
    - CFO analizi tamamlandığında: context:{org_id} + analytics:{org_id}:* temizle
    - Yeni connector sync: analytics:{org_id}:* temizle
    """

    def __init__(self, redis_pool):
        self._redis = redis_pool

    async def get(self, key: str) -> dict | None: ...
    async def set(self, key: str, value: dict, ttl: int) -> None: ...
    async def invalidate_pattern(self, pattern: str) -> int:
        # Redis SCAN + DEL — büyük keyspace'de güvenli
        ...

    def make_key(self, namespace: str, *parts: str) -> str:
        return f"cache:{namespace}:{':'.join(parts)}"
```

LLM Cache Decorator:

```python
# backend/app/services/cache_service.py

def llm_cached(ttl: int = 3600):
    """
    LLM çağrısını cache'ler.
    Cache key: prompt içeriğinin SHA-256 hash'i (ilk 16 karakter).

    Kullanım:
    @llm_cached(ttl=3600)
    async def analyze_pnl(prompt: str) -> str:
        return await openai_call(prompt)
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            prompt_key = _hash_prompt(args, kwargs)
            cached = await cache_service.get(f"llm:{prompt_key}")
            if cached:
                return cached["result"]
            result = await func(*args, **kwargs)
            await cache_service.set(f"llm:{prompt_key}", {"result": result}, ttl)
            return result
        return wrapper
    return decorator
```

Analytics Cache Middleware:

```python
# backend/app/middleware/analytics_cache.py

class AnalyticsCacheMiddleware:
    """
    GET /analytics/* endpoint'leri için response cache.
    
    Cache key: {org_id}:{path}:{sorted_query_params}
    TTL: 15 dakika (analytics verisi çok sık değişmez)
    
    Cache bypass:
    - ?refresh=true query param
    - POST request'ler (state değiştiriyor)
    - Admin kullanıcılar
    
    Cache invalidation trigger:
    - POST /analysis (yeni CFO analizi) → org bazlı cache temizle
    - POST /analytics/advanced-anomaly → ilgili job cache temizle
    """
```

---

### 3. Frontend Component Blueprint

```
frontend/src/app/(dashboard)/settings/
└── api-limits/page.tsx              ← Rate limit durumu + plan bilgisi

frontend/src/components/settings/
├── RateLimitStatusCard.tsx          ← Mevcut kullanım gauge + reset time
├── CacheStatsPanel.tsx              ← Admin: namespace bazlı hit/miss oranları
└── PlanUpgradePrompt.tsx            ← Limit aşımında plan yükseltme CTA

frontend/src/hooks/
└── useRateLimitStatus.ts            ← Polling (30s) + 429 intercept

frontend/src/lib/api/client.ts       ← Mevcut Axios instance — rate limit header'ları ekle
```

API Client güncelleme:

```typescript
// frontend/src/lib/api/client.ts — mevcut interceptor'a ekle

// Rate limit response interceptor
apiClient.interceptors.response.use(
  (response) => {
    // Header'lardan rate limit bilgisini store'a yaz
    const remaining = response.headers["x-ratelimit-remaining"];
    const resetAt   = response.headers["x-ratelimit-reset"];
    if (remaining !== undefined) {
      rateLimitStore.update({ remaining: parseInt(remaining), resetAt });
    }
    return response;
  },
  (error) => {
    if (error.response?.status === 429) {
      const retryAfter = error.response.headers["retry-after"];
      // Toast: "İstek limitine ulaşıldı. X saniye sonra tekrar deneyin."
      toast.warning(`Rate limit: ${retryAfter}s sonra tekrar deneyin`);
      // Zustand/store'a kaydet — tüm butonları disable et
    }
    return Promise.reject(error);
  }
);
```

`RateLimitStatusCard` tasarım:

```tsx
// Gauge: remaining/limit (yeşil → sarı → kırmızı)
// Reset countdown timer
// Plan badge: Free / Pro / Enterprise
// Endpoint bazlı en çok tüketen 3 endpoint listesi
// "Plan Yükselt" CTA (limit < %20 ise göster)
```

---

### 4. Testing Stratejisi

```python
# backend/tests/test_rate_limit/
├── test_token_bucket.py
│   ├── test_burst_allows_short_spike()
│   ├── test_bucket_refills_over_time()
│   └── test_endpoint_multiplier_reduces_limit()
│
├── test_cache_service.py
│   ├── test_cache_get_miss_returns_none()
│   ├── test_cache_set_get_roundtrip()
│   ├── test_ttl_expires_key()
│   ├── test_invalidate_pattern_removes_matching()
│   └── test_llm_cached_decorator_hits_on_second_call()
│
├── test_analytics_cache_middleware.py
│   ├── test_get_analytics_cached_on_second_request()
│   ├── test_refresh_param_bypasses_cache()
│   ├── test_post_request_not_cached()
│   └── test_new_analysis_invalidates_org_cache()
│
└── test_rate_limit_headers.py
    ├── test_response_includes_ratelimit_headers()
    ├── test_429_includes_retry_after()
    └── test_plan_limits_applied_correctly()
```

Load test senaryosu:

```bash
# k6 load test — rate limit doğrulama
# free plan: 60 req/saat → 61. request 429 döndürmeli
# burst: 10 req/10s → 11. request 429 döndürmeli

k6 run \
  -e PLAN=free \
  -e TARGET_URL=http://localhost:8000 \
  backend/tests/load/rate_limit_test.js
```

Done-when kriterleri:
- [ ] Free plan: 61. request → 429 + Retry-After header
- [ ] LLM cache: aynı prompt 2. çağrısı Redis'ten dönüyor (latency < 10ms)
- [ ] Analytics cache: GET /analytics/macro → 2. çağrı cache hit (X-Cache: HIT header)
- [ ] CFO analizi bitince `analytics:{org_id}:*` cache temizleniyor
- [ ] `RateLimitStatusCard` gauge'ı doğru remaining gösteriyor
- [ ] 429 alındığında toast gösteriliyor + butonlar disable ediliyor
- [ ] `pytest backend/tests/test_rate_limit/ -q` → 0 hata

---

### 5. Deployment Checklist

```yaml
pre_deploy:
  - [ ] Redis memory limit prod'da ayarlı (maxmemory-policy allkeys-lru)
  - [ ] Cache key naming convention dokümante edildi
  - [ ] Plan limit config env'den okunuyor (RATE_LIMIT_FREE_PER_HOUR=60)
  - [ ] LLM cache feature flag: ENABLE_LLM_CACHE=true

deploy:
  - [ ] Redis FLUSHDB gereksiz — key namespace farklı, safe
  - [ ] Smoke test: 2x aynı analytics request → 2. response X-Cache: HIT
  - [ ] Rate limit smoke test: curl loop → 429 alınıyor

post_deploy:
  - [ ] Cache hit rate monitoring: hedef > %60 (cold start sonrası)
  - [ ] Redis memory kullanımı izle: cache key'leri < toplam memory'nin %30'u
  - [ ] LLM maliyet karşılaştırması: cache öncesi vs sonrası (Sentry custom metric)
  - [ ] Rate limit false positive izle: meşru kullanıcı 429 alıyor mu?
```

---

## Sprint Özeti & Uygulama Sırası

| Sprint | Süre | Kritik Bağımlılık | Risk |
|--------|------|--------------------|------|
| L1 Advanced Analytics | 2 hafta | scikit-learn, statsmodels | ML recall regression |
| L2 Agent Negotiation | 2 hafta | CompanyContext, LangGraph | LLM hallucination |
| L3 Compliance & Audit | 2 hafta | L3 GDPR mevcut, +SOX/ISO | SOX legal review |
| M1 Real-time Alerts | 1.5 hafta | Redis, WS altyapı | WS connection leaks |
| M2 Executive Reports | 1.5 hafta | WeasyPrint Docker deps | PDF render latency |
| M3 Rate Limiting | 1 hafta | Redis, mevcut middleware | Cache invalidation bugs |

Önerilen sıra: L1 → M3 → M1 → L3 → M2 → L2
- L1: En yüksek teknik değer, bağımsız
- M3: Tüm diğer sprint'lere altyapı sağlar (cache + rate limit)
- M1: WebSocket altyapısı L2 consensus notifikasyonlarına da lazım
- L3: M2 PDF ile entegre (compliance sertifikası PDF)
- M2: L3'e bağımlı (sertifikasyon PDF)
- L2: En karmaşık, diğerleri tamamlandıktan sonra

Alembic migration sırası:
```
015_anomaly_ml_metadata.py      ← L1
016_agent_conflicts.py           ← L2
017_compliance_extended.py       ← L3
018_alert_tables.py              ← M1
019_report_schedules.py          ← M2
# M3 için migration gerekmez (Redis only + middleware)
```
