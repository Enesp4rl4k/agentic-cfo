"""
Multi-Source Data Sync Pipeline — Setup & Administration Guide

Zero manual uploads → CFO data automatically synchronized from accounting software + banking APIs.

═══════════════════════════════════════════════════════════════════════════════
Phase 1: Accounting Software (Paraşüt, Netsis, Mikro, Logo Tiger)
═══════════════════════════════════════════════════════════════════════════════

PARAŞÜT (Cloud Accounting Platform)
───────────────────────────────────

1. Register OAuth2 Application:
   - Go to https://app.parasut.com/settings/api
   - Create new application
   - Get Client ID and Client Secret

2. Configure in .env:
   PARASUT_OAUTH_CLIENT_ID=your_client_id
   PARASUT_OAUTH_CLIENT_SECRET=your_client_secret
   PARASUT_COMPANY_ID=your_company_id

3. First-time OAuth2 Flow:
   - App will prompt for authorization
   - User grants permission in browser
   - System stores refresh token securely
   - Token auto-refreshes before expiry

4. Sync Schedule:
   - Default: Daily 2 AM (cron: "0 2 * * *")
   - Customizable via SyncScheduler
   - Fetches: Transactions, Invoices (sales + purchases)
   - Range: Last 90 days (configurable)

5. Rate Limits:
   - 100 requests/minute
   - Auto-backoff with exponential retry
   - Max 3 retries

Example Configuration:
```python
from app.services.data_sync.schemas import AccountingSourceConfig

config = AccountingSourceConfig(
    source_type=SyncSourceType.PARASUT,
    is_enabled=True,
    schedule_cron="0 2 * * *",
    retry_count=3,
    timeout_seconds=300,
    oauth_client_id="abc123",
    oauth_client_secret="secret456",
    oauth_refresh_token="refresh_token_xyz",
)
```


NETSIS (Scheduled CSV Export)
─────────────────────────────

1. Export Configuration in Netsis:
   - Reports → Account Movements
   - Export format: CSV
   - Delimiter: Semicolon (;)
   - Encoding: UTF-8

2. Automated Download:
   - Manual: Upload CSV via UI
   - Scheduled: Configure FTP/API endpoint in .env

3. Supported Formats:
   - Account movements (Tarih, Evrak No, Açıklama, Borç, Alacak)
   - Fixed-width text reports
   - Trial balance (Mizan) exports

4. Sync Schedule:
   - Default: Daily 2 AM
   - Each run ingests latest CSV

Example Data:
```
NETSİS Hesap Hareketleri
Tarih;Evrak No;Açıklama;Borç;Alacak;Bakiye
15.01.2026;F001;Satış Faturası;;5000;100000
16.01.2026;G001;Masraf Ödemesi;2500;;97500
```


MIKRO (Batched XLS/CSV Import)
───────────────────────────────

1. Export Configuration in Mikro:
   - Reports → Account Movements OR Customer Cards
   - Format: CSV or XLS
   - Delimiter: Semicolon (;)

2. Import Methods:
   - Manual upload via UI
   - Scheduled FTP pull
   - Email attachment auto-import

3. Supported Formats:
   - Account movements (Tarih, Evrak No, Açıklama, Giriş, Çıkış)
   - Cari (customer) card movements
   - Cash/Bank movements

4. Batch Processing:
   - Processes up to 1000 rows per sync
   - Skips duplicates automatically
   - Validates Turkish date formats

Example Data:
```
MİKRO Hesap Hareketleri
Tarih,Evrak No,Açıklama,Giriş,Çıkış,Bakiye
15.01.2026,T001,Müşteri Tahsilatı,5000,0,100000
16.01.2026,G001,Tedarikçi Ödemesi,0,2500,97500
```


LOGO TIGER (Real-time CSV Ingestion)
────────────────────────────────────

1. Export Configuration:
   - Reports → Fiş Listesi (Receipt Report)
   - Format: CSV or fixed-width text
   - Delimiter: Semicolon (;)

2. Real-time Processing:
   - Upload CSV via /api/v1/upload endpoint
   - Automatic parsing of multiple formats
   - Immediate transaction ingestion

3. Supported Formats:
   - Fiş raporu (receipt list)
   - Hesap ekstresi (account statement)
   - Mizan raporu (trial balance)

4. Fallback Parsing:
   - Handles non-standard formats
   - Line-based pattern matching
   - Flexible column detection

Example Data:
```
LOGO Fiş Listesi
Tarih;Fiş No;Açıklama;Borç;Alacak;Bakiye
15.01.2026;F001;Satış;0;5000;100000
16.01.2026;G001;Gider;2500;0;97500
```


═══════════════════════════════════════════════════════════════════════════════
Phase 2: Open Banking APIs (Garanti BBVA, Akbank)
═══════════════════════════════════════════════════════════════════════════════

GARANTI BBVA (PSD2 Open Banking)
────────────────────────────────

1. Register Developer Account:
   - https://developer.garantibbva.com.tr
   - Create API application
   - Get Client ID and Client Secret
   - Test in sandbox environment first

2. Configure in .env:
   GARANTI_CLIENT_ID=your_client_id
   GARANTI_CLIENT_SECRET=your_client_secret
   GARANTI_SANDBOX_MODE=true

3. Authentication:
   - OAuth2 client credentials flow
   - Token auto-refreshes
   - Sandbox: https://sandbox-oauth.garantibbva.com.tr
   - Production: https://oauth.garantibbva.com.tr

4. Sync Schedule:
   - Default: Every 4 hours (cron: "0 */4 * * *")
   - Fetches: All accounts + transactions
   - Range: Last 90 days (configurable)

5. API Endpoints:
   - GET /api/v1/accounts → list of accounts
   - GET /api/v1/accounts/{accountId}/transactions → transactions

6. Rate Limits:
   - 100 requests/minute
   - Auto-backoff with retry logic

Example Configuration:
```python
from app.services.data_sync.schemas import BankingSourceConfig

config = BankingSourceConfig(
    source_type=SyncSourceType.GARANTI,
    is_enabled=True,
    schedule_cron="0 */4 * * *",
    client_id="abc123",
    client_secret="secret456",
    sandbox_mode=True,
    account_ids=None,  # None = sync all accounts
)
```


AKBANK (PSD2 Open Banking)
──────────────────────────

1. Register Developer Account:
   - https://developer.akbank.com
   - Create API application
   - Get Client ID and Client Secret
   - Test in sandbox environment first

2. Configure in .env:
   AKBANK_CLIENT_ID=your_client_id
   AKBANK_CLIENT_SECRET=your_client_secret
   AKBANK_SANDBOX_MODE=true

3. Authentication:
   - OAuth2 client credentials flow
   - Token auto-refreshes
   - Sandbox: https://sandbox-oauth.akbank.com.tr
   - Production: https://oauth.akbank.com.tr

4. Sync Schedule:
   - Default: Every 4 hours
   - Fetches: All accounts + transactions + balances
   - Range: Last 90 days (configurable)

5. API Endpoints:
   - GET /api/v1/accounts → list of accounts
   - GET /api/v1/accounts/{accountId}/transactions → transactions
   - GET /api/v1/accounts/{accountId} → account balance

6. Account Balance Sync:
   - Real-time balance updates available
   - Stored in database for CFO dashboard
   - No delay vs. bank

Example Configuration:
```python
config = BankingSourceConfig(
    source_type=SyncSourceType.AKBANK,
    is_enabled=True,
    schedule_cron="0 */4 * * *",
    client_id="xyz789",
    client_secret="secret789",
    sandbox_mode=True,
    account_ids=["ACC-001", "ACC-002"],  # Sync only these accounts
)
```


═══════════════════════════════════════════════════════════════════════════════
Phase 3: Data Quality & Conflict Resolution
═══════════════════════════════════════════════════════════════════════════════

Data Quality Validation
───────────────────────

Automatically runs on all ingested transactions:

1. Duplicate Detection:
   - Signature: (date, amount, vendor)
   - Flags if 3+ consecutive duplicates
   - Cross-source deduplication

2. Anomaly Detection:
   - Amount increases > 500% from average
   - Unusual transaction frequency
   - Statistical outliers (z-score > 3.0)

3. Data Integrity:
   - Empty descriptions flagged
   - Very old transactions (> 1 year)
   - Future-dated transactions
   - Missing required fields

4. Quality Thresholds (Customizable):
   - max_consecutive_duplicates: 3
   - max_amount_increase_percent: 500
   - max_daily_transactions: 10,000
   - outlier_stddev_threshold: 3.0

Example Configuration:
```python
from app.services.data_sync.schemas import DataQualityThresholds

thresholds = DataQualityThresholds(
    max_consecutive_duplicates=3,
    max_amount_increase_percent=500,
    min_transaction_interval_minutes=1,
    max_daily_transactions=10000,
    outlier_stddev_threshold=3.0,
)

validator = DataQualityValidator(thresholds)
```


Conflict Resolution
───────────────────

When same transaction exists in multiple sources, resolver picks highest-priority version:

Priority Order:
1. PSD2 Bank APIs (Garanti, Akbank) — real-time, authoritative
2. Accounting APIs (Paraşüt) — semi-real-time, verified
3. CSV exports (Netsis, Mikro, Logo Tiger) — delayed, may have errors

Conflict Signature: (date, amount) — uniquely identifies transaction.

Example:
```
Input:
  - 2026-01-15: 5000 TRY from Garanti (bank)
  - 2026-01-15: 5000 TRY from Netsis (CSV)

Output:
  - 2026-01-15: 5000 TRY from Garanti (kept, API wins)
```


Audit Trail
───────────

Every sync operation is logged with:
- Source type
- Status (success, partial_failure, failed)
- Transaction counts (synced, failed)
- Warnings and errors
- Data hash (SHA256) for integrity verification
- Duration

Immutable logs stored in `sync_audit_logs` table.

Query Example:
```sql
SELECT source_type, status, transactions_synced, data_hash, started_at
FROM sync_audit_logs
WHERE started_at >= NOW() - INTERVAL '7 days'
ORDER BY started_at DESC;
```


═══════════════════════════════════════════════════════════════════════════════
Scheduling Configuration
═══════════════════════════════════════════════════════════════════════════════

APScheduler manages all recurring syncs.

Cron Format Examples:
  "0 2 * * *"     → Daily at 2 AM
  "0 */4 * * *"   → Every 4 hours
  "0 */30 * * *"  → Every 30 minutes
  "30 9-17 * * 1-5" → Weekdays 9:30 AM to 5:30 PM every hour

Default Schedules:
  Accounting Software: Daily 2 AM (configurable)
  Banking APIs: Every 4 hours (configurable)

Programmatic Configuration:
```python
from app.services.data_sync.scheduler import init_sync_scheduler

scheduler = init_sync_scheduler()

# Custom schedules
scheduler.schedule_parasut_sync(schedule_cron="0 1 * * *")  # 1 AM daily
scheduler.schedule_garanti_sync(schedule_cron="0 */2 * * *")  # Every 2 hours

# List scheduled jobs
jobs = scheduler.get_jobs()
for job_id, details in jobs.items():
    print(f"{job_id}: {details['next_run']}")

# Pause/resume jobs
scheduler.pause_job("sync_parasut")
scheduler.resume_job("sync_parasut")

# Shutdown
scheduler.stop()
```


═══════════════════════════════════════════════════════════════════════════════
API Endpoints
═══════════════════════════════════════════════════════════════════════════════

Upload CSV (Manual)
POST /api/v1/upload
  - Headers: Content-Type: multipart/form-data
  - Body: file (CSV), source_type (accounting software)
  - Response: { "synced": N, "errors": M, "warnings": [...] }

Example:
```bash
curl -X POST http://localhost:8000/api/v1/upload \
  -F "file=@export.csv" \
  -F "source_type=netsis"
```

Get Sync Status
GET /api/v1/data-sync/status
  - Response: { "last_sync": "...", "next_sync": "...", "stats": {...} }

Get Audit Logs
GET /api/v1/data-sync/audit-logs?days=7
  - Response: [ { "source": "...", "status": "...", "timestamp": "..." }, ... ]

Get Scheduled Jobs
GET /api/v1/data-sync/jobs
  - Response: { "jobs": [ { "id": "...", "next_run": "...", "trigger": "..." } ] }


═══════════════════════════════════════════════════════════════════════════════
Troubleshooting
═══════════════════════════════════════════════════════════════════════════════

Common Issues
─────────────

1. "Paraşüt sync disabled"
   → Check .env: PARASUT_OAUTH_CLIENT_ID, PARASUT_OAUTH_CLIENT_SECRET set
   → Check database: oauth_refresh_token stored

2. "Rate limited: sleeping X seconds"
   → Normal behavior, exponential backoff in place
   → If frequent, consider longer schedule intervals

3. "No transactions extracted"
   → Check CSV format matches expected columns
   → Verify date ranges include transactions
   → Check data encodings (UTF-8 required)

4. "Duplicate detected: X items"
   → Normal if same file uploaded twice
   → Conflict resolver will keep highest-priority version
   → Check audit logs for which source won

5. "Amount anomaly detected"
   → Check if legitimate (seasonal, one-time event)
   → Raise max_amount_increase_percent threshold if needed
   → Review data quality warnings in audit logs


Debugging Steps
───────────────

1. Enable DEBUG logging:
   LOG_LEVEL=DEBUG

2. Check logs for sync errors:
   tail -f backend/logs/data_sync.log

3. Query audit trail:
   SELECT * FROM sync_audit_logs
   WHERE started_at >= NOW() - INTERVAL '24 hours'
   ORDER BY started_at DESC;

4. Verify data quality:
   SELECT * FROM sync_audit_logs
   WHERE status != 'success'
   ORDER BY started_at DESC;

5. Test manual upload:
   POST /api/v1/upload with test CSV file


═══════════════════════════════════════════════════════════════════════════════
Security Best Practices
═══════════════════════════════════════════════════════════════════════════════

1. Environment Variables:
   - Store all credentials in .env (never in code)
   - Use strong, unique values
   - Rotate secrets periodically

2. OAuth2 Tokens:
   - Refresh tokens stored encrypted in database
   - Access tokens never persisted
   - Tokens auto-expire after configurable duration

3. API Credentials:
   - Never log credentials
   - Sanitize request/response bodies in audit
   - Use HTTPS for all API calls

4. Data Privacy:
   - Transactions are customer financial data (PII)
   - Ensure GDPR/KVKK compliance
   - Audit all data access

5. Database:
   - Audit logs are immutable (never delete)
   - Use database encryption at rest
   - Restrict direct table access


═══════════════════════════════════════════════════════════════════════════════
Monitoring & Alerts
═══════════════════════════════════════════════════════════════════════════════

Key Metrics to Monitor
──────────────────────

1. Sync Success Rate:
   SELECT
     DATE(started_at) as date,
     COUNT(*) as total_syncs,
     SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count
   FROM sync_audit_logs
   GROUP BY DATE(started_at)
   ORDER BY date DESC;

2. Data Freshness:
   SELECT source_type, MAX(ended_at) as last_sync
   FROM sync_audit_logs
   WHERE status = 'success'
   GROUP BY source_type;

3. Error Trends:
   SELECT source_type, COUNT(*) as error_count
   FROM sync_audit_logs
   WHERE status IN ('failed', 'partial_failure')
     AND started_at >= NOW() - INTERVAL '7 days'
   GROUP BY source_type;

4. Data Quality Issues:
   SELECT source_type, COUNT(warnings) as warning_count
   FROM sync_audit_logs
   WHERE array_length(warnings, 1) > 0
     AND started_at >= NOW() - INTERVAL '7 days'
   GROUP BY source_type;


Recommended Alerts
──────────────────

Set up alerts for:
  - Sync failure 2+ times in a row
  - Sync duration > 5 minutes
  - Error count > 100 in single sync
  - No successful sync for 24+ hours
  - Data quality warnings > 50
"""
