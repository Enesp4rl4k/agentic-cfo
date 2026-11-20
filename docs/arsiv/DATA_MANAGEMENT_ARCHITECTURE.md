# Data Management Architecture

Bu doküman, projedeki agentic katmanlara veriyi en kolay, en güvenli ve en
ölçeklenebilir şekilde sağlamak için önerilen veri mimarisini tanımlar.

Amaç:
- ERP / banka / e-fatura / CSV / PDF kaynaklarını tek veri düzleminde birleştirmek
- Agent'ları veri kaynağından ayırmak
- Tam otomatik sync + normalize + validate + trigger hattı kurmak
- RAG ve CompanyContext katmanlarını aynı veri düzlemine bağlamak

## Tasarım İlkeleri

1. Source-agnostic olun.
   Agent'lar "Logo Tiger mı geldi, Paraşüt mü geldi?" bilmemeli.

2. Tek veri kontratı kullanın.
   Tüm connector'lar canonical modele normalize edilmeli.

3. Incremental sync kullanın.
   Mümkün olan her yerde full import yerine cursor / timestamp delta çekin.

4. Idempotent olun.
   Aynı kayıt tekrar gelirse duplicate üretmeyin.

5. Veri kalitesini load-bearing yapın.
   Düşük kaliteli veri otomatik çalışsa bile review gate'e düşebilmeli.

6. Event-driven çalışın.
   "Data synced" olayı; analysis, cache invalidation, RAG indexing ve alerting'i tetiklemeli.


## Hedef Mimari

```text
┌──────────────────────────────────────────────────────────────────┐
│                        SOURCE SYSTEMS                             │
│  Logo Tiger | Paraşüt | Netsis | Open Banking | e-Fatura | CSV  │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                       CONNECTORS LAYER                            │
│  pull() | health_check() | refresh_token() | to_canonical()      │
└───────────────────────────────┬──────────────────────────────────┘
                                │ raw payload + metadata
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                         DATA PLANE                                │
│  Raw Ingest  → Normalize → Validate → Persist → Emit Event       │
│  sync_runs   → canonical tables → quality gate → snapshots       │
└──────────────┬───────────────────────────────┬───────────────────┘
               │                               │
               ▼                               ▼
┌─────────────────────────────┐   ┌───────────────────────────────┐
│      CONTEXT / RAG          │   │       AGENTIC LAYER           │
│  CompanyContext + rag_chunks│   │  LangGraph + kernels + chat   │
└─────────────────────────────┘   └───────────────────────────────┘
```


## Katmanlar

### 1. Connectors Layer

Bu katmanın tek görevi kaynağa bağlanmak ve ham veriyi almak.

Önerilen klasör yapısı:

```text
backend/app/connectors/
  base.py
  erp/
    logo_tiger.py
    parasut.py
    netsis.py
  banking/
    akbank.py
    garanti.py
  invoicing/
    gib_efatura.py
  files/
    csv_import.py
    pdf_import.py
```

Her connector aşağıdaki interface'i uygulamalı:

```python
class BaseConnector:
    async def health_check(self) -> dict: ...
    async def pull(self, since_cursor: str | None = None) -> dict: ...
    async def to_canonical(self, raw_batch: dict) -> dict: ...
    async def get_next_cursor(self, raw_batch: dict) -> str | None: ...
```

Notlar:
- OAuth kaynaklarda token refresh bu katmanda kalmalı
- ERP-specific mapping logic agent'lara sızmamalı
- Retry / timeout / rate limit handling connector içinde olmalı


### 2. Data Plane

Bu sistemin ana omurgasıdır.

Önerilen servisler:

```text
backend/app/services/data_plane/
  ingest_service.py
  normalization_service.py
  validation_service.py
  provenance_service.py
  sync_orchestrator.py
  event_router.py
```

Sorumluluklar:
- ham veriyi arşivlemek
- canonical modele çevirmek
- kalite skoru üretmek
- DB'ye yazmak
- event yayınlamak

Bu katman agent'lar için tek giriş kapısı olmalı.


### 3. Context / RAG Layer

Mevcut bileşenler:
- `backend/app/services/company_context.py`
- `backend/app/services/rag_service.py`
- `backend/app/models/rag_chunk.py`

Rol dağılımı:
- CompanyContext = son agent sonuçları
- RAG = kaynak kanıt parçaları

Kural:
- CompanyContext sadece sonuç/özet taşımalı
- RAG ham/kanıt metni taşımalı


### 4. Agentic Layer

Mevcut bileşenler:
- `backend/app/agents/orchestrator.py`
- `backend/app/services/capability_router.py`
- `backend/app/services/auto_chain.py`
- `backend/app/services/agent_context_bridge.py`

Bu katman:
- canonical data kullanır
- quality / confidence skoruna bakar
- event sonrası koşar
- kendi veri toplama mantığını minimumda tutar


## Canonical Veri Modeli

Agent'lara doğrudan ERP satırı vermek yerine tek kontrat kullanın.

### Minimal Faz-1 Canonical Set

1. `canonical_transactions`
- org_id
- source_type
- source_record_id
- account_ref
- transaction_date
- amount_cents
- currency
- direction
- category
- counterparty
- description
- confidence
- sync_run_id

2. `canonical_invoices`
- org_id
- source_type
- source_record_id
- invoice_no
- issued_at
- due_at
- gross_amount_cents
- net_amount_cents
- tax_amount_cents
- status
- counterparty
- sync_run_id

3. `canonical_cash_accounts`
- org_id
- source_type
- source_record_id
- account_name
- bank_name
- balance_cents
- currency
- as_of
- sync_run_id

4. `canonical_ar_ap_aging`
- org_id
- bucket
- amount_cents
- kind
- as_of
- sync_run_id

5. `canonical_payroll_summary`
- org_id
- period
- headcount
- gross_payroll_cents
- net_payroll_cents
- sync_run_id

### Kaynak ve provenance alanları zorunlu

Her canonical tabloda şunlar bulunmalı:
- `org_id`
- `source_type`
- `source_record_id`
- `sync_run_id`
- `created_at`
- `updated_at`


## Yeni DB Tabloları

Önerilen ek tablolar:

1. `integration_connections`
- org_id
- provider
- auth_type
- encrypted_credentials
- status
- last_healthcheck_at
- last_sync_cursor

2. `sync_runs`
- id
- org_id
- provider
- started_at
- completed_at
- status
- row_count_raw
- row_count_canonical
- quality_score
- error_message

3. `raw_ingest_blobs`
- id
- sync_run_id
- provider
- blob_type
- payload_json_or_path
- checksum

4. `integration_webhooks`
- id
- org_id
- provider
- event_type
- received_at
- payload
- processed


## Veri Akışları

### A. Upload tabanlı akış

```text
upload -> analysis_job create -> enqueue_analysis
       -> agent_bus:data_uploaded
       -> worker
       -> transactions persist
       -> rag index
       -> auto_chain
```

Bu repo içinde ilk versiyonu zaten başlamış durumda.


### B. Scheduled sync akışı

```text
scheduler -> run_due_syncs
          -> connector.pull()
          -> normalize
          -> validate
          -> create_analysis_job
          -> enqueue_analysis
          -> agent_bus:sync_analysis_enqueued
```


### C. Future webhook akışı

Örnek: ERP tarafı "invoice.created" webhook gönderir.

```text
webhook receive
-> verify signature
-> store raw payload
-> map event to provider connector
-> incremental pull or direct normalize
-> emit data.synced
```


## Event Modeli

Tüm otomasyon aynı event sözleşmesiyle ilerlemeli.

Önerilen event tipleri:
- `data_uploaded`
- `sync_analysis_enqueued`
- `data_synced`
- `data_quality_low`
- `analysis_completed`
- `rag_backfill_needed`
- `context_updated`

Önerilen payload alanları:
- event_id
- event_type
- org_id
- job_id
- provider
- source_type
- sync_run_id
- created_at
- metadata

Mevcut `agent_bus` bunun için uygun temel taşıyor.


## Quality Gate Tasarımı

Veri kalitesi agent'ların içine gömülmemeli; Data Plane katmanında çözülmeli.

Önerilen kalite boyutları:
- schema completeness
- duplicate ratio
- date parse success ratio
- amount parse success ratio
- source freshness
- referential consistency

Skor çıktısı:

```python
{
  "quality_score": 0.0_to_1.0,
  "issues": [...],
  "should_block": bool,
  "should_review": bool,
}
```

Kurallar:
- `quality_score < 0.50` => analysis block
- `0.50 <= score < 0.80` => analysis allowed but `awaiting_review=True`
- `score >= 0.80` => normal flow


## RAG Stratejisi

### Şimdiki kolay yaklaşım
- `rag_chunks` tablosu
- TF-IDF retrieval
- source-scoped evidence

### Sonraki üretim yaklaşımı
- `pgvector`
- embedding queue
- semantic retrieval + metadata filtering

Chunk kaynakları:
- upload raw text
- invoice OCR text
- ERP document notes
- board / audit artifacts

Kural:
- Agent summary ve RAG evidence ayrı tutulmalı
- Prompt'a sadece küçük top-k kanıtlar girmeli


## CompanyContext Stratejisi

CompanyContext içinde sadece şu tip bilgiler yaşamalı:
- son CFO sonucu
- son CTO sonucu
- son Risk sonucu
- active job ids
- context summary metadata

CompanyContext içinde yaşanmaması gerekenler:
- binlerce raw transaction
- büyük OCR dump'ları
- tam webhook payload'ları

Bunlar canonical store veya raw blob store'da kalmalı.


## ERP Entegrasyon Stratejisi

### Faz-1 öncelik

1. Paraşüt
- modern API
- SMB segment için yüksek değer
- finance-first onboarding

2. Logo Tiger
- Türkiye pazarı için kritik
- enterprise / orta ölçekli şirket değeri yüksek

3. CSV fallback
- her zaman desteklenmeli
- onboarding kurtarıcı kanal

### Faz-2
- Open Banking
- GİB e-Fatura
- HR / CRM


## Repo İçinde Önerilen Uygulama Yerleşimi

### Yeni / güçlendirilecek dosyalar

```text
backend/app/connectors/
backend/app/services/data_plane/
backend/app/models/integration_connection.py
backend/app/models/sync_run.py
backend/app/models/raw_ingest_blob.py
backend/app/services/event_router.py
backend/app/api/integrations/
backend/app/api/webhooks/
```

### Mevcut dosyalarla bağlantılar

- `backend/app/services/scheduled_sync.py`
  -> sync orchestrator'a dönüşmeli

- `backend/app/services/upload_service.py`
  -> upload source adapter gibi davranmalı

- `backend/app/worker.py`
  -> analysis ve post-analysis hooks burada kalabilir

- `backend/app/services/auto_chain.py`
  -> analysis sonrası domain chain

- `backend/app/services/agent_context_bridge.py`
  -> canonical summary okuyarak agent input enrich etmeli


## Uygulama Sırası

### Sprint 1
- connector base interface
- `integration_connections`
- `sync_runs`
- event contract
- Paraşüt connector
- CSV fallback standardization

### Sprint 2
- canonical transaction / invoice tables
- normalization service
- quality scoring service
- sync orchestrator refactor

### Sprint 3
- Logo Tiger connector
- webhook ingestion
- CompanyContext auto-update rules
- RAG indexing from canonical docs

### Sprint 4
- pgvector migration
- semantic retrieval
- per-domain retrieval filters
- data freshness dashboards


## Done When

Bu mimari "tamamlandı" sayılabilmesi için:

1. Yeni bir ERP connector eklemek 1 adapter dosyası + config ile mümkün olmalı
2. Agent'lar ERP adı bilmeden canonical data ile çalışmalı
3. Sync sonrası analysis otomatik başlamalı
4. Veri kalitesi düşük olduğunda otomatik review gate çalışmalı
5. RAG evidence, ilgili şirkete ve ilgili job'a scoped gelmeli
6. Tüm akış audit trail bırakmalı: `org_id`, `sync_run_id`, `job_id`

