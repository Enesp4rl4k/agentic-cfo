"""
Data Sync Service — Quick Reference

Multi-source data pipeline orchestrator for zero-manual-upload CFO data synchronization.
"""

# ═══════════════════════════════════════════════════════════════════════════════
# Quick Start
# ═══════════════════════════════════════════════════════════════════════════════

## Installation

All dependencies already in `backend/requirements.txt`:
- httpx (async HTTP for APIs)
- apscheduler (background job scheduling)
- pydantic (data validation)
- sqlalchemy (database ORM)

## Environment Setup

```bash
# Copy template
cp .env.example .env

# Add credentials
PARASUT_OAUTH_CLIENT_ID=your_id
PARASUT_OAUTH_CLIENT_SECRET=your_secret
GARANTI_CLIENT_ID=your_id
GARANTI_CLIENT_SECRET=your_secret
AKBANK_CLIENT_ID=your_id
AKBANK_CLIENT_SECRET=your_secret
```

## Initialize Scheduler

```python
from app.services.data_sync.scheduler import init_sync_scheduler

# In main.py or startup handler:
scheduler = init_sync_scheduler()

# Schedule jobs with defaults or custom crons
scheduler.schedule_parasut_sync()
scheduler.schedule_garanti_sync()
scheduler.schedule_akbank_sync()
```

## Manual Sync

```python
from app.services.data_sync.orchestrator import DataSyncOrchestrator
from app.services.data_sync.schemas import BankingSourceConfig, SyncSourceType

orchestrator = DataSyncOrchestrator()

# Sync Garanti
config = BankingSourceConfig(
    source_type=SyncSourceType.GARANTI,
    client_id="abc123",
    client_secret="secret456",
    sandbox_mode=True,
)
batch = await orchestrator.sync_garanti(config)
print(f"Synced {len(batch.transactions)} transactions")
```

# ═══════════════════════════════════════════════════════════════════════════════
# Architecture Overview
# ═══════════════════════════════════════════════════════════════════════════════

## File Structure

```
backend/app/services/data_sync/
├── __init__.py                      # Package marker
├── schemas.py                       # Pydantic validation schemas
├── orchestrator.py                  # Main orchestration logic
├── validators.py                    # Data quality + conflict resolution
├── audit.py                         # Audit trail logging
├── scheduler.py                     # APScheduler job management
│
├── accounting/
│   ├── __init__.py
│   ├── parasut.py                   # OAuth2 API client (Paraşüt)
│   └── importers.py                 # CSV importers (Netsis, Mikro, Logo Tiger)
│
└── banking/
    ├── __init__.py
    └── psd2.py                      # PSD2 clients (Garanti, Akbank)

backend/tests/
└── test_data_sync.py                # Integration tests

backend/
└── DATA_SYNC_GUIDE.md               # Full setup + admin guide
```

## Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│ Data Sources (Phase 1 + 2)                                  │
├─────────────────────────────────────────────────────────────┤
│ • Paraşüt (OAuth2 API)    → ParasutClient.sync_transactions │
│ • Netsis (CSV)            → NetsisImporter.sync             │
│ • Mikro (CSV/XLS)         → MikroImporter.sync              │
│ • Logo Tiger (CSV)        → LogoTigerImporter.sync          │
│ • Garanti (PSD2 API)      → GarantiPSD2Client.fetch_*       │
│ • Akbank (PSD2 API)       → AkbankPSD2Client.fetch_*        │
└──────────────────┬────────────────────────────────────────┘
                   │
                   ↓
        ┌──────────────────────────┐
        │ SyncBatch                │
        ├──────────────────────────┤
        │ • source_type            │
        │ • transactions[]          │
        │ • warnings[]             │
        │ • error_count            │
        └──────────────┬───────────┘
                       │
                       ↓
        ┌──────────────────────────────────┐
        │ Phase 3: Quality + Conflict       │
        ├──────────────────────────────────┤
        │ 1. DataQualityValidator          │
        │    • Duplicate detection         │
        │    • Anomaly detection           │
        │    • Data integrity checks       │
        │                                  │
        │ 2. DuplicateDetector             │
        │    • Cross-batch deduplication   │
        │                                  │
        │ 3. ConflictResolver              │
        │    • API data wins over CSV      │
        │    • Priority: Bank > API > CSV  │
        └──────────────┬───────────────────┘
                       │
                       ↓
        ┌──────────────────────────────────┐
        │ Database: Transactions Persisted │
        │ Audit: SyncAuditLog recorded     │
        └──────────────────────────────────┘
```

# ═══════════════════════════════════════════════════════════════════════════════
# Key Classes & Methods
# ═══════════════════════════════════════════════════════════════════════════════

## Orchestrator

```python
class DataSyncOrchestrator:
    async def sync_parasut(config, date_range_days=90)
        → SyncBatch: Fetch from Paraşüt API
    
    async def sync_accounting_csv(source_type, csv_content)
        → SyncBatch: Parse accounting software CSV
    
    async def sync_garanti(config, date_range_days=90)
        → SyncBatch: Fetch from Garanti PSD2
    
    async def sync_akbank(config, date_range_days=90)
        → SyncBatch: Fetch from Akbank PSD2
    
    async def process_batches(batches)
        → list[SyncBatch]: Apply validators + conflict resolution
    
    def get_batch_summary(batch)
        → dict: Stats + data hash for audit
```

## Validators

```python
class DataQualityValidator:
    def validate_batch(batch) → SyncBatch
        Detects duplicates, anomalies, outliers, integrity issues

class DuplicateDetector:
    def is_duplicate(tx) → bool
    def detect_duplicates_in_batch(batch) → list[SyncTransaction]

class ConflictResolver:
    def resolve_conflicts(transactions) → list[SyncTransaction]
        Keeps highest-priority version of duplicate transactions
```

## Scheduler

```python
class SyncScheduler:
    def start() → None
    def stop() → None
    
    def schedule_parasut_sync(schedule_cron, job_id)
    def schedule_netsis_sync(schedule_cron, job_id)
    def schedule_mikro_sync(schedule_cron, job_id)
    def schedule_logo_tiger_sync(schedule_cron, job_id)
    def schedule_garanti_sync(schedule_cron, job_id)
    def schedule_akbank_sync(schedule_cron, job_id)
    
    def get_jobs() → dict[str, dict]
    def pause_job(job_id) → bool
    def resume_job(job_id) → bool
```

## Audit Trail

```python
class AuditTrail:
    @staticmethod
    def compute_batch_hash(batch) → str
        SHA256 hash of batch transactions for integrity
    
    @staticmethod
    def create_sync_log(batch, status, started_at, ended_at, ...)
        → SyncJobLog: Immutable sync operation record
```

# ═══════════════════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════════════════

## SyncTransaction

Normalized transaction from any source:

```python
class SyncTransaction(BaseModel):
    date: datetime                      # Transaction date (UTC)
    description: str                    # Human-readable description
    amount_cents: int                   # Always positive; sign in tx_type
    tx_type: TransactionType            # "income" | "expense"
    currency: str = "TRY"               # 3-letter code
    vendor: Optional[str] = None        # Counterparty name
    balance_cents: Optional[int] = None # Running balance
    reference: Optional[str] = None     # External transaction ID
    source_type: SyncSourceType         # Which source this came from
    source_id: Optional[str] = None     # Unique ID in source system
    raw_row: str = ""                   # Original data for audit
```

## SyncBatch

Result of one sync operation:

```python
class SyncBatch(BaseModel):
    source_type: SyncSourceType         # Which source
    sync_timestamp: datetime            # When sync ran
    transactions: list[SyncTransaction] # Normalized transactions
    warnings: list[str]                 # Data quality warnings
    error_count: int                    # Failed transaction count
    total_processed: int                # Total attempted
```

## SyncJobLog

Immutable audit trail entry:

```python
class SyncJobLog(BaseModel):
    source_type: SyncSourceType
    status: SyncStatus                  # success | partial_failure | failed
    started_at: datetime
    ended_at: Optional[datetime]
    duration_ms: Optional[int]
    transactions_synced: int
    transactions_failed: int
    conflict_count: int
    warnings: list[str]
    error_message: Optional[str]
    data_hash: str                      # SHA256 for integrity verification
```

# ═══════════════════════════════════════════════════════════════════════════════
# Error Handling & Retries
# ═══════════════════════════════════════════════════════════════════════════════

All HTTP clients include:

1. **Exponential Backoff Retry**
   - Max retries: configurable (default 3)
   - Backoff: 2^attempt seconds
   - Timeout: 30 seconds per request

2. **Rate Limiting**
   - Respects X-RateLimit-Reset headers
   - Auto-sleeps before making requests
   - Logs rate limit events

3. **Error Handling**
   - Network errors → logged + retried
   - 429 (rate limited) → exponential backoff
   - 4xx (client error) → fail fast
   - 5xx (server error) → retried

4. **Data Validation**
   - Pydantic validates all ingested data
   - Invalid records → warnings, not failures
   - Batch continues on individual errors

# ═══════════════════════════════════════════════════════════════════════════════
# Testing
# ═══════════════════════════════════════════════════════════════════════════════

Run tests:

```bash
cd backend
pytest tests/test_data_sync.py -v

# Run with coverage
pytest tests/test_data_sync.py --cov=app.services.data_sync
```

Test fixtures include:
- Sample transactions + batches
- Real CSV samples from each accounting software
- Mock clients for API testing

Test coverage:
- CSV parsing (all accounting software)
- Data validators (duplicates, anomalies, outliers)
- Conflict resolution
- Audit trail
- Orchestrator workflow

# ═══════════════════════════════════════════════════════════════════════════════
# Performance Considerations
# ═══════════════════════════════════════════════════════════════════════════════

## Scalability

- **Batch Size**: Handles 10K+ transactions per sync
- **Parallel Sync**: Can run all 6 sources simultaneously (different processes)
- **Memory**: Historical data limited to last 1000 transactions for anomaly detection
- **Database**: Indexed queries on (source_type, started_at)

## Optimization

1. **Async/Await**: Non-blocking HTTP calls
2. **Connection Pooling**: Reused HTTP connections
3. **Pagination**: API clients fetch 100 records per page
4. **Deduplication**: Set-based duplicate detector (O(1) lookup)

## Database Indexes

Required for performance:
```sql
CREATE INDEX idx_sync_source_date ON sync_audit_logs(source_type, started_at);
CREATE INDEX idx_sync_status ON sync_audit_logs(status, started_at);
```

# ═══════════════════════════════════════════════════════════════════════════════
# Next Steps / Future Enhancements
# ═══════════════════════════════════════════════════════════════════════════════

Phase 1 Complete: ✅ Accounting software parsers + banking APIs

Phase 2 (Future):
- [ ] Webhook-based real-time ingestion (vs. scheduled polling)
- [ ] Machine learning anomaly detection (replacing simple stats)
- [ ] Automated reconciliation with uploaded CSVs
- [ ] Multi-currency support (currently TRY only)
- [ ] Incremental sync (track last_sync timestamp per source)
- [ ] Data retention policies (archive old transactions)

API Enhancements:
- [ ] Batch sync endpoint (trigger all sources at once)
- [ ] Webhook for external trigger
- [ ] Sync status WebSocket stream
- [ ] Export audit logs to CSV/PDF

Monitoring:
- [ ] Datadog/Prometheus metrics
- [ ] Slack alerts for sync failures
- [ ] Dashboard showing sync status + data freshness
- [ ] Automated health checks

# ═══════════════════════════════════════════════════════════════════════════════
# Support & Troubleshooting
# ═══════════════════════════════════════════════════════════════════════════════

See `backend/DATA_SYNC_GUIDE.md` for detailed:
- Setup instructions per source
- Troubleshooting guide
- SQL queries for monitoring
- Security best practices
- Recommended alerts
"""
