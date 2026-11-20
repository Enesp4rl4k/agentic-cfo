# C-Level AI — Platform Mimarisi v2

> Sadece finansal araç değil: tüm kurumsal katmanları kapsayan, her agent'ın kernel-seviyesinde altyapısıyla çalıştığı profesyonel C-Suite intelligence platformu.

---

## 1. Mevcut Durum Tespiti

### Ne Var (Güçlü Yönler)

| Katman | Durum |
|--------|-------|
| CFO Pipeline | ✅ Tam — LangGraph, P&L, CashFlow, Forecast, Budget, Tax, Anomaly |
| CEO Synthesis | ✅ Var — cross-domain board deck, OKR tracking |
| CTO / CMO / COO / CHRO | ⚠️ Var ama CSV form-based — otomatik bağlantı yok |
| Risk / Compliance / Audit | ⚠️ Var ama CSV form-based |
| CapabilityRouter | ✅ Var — hangi agent'ın çalışacağını dinamik belirliyor |
| ReflectionAgent | ✅ Var — narrative kalitesini skorluyor |
| AgentMemory (SQLite) | ✅ Var — episode kayıt/geri çağırma |
| SSE Streaming | ✅ Var — real-time agent adımları |
| Multi-tenant / Auth | ✅ Var — org_id, role-based access |

### Ne Eksik (Kritik Boşluklar)

1. **Unified Company Context** — Her agent izole çalışıyor. Bir CFO analizi yapıldığında CTO/CMO/CHRO sayfaları bunu bilmiyor.
2. **Otomatik Cross-Domain Tetikleme** — CFO analizi bitince CEO pipeline otomatik çalışmıyor.
3. **Harici Veri Entegrasyonu** — GitHub, cloud billing, CRM, HR sistemleri bağlı değil.
4. **Scheduled Intelligence** — Günlük/haftalık otomatik analiz yok.
5. **Alert Routing** — Backend alert'leri var ama Slack/email'e gitmiyor.
6. **Platform State** — Frontend'de aktif job_id URL'de taşınıyor; workspace-level persist yok.

---

## 2. Hedef Mimari

```
┌─────────────────────────────────────────────────────────────────────┐
│                    PLATFORM KERNEL LAYER                             │
│                                                                      │
│  ┌──────────────────┐  ┌─────────────────┐  ┌────────────────────┐  │
│  │  CompanyContext   │  │ Scheduler (ARQ) │  │  Alert Router      │  │
│  │  (org-level state)│  │ daily/weekly    │  │  Slack / Email     │  │
│  └──────────────────┘  └─────────────────┘  └────────────────────┘  │
│                                                                      │
│  ┌──────────────────┐  ┌─────────────────┐  ┌────────────────────┐  │
│  │  DataConnectors   │  │ AgentMemory     │  │  CapabilityRouter  │  │
│  │  (GitHub/CRM/HR) │  │ (SQLite→Postgres)│  │  (dependency graph)│  │
│  └──────────────────┘  └─────────────────┘  └────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────────┐
│                    AGENT ORCHESTRATION LAYER                         │
│                                                                      │
│  Master Orchestrator (CEO-level conductor)                           │
│  ┌──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┐  │
│  │ CFO  │ CTO  │ CMO  │ COO  │ CHRO │ Risk │ Comp │ Audit│ CEO  │  │
│  │ ─────│──────│──────│──────│──────│──────│──────│──────│──────│  │
│  │Kernel│Kernel│Kernel│Kernel│Kernel│Kernel│Kernel│Kernel│Synth │  │
│  └──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┘  │
│                              │                                       │
│                    Cross-Domain Correlator                           │
│                    Cascade Risk Simulator                            │
└─────────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────────┐
│                    FRONTEND INTELLIGENCE LAYER                       │
│                                                                      │
│  ┌──────────────────┐  ┌─────────────────┐  ┌────────────────────┐  │
│  │  Command Center  │  │  Per-Agent Dash  │  │  NL Chat (any     │  │
│  │  (unified health)│  │  (deep-dive)     │  │   agent context)  │  │
│  └──────────────────┘  └─────────────────┘  └────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Geliştirme Fazları

### Faz 1 — Platform Kernel (1-2 Hafta) 🔴 KRİTİK

**Amaç:** Unified Company Context — bir kez veri yükle, tüm agentlar bağlansın.

#### 1.1 CompanyContext Servisi (Backend)

```python
# backend/app/services/company_context.py
class CompanyContext:
    """
    Org bazında aktif analiz state'i.
    Tüm agentlar bu context'i okur/yazar.
    Redis'te tutulur (30 dk TTL), DB'ye snapshot alınır.
    """
    org_id: str
    active_cfo_job_id: str | None      # Son tamamlanan CFO analizi
    last_cfo_result: dict | None       # Dashboard JSON cache
    last_cto_result: dict | None
    last_cmo_result: dict | None
    last_coo_result: dict | None
    last_chro_result: dict | None
    last_risk_result: dict | None
    last_audit_result: dict | None
    company_name: str | None
    reporting_period: str | None
    updated_at: datetime
```

**Yeni API Endpoint'leri:**
```
GET  /api/v1/context/{org_id}          → CompanyContext döner
POST /api/v1/context/{org_id}/reset    → Context'i sıfırla
GET  /api/v1/context/{org_id}/summary  → Tüm agentların son durumu
```

#### 1.2 Auto-Chain Mekanizması

CFO analizi tamamlandığında diğer agentları otomatik tetikle:

```python
# backend/app/services/auto_chain.py
AGENT_CHAIN = {
    "cfo_complete": ["risk", "audit", "ceo_synthesis"],
    "cto_complete": ["ceo_synthesis"],
    "risk_complete": ["compliance", "ceo_synthesis"],
}

async def on_agent_complete(agent: str, org_id: str, result: dict):
    """CFO bitince → Risk + Audit otomatik başlar → CEO synthesis."""
    context = await get_company_context(org_id)
    context.update_agent_result(agent, result)
    
    for next_agent in AGENT_CHAIN.get(f"{agent}_complete", []):
        if context.has_required_data(next_agent):
            await enqueue_agent(next_agent, org_id, context)
```

#### 1.3 Frontend: Workspace-Level Context Store

> **Uygulama Notu:** PLAN.md'de Zustand planlandı, ancak React Context + localStorage ile
> daha hafif bir çözüm tercih edildi. Zustand bağımlılığı eklenmedi.
> Mevcut uygulama `frontend/src/store/companyContext.tsx` dosyasındadır.

```typescript
// frontend/src/store/companyContext.tsx (React Context + localStorage — Zustand DEĞİL)
interface CompanyContextStore {
  orgId: string | null
  activeCFOJobId: string | null
  companyName: string | null
  lastUpdated: string | null
  agentResults: Record<string, unknown>
  
  setActiveCFOJob: (jobId: string) => void
  refreshContext: () => Promise<void>
}
```

**Değişiklik:** Tüm sayfalar URL `?job=` yerine store'dan `activeCFOJobId` okur.

---

### Faz 2 — Agent Kernel Güçlendirme (2-3 Hafta) 🟡 ÖNEMLİ

Her agent CSV form-based olmaktan çıkıp gerçek veri kaynaklarına bağlanmalı.

#### 2.1 CTO Agent Kernel

**Mevcut:** Manuel CSV paste
**Hedef:** Otomatik veri çekme

```python
# backend/app/connectors/cto/
├── github_connector.py       # GitHub API: commits, PRs, issues
├── cloud_billing_connector.py # AWS/Azure/GCP Cost Explorer API
├── incident_connector.py     # PagerDuty / OpsGenie API
└── sprint_connector.py       # Jira / Linear API

class CTOKernel:
    """
    Veri kaynağı önceliği:
    1. Bağlı connector'dan çek (OAuth)
    2. Uploaded CSV'den oku
    3. CompanyContext'ten son result'u kullan
    4. Template fallback (dev mode)
    """
    async def collect(self, context: CompanyContext) -> CTOInputData:
        ...
```

**Yeni OAuth Endpoints:**
```
GET  /api/v1/integrations/github/auth     → OAuth redirect
GET  /api/v1/integrations/github/callback → Token kaydet
GET  /api/v1/integrations/github/status   → Bağlı mı?
POST /api/v1/integrations/github/sync     → Manuel sync tetikle
```

#### 2.2 CMO Agent Kernel

```python
# backend/app/connectors/cmo/
├── google_analytics_connector.py  # GA4 API
├── hubspot_connector.py           # HubSpot CRM API  
├── stripe_revenue_connector.py    # Stripe MRR/ARR
└── facebook_ads_connector.py      # Meta Ads API
```

#### 2.3 CHRO Agent Kernel

```python
# backend/app/connectors/chro/
├── bamboohr_connector.py    # BambooHR API
├── personio_connector.py    # Personio API (TR market)
├── jira_connector.py        # Jira ticket → workload analysis
└── hr_csv_parser.py         # Generic HR CSV
```

#### 2.4 Risk Agent Kernel Güçlendirmesi

```python
# backend/app/agents/risk/ — mevcut yapıya eklemeler
├── external_risk_feeds.py   # BIST, Merkez Bankası API
├── cyber_risk_scanner.py    # CVE veritabanı kontrol
└── supply_chain_monitor.py  # Tedarikçi risk skoru
```

---

### Faz 3 — Cross-Domain Intelligence (1-2 Hafta) 🟡 ÖNEMLİ

#### 3.1 Master Orchestrator Güçlendirmesi

Mevcut CEO pipeline'ı gerçek bir cross-domain orchestrator'a dönüştür:

```python
# backend/app/agents/master_orchestrator.py
class MasterOrchestrator:
    """
    Tüm agent sonuçlarını alır, cross-domain korelasyon yapar.
    
    Örnekler:
    - CFO'da nakit sıkışması + CHRO'da yüksek attrition → "talent-cash cascade risk"
    - CTO'da yavaş velocity + CMO'da yüksek CAC → "delivery risk to revenue"
    - Risk'te open items + Audit'te coverage gap → "regulatory exposure"
    """
    
    async def synthesize(self, context: CompanyContext) -> MasterSynthesis:
        correlations = await self._find_cross_correlations(context)
        cascade_risks = await self._simulate_cascades(correlations)
        board_priorities = await self._rank_priorities(cascade_risks)
        return MasterSynthesis(
            correlations=correlations,
            cascade_risks=cascade_risks,
            board_priorities=board_priorities,
            executive_summary=await self._generate_summary(context),
        )
```

#### 3.2 Cascade Risk Simulator

```python
# backend/app/services/cascade_simulator.py
"""
"Nakit 3 ayda biterse ne olur?" sorusunu tüm domainlere yansıt:
- CFO: burn rate artıyor
- CHRO: işe alım durur → attrition artar
- CTO: teknik borç ertelenir
- CMO: marketing bütçesi kesilir → CAC artar
- Risk: operational risk artar
"""

class CascadeSimulator:
    def simulate(self, trigger: RiskEvent, context: CompanyContext) -> CascadeReport:
        ...
```

---

### Faz 4 — Scheduled Intelligence (1 Hafta) 🟢 DEĞER KATAR

#### 4.1 Günlük/Haftalık Otomatik Analiz

```python
# backend/app/scheduler.py — mevcut dosyaya ekle
@scheduler.scheduled_job("cron", hour=8, minute=0)  # Her gün 08:00
async def daily_intelligence_run():
    """
    Aktif workspace'leri tara.
    Her org için bağlı connector'lardan veri çek.
    Tüm agent pipeline'ı çalıştır.
    Değişiklikleri tespit et, alert gönder.
    """
    orgs = await get_active_orgs_with_connectors()
    for org in orgs:
        await run_full_intelligence_suite(org.id)
```

#### 4.2 Alert Routing Gerçek Entegrasyon

```python
# backend/app/services/alert_router.py — mevcut dosyayı güçlendir
class AlertRouter:
    async def route(self, alert: Alert, org_id: str):
        prefs = await get_org_alert_prefs(org_id)
        if prefs.slack_webhook:
            await self._send_slack(alert, prefs.slack_webhook)
        if prefs.email:
            await self._send_email(alert, prefs.email)
        if prefs.whatsapp:
            await self._send_whatsapp(alert, prefs.whatsapp)
```

**Yeni API:**
```
POST /api/v1/org/alert-prefs     → Slack webhook / email kaydet
GET  /api/v1/org/alert-prefs     → Mevcut ayarları getir
POST /api/v1/org/alert-test      → Test alert gönder
```

---

### Faz 5 — Platform Monetizasyon (1 Hafta) 🟢 GELİR

#### 5.1 Stripe Billing

```python
# backend/app/api/billing.py
"""
Plan sınırları:
- Free: 3 analiz/ay, sadece CFO agent
- Pro: unlimited analiz, tüm agentlar, 1 connector
- Enterprise: unlimited, tüm connectorlar, white-label, SSO
"""

POST /api/v1/billing/subscribe      → Stripe checkout
GET  /api/v1/billing/portal         → Stripe customer portal
POST /api/v1/billing/webhook        → Stripe events
GET  /api/v1/billing/usage          → Bu ay kullanım
```

#### 5.2 Usage Metering

```python
# backend/app/middleware/usage_meter.py
class UsageMeter:
    """Her agent run'ı say, plan limitini kontrol et."""
    async def check_and_increment(self, org_id: str, resource: str) -> bool:
        ...
```

---

## 4. Veritabanı Şema Değişiklikleri

### Yeni Tablolar

```sql
-- Entegrasyon bağlantıları (OAuth tokens)
CREATE TABLE integrations (
    id          UUID PRIMARY KEY,
    org_id      UUID NOT NULL REFERENCES organizations(id),
    provider    VARCHAR(50) NOT NULL,  -- github, hubspot, etc.
    access_token TEXT,  -- encrypted
    refresh_token TEXT, -- encrypted
    scopes      TEXT[],
    connected_at TIMESTAMPTZ,
    last_sync_at TIMESTAMPTZ,
    status      VARCHAR(20) DEFAULT 'active'
);

-- Company context cache (DB snapshot)
CREATE TABLE company_contexts (
    org_id      UUID PRIMARY KEY REFERENCES organizations(id),
    cfo_job_id  UUID,
    company_name VARCHAR(200),
    period      VARCHAR(50),
    agent_results JSONB DEFAULT '{}',
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Alert tercihler
CREATE TABLE alert_preferences (
    org_id          UUID PRIMARY KEY REFERENCES organizations(id),
    slack_webhook   TEXT,
    email_addresses TEXT[],
    whatsapp_number VARCHAR(20),
    min_severity    VARCHAR(20) DEFAULT 'high',
    digest_schedule VARCHAR(20) DEFAULT 'daily'
);

-- Billing / Usage
CREATE TABLE billing_subscriptions (
    org_id      UUID PRIMARY KEY REFERENCES organizations(id),
    stripe_customer_id VARCHAR(100),
    stripe_subscription_id VARCHAR(100),
    plan        VARCHAR(20) DEFAULT 'free',
    status      VARCHAR(20) DEFAULT 'active',
    current_period_end TIMESTAMPTZ
);

CREATE TABLE usage_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL,
    resource    VARCHAR(50),  -- 'agent_run', 'connector_sync', etc.
    quantity    INT DEFAULT 1,
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Alembic Migration Sırası
```
007_integrations.py
008_company_context.py
009_alert_preferences.py
010_billing.py
```

---

## 5. Frontend Mimari Değişiklikleri

### Global State (React Context + localStorage)

> **Karar:** Zustand yerine React Context + localStorage kullanıldı (`frontend/src/store/companyContext.tsx`).
> `useCompanyContextStore()` hook arayüzü Zustand ile uyumlu tasarlandığından,
> gelecekte Zustand'a geçiş yapılırsa tüketici bileşenler değişmez.

```typescript
// frontend/src/store/
├── companyContext.tsx   // Aktif analiz context'i — React Context + localStorage ✅ UYGULANMIŞ
├── integrations.ts     // Bağlı connector'lar (Faz 4'te eklenecek)
└── workspace.ts        // Mevcut org/user info (Faz 4'te eklenecek)
```

### Yeni Sayfalar

```
/integrations          → Connector kurulum (GitHub, HubSpot, vs.)
/integrations/github   → GitHub OAuth + sync status
/billing               → Plan yönetimi (Stripe portal)
/settings/alerts       → Slack/email/WhatsApp ayarları
/settings/schedule     → Otomatik analiz programı
```

### Güncellenecek Sayfalar

| Sayfa | Değişiklik |
|-------|------------|
| `/upload` | CSV formdan "Connect Integrations" akışına yönlendirme ekle |
| `/cto` | CSV form yerini GitHub/cloud sync status alır |
| `/cmo` | CSV form yerini HubSpot/GA4 sync status alır |
| `/command-center` | CompanyContext'ten gerçek veri, auto-refresh |
| `/settings/workspace` | Alert prefs + integration yönetimi |

---

## 6. Uygulama Sırası (Öncelik Sırası)

```
Sprint 1 (1 hafta)
  ✦ CompanyContext servisi + Redis cache + DB snapshot
  ✦ GET /context endpoint'i
  ✦ Frontend Context store (companyContext) ✅ UYGULANMIŞ — React Context + localStorage
  ✦ Tüm dashboard sayfaları URL ?job= yerine store kullan
  ✦ Migration 007-008

Sprint 2 (1 hafta)  
  ✦ Auto-chain mekanizması (CFO biter → Risk + Audit tetiklenir)
  ✦ Alert Router → Slack entegrasyonu
  ✦ Alert preferences API + frontend settings sayfası
  ✦ Migration 009

Sprint 3 (2 hafta)
  ✦ CTO Kernel: GitHub connector (OAuth + sync)
  ✦ CMO Kernel: HubSpot connector (OAuth + sync)
  ✦ Integration settings sayfası
  ✦ Migration 007 (integrations tablosu)

Sprint 4 (1 hafta)
  ✦ Master Orchestrator güçlendirmesi
  ✦ Cascade Risk Simulator
  ✦ Command Center → gerçek cross-domain correlation

Sprint 5 (1 hafta)
  ✦ Stripe billing
  ✦ Usage metering
  ✦ Plan sınırları (free/pro/enterprise)
  ✦ Migration 010

Sprint 6 (1 hafta)
  ✦ Günlük otomatik analiz (scheduler)
  ✦ Email report (Resend)
  ✦ Mobile responsive iyileştirmeler
```

---

## 7. Teknik Kararlar

| Karar | Seçim | Gerekçe |
|-------|-------|---------|
| Company Context cache | Redis (mevcut) + DB snapshot | Hız + kalıcılık |
| OAuth token şifreleme | Fernet (cryptography lib) | Basit, güvenli |
| Connector pattern | Async context manager + retry | CLAUDE.md kuralı: retry_harness |
| Frontend state | React Context + localStorage (✅ uygulandı) | Zustand bağımlılığı olmadan yeterli; gerekirse geçiş kolay |
| Alert queue | Redis (mevcut) + ARQ | Mevcut worker kullan |
| Billing | Stripe | Türkiye desteği, webhook güvenilir |
| Email | Resend | Next.js ekosistemi, iyi DX |

---

## 8. Güvenlik Notları

- OAuth token'lar Fernet ile şifrelenir, DB'de düz metin yok
- Connector credential'ları org_id ile scope'lanır, cross-tenant leak yok
- Stripe webhook signature doğrulama zorunlu
- Usage meter bypass koruması (rate limit + DB audit)
- Integration sync sadece org owner/admin tetikleyebilir

---

## 9. Başarı Kriterleri (done_when)

| Milestone | Kriter |
|-----------|--------|
| CompanyContext | CFO analizi biter → /context/{org_id} güncel veri döner |
| Auto-chain | CFO biter → 60 sn içinde Risk analizi otomatik başlar |
| GitHub connector | Bağlandıktan sonra CTO sayfası CSV olmadan çalışır |
| Alert routing | Kritik alert → 30 sn içinde Slack mesajı gelir |
| Billing | Stripe checkout flow end-to-end çalışır |
| Scheduler | Günlük 08:00 run logs'da görünür |
