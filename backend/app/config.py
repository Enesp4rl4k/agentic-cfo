from __future__ import annotations

import logging
import warnings
from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── Known-insecure default values (SEC-7) ─────────────────────────────────────
_INSECURE_SECRETS: frozenset[str] = frozenset(
    {
        "dev-secret-change-in-production",
        "dev-secret-change-in-production-32chars!!",
        "changeme",
        "secret",
        "password",
        "",
    }
)


_SSL_MODES: frozenset[str] = frozenset(
    {"", "disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
)


def _for_driver(url: str, parameter: str) -> str:
    """The URL's TLS mode under the spelling one driver reads.

    asyncpg reads `ssl`, psycopg reads `sslmode`, and each refuses the other's. A URL
    without a mode comes back as it was.
    """
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    mode = next((value for key, value in query if key in ("ssl", "sslmode")), None)
    if mode is None:
        return url
    rest = [(key, value) for key, value in query if key not in ("ssl", "sslmode")]
    return urlunsplit(parts._replace(query=urlencode([*rest, (parameter, mode)])))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Product identity ──────────────────────────────────────────────────────
    # Resolved through app/core/branding.py; never typed into a template. The
    # domain defaults to empty on purpose: with no domain configured, contact
    # addresses come back empty and callers say "unconfigured" rather than
    # printing an address the project does not own.
    brand_name: str = "Tiphys"
    brand_domain: str = ""
    brand_app_url: str = "http://localhost:3000"
    brand_contact_email: str = ""
    brand_privacy_email: str = ""
    brand_dpo_email: str = ""

    # OpenAI — optional for dev/test without LLM
    openai_api_key: str = "llm-placeholder-dev"

    # Cash radar: a bank-statement balance older than this many days is shown as
    # "last known", not as today's cash. Plan v10/v11 name no value; 7 days (one
    # week of the radar) is the working default.
    radar_balance_stale_after_days: int = 7

    # Documents held as possible duplicates are not in the radar (a held row opens no open item). The
    # Monday briefing says so in its headline when what they would add to the week's payments, or to
    # payments with no date, is at least this share of the week's outflow (or the outflow is nil), or
    # when a held payable's size cannot be added up (foreign currency). 10% is a working default: no
    # plan names one, and a smaller share is rounding for a company's weekly cash.
    radar_held_material_ratio: float = 0.10

    # PostgreSQL — optional, falls back to SQLite when not set
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "aicfo"
    postgres_user: str = "aicfo"
    postgres_password: str = "changeme"
    # TLS to the database: a managed Postgres refuses plain connections. Empty adds
    # nothing, which is what a database inside the same cluster wants.
    postgres_sslmode: str = ""

    # If set, overrides the postgres_* fields entirely
    database_url_override: str = ""

    @field_validator("postgres_sslmode")
    @classmethod
    def _known_ssl_mode(cls, value: str) -> str:
        if value not in _SSL_MODES:
            raise ValueError(
                f"postgres_sslmode must be one of {sorted(_SSL_MODES - {''})}, got {value!r}"
            )
        return value

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    # ARQ queue partitioning (analysis vs maintenance) + backpressure knobs
    arq_analysis_queue_name: str = "arq:queue:analysis"
    # Enqueue-side connect attempts. Low on purpose: a blocked HTTP request is
    # worse than an early fallback. The worker process keeps ARQ's own defaults.
    arq_producer_conn_retries: int = 1
    arq_maintenance_queue_name: str = "arq:queue:maintenance"
    arq_analysis_max_jobs: int = 10
    arq_maintenance_max_jobs: int = 3

    # App
    backend_secret_key: str = "dev-secret-change-in-production"
    backend_cors_origins: str = "http://localhost:3000,http://localhost:3001,http://localhost:3002"
    backend_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"

    # SSO — Microsoft Entra ID (Azure AD) (SEC-1)
    azure_tenant_id: str = ""  # "common" for multi-tenant, or specific tenant GUID
    azure_client_id: str = ""
    azure_client_secret: str = ""

    # SSO — Google Workspace (SEC-1)
    google_client_id: str = ""
    google_client_secret: str = ""

    # SSO — GitHub (SEC-1, optional)
    github_client_id: str = ""
    github_client_secret: str = ""

    # Field-level encryption (SEC-2)
    # NOTE: Set field_encryption_key to a 32-byte Fernet key and enable this
    # in production to encrypt OAuth tokens and other sensitive DB fields.
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    field_encryption_key: str = ""
    field_encryption_enabled: bool = False  # Set True in production once key is configured

    # Open Banking (INT-2) — per-bank credentials
    openbanking_akbank_client_id: str = ""
    openbanking_akbank_client_secret: str = ""
    openbanking_garanti_client_id: str = ""
    openbanking_garanti_client_secret: str = ""
    openbanking_isbank_client_id: str = ""
    openbanking_isbank_client_secret: str = ""
    openbanking_yapikredi_client_id: str = ""
    openbanking_yapikredi_client_secret: str = ""

    # E-ticaret (INT-4)
    shopify_shop_domain: str = ""
    shopify_access_token: str = ""
    trendyol_supplier_id: str = ""
    trendyol_api_key: str = ""
    trendyol_api_secret: str = ""

    # Google Sheets (INT-5) — base64-encoded service account JSON
    google_sheets_service_account: str = ""

    # Webhook / notification outbound (INT-6)
    # NOTE: slack_webhook_url and smtp_* are defined ONCE here.
    # Per-org overrides are stored in the alert_preferences DB table.
    slack_webhook_url: str = ""  # Global fallback; per-org overrides in DB
    teams_webhook_url: str = ""
    custom_webhook_url: str = ""

    # WhatsApp Business notifications (optional)
    # Meta Cloud API: https://developers.facebook.com/docs/whatsapp/cloud-api
    whatsapp_phone_number_id: str = ""  # Sender phone number ID from Meta console
    whatsapp_access_token: str = ""  # System user token (never expires)
    whatsapp_api_version: str = "v19.0"
    # Twilio WhatsApp fallback (sandbox: https://www.twilio.com/console/sms/whatsapp/sandbox)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""  # e.g. "whatsapp:+14155238886"

    # WhatsApp webhook verification token (self-chosen, set same in Meta console). No default: a public
    # default let anyone pass the verification handshake. Unset (or no app secret) = the WhatsApp webhook is
    # disabled (404) and startup says so.
    whatsapp_verify_token: str = ""

    # Slack Bot (for Events API and chat.postMessage)
    slack_bot_token: str = ""  # xoxb-...
    slack_signing_secret: str = ""  # From Slack App Basic Information page
    # Meta App Secret — signs every WhatsApp webhook (X-Hub-Signature-256).
    # Without it the webhook refuses all posts rather than accepting unsigned ones.
    whatsapp_app_secret: str = ""

    # E-postayla veri. The domain whose mail a provider (Mailgun, SendGrid)
    # receives and posts to /email/inbound, and the secret it sends with each
    # post. Without both, the inbox is off: addresses are not handed out and
    # the webhook refuses every post rather than accepting unsigned mail.
    email_ingest_domain: str = ""
    email_inbound_secret: str = ""

    # Paraşüt: the platform's one registered application. With it a person
    # connects by logging in to Paraşüt; without it the button says Paraşüt
    # is not available here. The callback is {backend_url}/api/v1/erp/parasut/callback.
    parasut_client_id: str = ""
    parasut_client_secret: str = ""

    # SMTP email notifications
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    notification_from: str = "noreply@aicfo.app"

    # The outbox sender (app/services/outbox_transport.py), the only code that talks to a
    # mail, WhatsApp, Slack or webhook endpoint. "auto": a recorded no-op in development
    # (SQLite) and under pytest, live otherwise. "live" / "noop" force it.
    outbox_transport: str = "auto"
    # Deliver an immediate-class message (invite, password reset) as soon as it is written,
    # instead of at the scheduler's next five-minute pass.
    outbox_kick_on_enqueue: bool = True

    # A new account cannot sign in or act until its address is verified (owner decision). Turned off
    # by tests that are not about it; a deployment with no mail sender configured must also turn it off
    # or nobody can verify (startup says so, see validate_production_security).
    email_verification_required: bool = True
    email_verification_expire_hours: int = 48

    # Client address (app/core/client_ip.py). Default: trust no proxy, use the socket peer and ignore
    # X-Forwarded-For. Behind a reverse proxy set TRUSTED_PROXY_CIDRS (its network) or
    # TRUSTED_PROXY_COUNT (how many proxies sit in front of the app).
    trusted_proxy_count: int = 0
    trusted_proxy_cidrs: str = ""

    # Password reset (POST /auth/forgot-password, /auth/reset-password)
    password_reset_expire_minutes: int = 30
    # Per (address, client IP) per hour. The address alone is not a key: one IP could use up the
    # allowance a real owner needs. Mail flooding is stopped by the cool-down below instead.
    password_reset_per_email_per_hour: int = 3
    # At most one reset / verification / "you already have an account" mail per address and kind
    # in this many minutes, however many requests arrive from however many IPs. The answer is the
    # same; the earlier mail's link is still valid (reset 30 min, verification 48 h), so the owner
    # is never locked out by someone else's requests. Keep it below the reset lifetime.
    auth_mail_cooldown_minutes: int = 15
    # A request takes at least this long whether or not the account exists.
    password_reset_response_floor_seconds: float = 0.5

    # TCMB EVDS API (optional — benchmark data falls back to static if not set)
    # Get free key: https://evds2.tcmb.gov.tr/index.php?lang=tr
    tcmb_api_key: str = ""

    # GİB e-Fatura (optional — falls back gracefully if not configured)
    # Test ortamı: https://efatura.gib.gov.tr/test
    gib_vkn: str = ""  # Vergi Kimlik Numarası (10 hane)
    gib_username: str = ""  # e-Fatura portal kullanıcı adı
    gib_password: str = ""  # e-Fatura portal şifresi
    gib_sandbox: bool = True  # True = test ortamı
    # GİB e-Defter web servisi ortamı. "prod" yalnızca biri bilerek yazarsa;
    # imzalayıcı olmadan hiçbir ortamda gönderim yapılmaz.
    gib_edefter_env: str = "test"

    # Open Banking — Turkish banks (sandbox credentials from developer portals)
    # Akbank: https://developer.akbank.com
    akbank_client_id: str = ""
    akbank_client_secret: str = ""
    # Garanti BBVA: https://developer.garantibbva.com.tr
    garanti_client_id: str = ""
    garanti_client_secret: str = ""
    # Sandbox mode (True = no real bank data, safe for development)
    open_banking_sandbox: bool = True
    open_banking_redirect_uri: str = "http://localhost:8000/api/v1/open-banking/callback"

    # Storage
    storage_backend: str = "local"
    storage_local_path: str = "./uploads"

    # KVKK org erasure: `hard_delete` stays unreachable through the API until the
    # retention question (plan G19) is decided by the owner/lawyer.
    org_erasure_hard_delete_enabled: bool = False
    # KVKK erasure: days between the owner's confirmation and the destructive step (0 = immediately); the owner can cancel until then
    erasure_cooling_off_days: int = 7
    # Company export: hours a finished bundle can be downloaded before it is deleted
    data_export_ttl_hours: int = 24
    # Company export: size bound in MB; uploaded files that would exceed it are listed as omitted in the manifest
    data_export_max_mb: int = 500
    # Retention job: true (the default) only COUNTS the dry-run purges (counts in retention_runs and the log); the
    # always-enforced ones (checkpoints, erasure leftovers) delete anyway. Production warns while true (preflight
    # `retention_dry_run`): set false after reading the first report (docs/ops/first-deploy-checklist.md)
    retention_dry_run: bool = True
    # Retention: days after which a processed upload's raw file, raw text and text chunks are removed (0 = keep; Turkish accounting-record periods are an open lawyer question)
    retention_upload_days: int = 0
    # Retention: days after delivery that a sent outbox message's body is removed (recipient, status and times stay)
    retention_outbox_body_days: int = 90
    # Retention: days after expiry that password-reset, verification tokens and spent or expired invitations are deleted
    retention_token_days: int = 30
    # Retention: days after which an audit-log row's IP address is truncated and its browser string removed (the row stays)
    retention_audit_ip_days: int = 365
    # Retention: days after an agent run's last checkpoint that its LangGraph checkpoints are deleted (Postgres; 0 = keep)
    retention_checkpoint_days: int = 3
    # Retention: days after which in-app notifications are deleted
    retention_notification_days: int = 180
    # Retention: days after which alert history rows are deleted
    retention_alert_history_days: int = 365
    # Version of the privacy notice a person must have accepted; change it to ask everyone again (the text is the owner's documents, linked)
    privacy_notice_version: str = "taslak-1"
    # Version of the terms of use a person must have accepted
    terms_version: str = "taslak-1"
    # Where the privacy notice text lives (a link; the product does not hold legal text)
    privacy_notice_url: str = ""
    # Where the terms of use live (a link)
    terms_url: str = ""
    # KVKK member erasure: key of the HMAC that derives the stable `member-<hex>` pseudonym; empty = BACKEND_SECRET_KEY.
    # Changing it changes the pseudonym of members erased AFTER the change (earlier ones keep theirs), so set it once.
    erasure_pseudonym_secret: str = ""

    # LLM — set llm_base_url to use DeepSeek or any OpenAI-compatible API
    llm_model: str = "deepseek-chat"
    # Optional per-tier model ids (see app.platform.model_catalog). Unset = use
    # llm_model, so the single LLM_MODEL variable keeps working.
    llm_model_cheap: str | None = None
    llm_model_strong: str | None = None
    # Optional USD price per 1K tokens, keyed by model id:
    #   LLM_MODEL_PRICES='{"deepseek-chat": [0.00027, 0.0011]}'  ([in, out])
    # A model that is not listed has an unknown price; its cost is recorded as null.
    llm_model_prices: dict[str, tuple[float, float]] = {}
    llm_temperature: float = 0.0
    llm_max_tokens: int = 16384
    # DeepSeek: https://api.deepseek.com
    # OpenAI:   https://api.openai.com/v1  (or leave empty)
    llm_base_url: str = "https://api.deepseek.com"
    # What may leave for the provider (app.platform.llm_egress; docs/kvkk/yapay-zeka-veri-akisi.md):
    #   off     no LLM and no embedding call at all (deterministic paths only)
    #   masked  identifiers and the names the books hold are replaced by placeholders first (default)
    #   raw     the text goes as it is: today's behaviour before masking existed. Always an explicit choice.
    llm_data_mode: Literal["off", "masked", "raw"] = "masked"
    # allow: uploaded-document text goes through the mode above. never: no raw document text is sent in any
    # mode; extraction falls back to the deterministic parsers and says the AI step was skipped.
    llm_document_text: Literal["allow", "never"] = "allow"
    # May an organisation's owner choose a MORE permissive mode than LLM_DATA_MODE? false: LLM_DATA_MODE is the
    # operator's ceiling and an owner can only tighten it (masked -> off); true: the owner's choice stands.
    llm_org_may_relax: bool = False
    # The chat's Think -> Plan -> Act -> Synthesize loop (`use_reasoning=true`, app/services/reasoning_loop.py). Off
    # by default: when off, `use_reasoning` is ignored and the reply says so. At most 6 model calls per question (think,
    # plan, up to 3 act steps, synthesize), all inside REASONING_LOOP_TIMEOUT_SECONDS; past it the labelled template.
    reasoning_loop_enabled: bool = False
    reasoning_loop_timeout_seconds: float = 60.0

    # Platform operators: comma-separated user e-mails allowed to mint pilot
    # invites and read every company's pilot feedback (platform-wide data, not
    # a company owner's). Empty = nobody.
    platform_operator_emails: str = ""
    # Shown to someone locked out by their company's IP allow-list: where to ask for its removal
    # (an e-mail address or a URL). Unset: "platform yöneticinize başvurun".
    support_contact: str = ""

    # Who may create an account (POST /auth/register, SSO sign-up, POST /org/create).
    #   open         anyone (development, the demo stack, the e2e journey)
    #   invite_only  a valid pilot invite (issued by a platform operator, e-mailed to the invitee) or an
    #                organisation invite; a platform operator's own address may register once, to bootstrap
    #   closed       like invite_only, but a pilot invite no longer creates a company either
    # Default invite_only: a host that forgets the setting is closed, not open.
    registration_mode: Literal["open", "invite_only", "closed"] = "invite_only"
    pilot_invite_expire_days: int = 14

    # Operator notifications (services/operator_alerts.py): a mail to PLATFORM_OPERATOR_EMAILS through the
    # outbox. One alert code, subject and window is sent once per cool-down, however often it fires.
    operator_alert_cooldown_minutes: int = 360
    # A scheduled job (per company and period) that failed this many times alerts the operators.
    job_failure_alert_after: int = 3
    # A destination (company, channel, address) with this many failed outbox rows in 24 hours alerts them.
    outbox_failure_alert_threshold: int = 5
    # Shared secret of POST /platform/ops/backup-report (the backup cron). Empty: the endpoint answers 404.
    ops_report_token: str = ""
    # The newest successful backup report older than this many hours alerts the operators.
    backup_max_age_hours: int = 30

    # File upload
    max_upload_size_mb: int = 10
    # Reading an uploaded PDF (app/services/pdf_isolation.py): it runs in a child process with these limits.
    pdf_max_pages: int = 500
    pdf_parse_timeout_seconds: int = 180          # text path, whole document
    pdf_ocr_seconds_per_page: int = 30            # added per page that needs OCR (Tesseract), so a long scan is not refused for length
    pdf_child_memory_mb: int = 1536               # RLIMIT_AS of a PDF parser child (Linux): a generous BACKSTOP above its measured peak; docs/ops/parser-sizing.md
    parse_child_rss_mb: int = 800                 # resident memory limit of one parser child plus its Tesseract: ENFORCED by the parent (over it: the group is killed, "memory" refusal) and what the container is sized for
    pdf_parse_concurrency: int = 1                # simultaneous parser children per PROCESS (PDF and spreadsheet children share it)
    parse_process_count: int = 2                  # API worker processes in this container (uvicorn --workers); an arq worker container sets 1
    parse_queue_wait_seconds: int = 60            # an upload waiting for a free parser slot longer than this is refused as "busy"
    # Reading an uploaded spreadsheet or CSV (app/services/sheet_isolation.py): the same child mechanism, these limits.
    sheet_parse_timeout_seconds: int = 90
    sheet_child_memory_mb: int = 512              # RLIMIT_AS of a spreadsheet/CSV child (measured peak about 110 MB for 600k cells)
    sheet_max_uncompressed_mb: int = 128          # total uncompressed size of an .xlsx's zip members (directory AND while reading)
    sheet_max_zip_members: int = 500
    sheet_max_rows: int = 200_000                 # per sheet
    sheet_max_columns: int = 256
    sheet_max_cells: int = 1_000_000              # per file
    sheet_max_csv_line_chars: int = 100_000
    # Full-automation mode: upload sonrası analizi otomatik kuyruğa al.
    auto_enqueue_analysis_on_upload: bool = True
    # No Redis? Run the enqueued analysis inline in the API process instead of
    # dropping it. Keeps the upload -> analysis path working on a laptop with no
    # broker. Never a substitute for the worker in production: the job dies with
    # the request process and there is no retry.
    # Unset, it follows the database: on with SQLite (a laptop), off with
    # Postgres. It used to default to on everywhere, so a staging or production
    # API with a Redis blip ran analyses in-process, unretried, and said so only
    # in a log line. Turning it on with Postgres is refused at startup.
    allow_inline_job_fallback: bool | None = None
    # Confidence gate: min lowest-skill confidence to auto-proceed without a
    # human. Below this the run holds for review. Env-tunable per deployment.
    agent_auto_proceed_min_confidence: float = 0.80
    # RAG maintenance: tamamlanmış job'lar için eksik chunk index backfill.
    rag_backfill_enabled: bool = True
    rag_backfill_lookback_days: int = 14
    rag_embedding_enabled: bool = True
    rag_embedding_model: str = "text-embedding-3-small"
    rag_embedding_dimensions: int = 1536

    # ── Reliability (DDIA) ────────────────────────────────────────────────────
    # A claimed analysis job holds a lease for this long. The worker's own
    # bound is job_timeout (600s); the lease exceeds it so a live worker is
    # never reaped, while a dead one is (Ch.7 — a lease, not a heartbeat).
    job_lease_seconds: int = 900
    # A job that was enqueued (lease stamped) but never claimed within this
    # window failed to reach a worker: the reaper marks it failed so the user
    # can re-run instead of waiting forever. Jobs nobody enqueued (manual
    # trigger pending) have no lease and are never touched.
    stale_pending_minutes: int = 60
    # agent_runs stuck in `running` longer than this are ledger-marked failed.
    stale_agent_run_minutes: int = 30
    # Run the stuck-job reaper on the scheduler (every 10 minutes).
    reaper_enabled: bool = True
    # APScheduler: one process should run each cron; all are additionally
    # wrapped in a Redis NX lock, so this only matters without a broker.
    scheduler_enabled: bool = True
    # Which process type owns the crons. "api" (default) keeps dev without a
    # worker working; staging/prod set "worker" so only the arq analysis
    # worker runs APScheduler and API processes never do batch work.
    scheduler_process: Literal["api", "worker"] = "api"
    # SSE live subscriptions per worker process. Docstring promised 50 for a
    # long time while nothing enforced it; the endpoint now returns 429.
    sse_max_connections: int = 50

    # Postgres connection pool, per process. Capacity math for operators:
    #   (uvicorn workers + ARQ workers) × (pool_size + max_overflow + 5)
    #   must stay below Postgres max_connections (default 100). The + 5 is the
    #   LangGraph checkpoint pool (`checkpointer._postgres_saver`, max_size=5),
    #   opened by every process that builds the saver (API, both workers).
    # With the shipped defaults (2+2 processes × 35) that is 140 — under the
    # production compose's max_connections=200; raise max_connections or lower
    # these before raising process counts.
    db_pool_size: int = 20
    db_max_overflow: int = 10

    # LangGraph checkpoint store (LANGGRAPH_CHECKPOINT). sqlite keeps it in this
    # file (dev / single-node); postgres is the production path
    # (`langgraph-checkpoint-postgres`, pinned). In production a configured
    # store that cannot be built stops the process (CheckpointerUnavailable);
    # only development and tests fall back to memory, with a warning. Every run
    # has its own thread and nothing resumes one (checkpointer.py).
    checkpoint_sqlite_path: str = "./langgraph_checkpoints.sqlite"

    # Dev mode: use SQLite instead of PostgreSQL
    use_sqlite: bool = True
    # Seconds a writer waits for the SQLite lock before giving up. The driver
    # default is 0: any concurrent write fails instantly rather than queueing.
    # This buys patience for honest contention — it is not a substitute for
    # closing transactions, which is what actually wedged this app.
    sqlite_busy_timeout_sec: float = 15.0

    # Demo mode: enables /demo/seed endpoint and pre-loaded sample data
    demo_mode: bool = False
    demo_company_name: str = "TechNova Yazılım A.Ş."
    # D4: konuk workspace TTL (saat) — demo cron'u süresi dolan konuk org'larının
    # iş verisini purge eder (demo job + context + semantic; kimlik satırları kalır).
    demo_guest_ttl_hours: int = 24

    # Stripe Billing (STRIPE sprint)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_publishable_key: str = ""
    # Stripe Price IDs (set in .env after creating products in Stripe Dashboard)
    stripe_price_starter_monthly: str = ""
    stripe_price_starter_yearly: str = ""
    stripe_price_pro_monthly: str = ""
    stripe_price_pro_yearly: str = ""
    stripe_price_enterprise_monthly: str = ""
    stripe_price_enterprise_yearly: str = ""

    # ── Derived properties ────────────────────────────────────────────────────

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return _for_driver(self.database_url_override, "ssl")
        if self.use_sqlite:
            return "sqlite+aiosqlite:///./aicfo_dev.db"
        tls = f"?ssl={self.postgres_sslmode}" if self.postgres_sslmode else ""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}{tls}"
        )

    @property
    def database_url_sync(self) -> str:
        # The async URL honoured the override and this did not, so a caller
        # asking for the sync DSN (agent_memory's pgvector path) got the
        # postgres_* defaults — or a SQLite path — while the app itself was
        # talking to the overridden database.
        if self.database_url_override:
            return _for_driver(
                self.database_url_override.replace("+asyncpg", "").replace("+aiosqlite", ""),
                "sslmode",
            )
        if self.use_sqlite:
            return "sqlite:///./aicfo_dev.db"
        tls = f"?sslmode={self.postgres_sslmode}" if self.postgres_sslmode else ""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}{tls}"
        )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",")]

    @property
    def secret_key(self) -> str:
        """JWT signing secret — alias for backend_secret_key."""
        return self.backend_secret_key

    @model_validator(mode="after")
    def _inline_fallback_follows_the_database(self) -> Settings:
        if self.allow_inline_job_fallback is None:
            self.allow_inline_job_fallback = self.use_sqlite
        return self

    def validate_production_security(self) -> None:
        """
        Raise ValueError if security-critical settings are insecure.

        Call this from application startup when USE_SQLITE=False (i.e. production).
        In SQLite/dev mode, only a warning is emitted so local dev is not blocked.
        """
        issues: list[str] = []

        if self.backend_secret_key in _INSECURE_SECRETS:
            issues.append(
                "BACKEND_SECRET_KEY is set to an insecure default. "
                'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
            )

        if self.field_encryption_enabled and not self.field_encryption_key:
            issues.append(
                "FIELD_ENCRYPTION_ENABLED=true but FIELD_ENCRYPTION_KEY is empty. "
                'Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            )

        if self.allow_inline_job_fallback and not self.use_sqlite:
            issues.append(
                "ALLOW_INLINE_JOB_FALLBACK=true with Postgres: an analysis would run "
                "inside the API process when Redis is unreachable, with no retry and "
                "lost on restart. Leave it unset; the worker owns analyses."
            )

        if (
            self.email_verification_required
            and not self.use_sqlite
            and self.outbox_transport != "noop"
            and not (self.smtp_user and self.smtp_password)
        ):
            # Not a hard failure (a demo or staging may run without mail), but never silent: with
            # verification required and no sender, a new account can never be verified.
            message = (
                "EMAIL_VERIFICATION_REQUIRED is on but no mail sender is configured (SMTP_USER / "
                "SMTP_PASSWORD): new accounts will wait for a verification e-mail that cannot be sent. "
                "Configure SMTP, or set EMAIL_VERIFICATION_REQUIRED=false for a deployment without mail."
            )
            logging.getLogger(__name__).error(message)
            warnings.warn(f"Registration warning: {message}", stacklevel=3)

        if not self.use_sqlite and issues:
            # Production mode — hard fail
            raise ValueError(
                "Production security check failed:\n" + "\n".join(f"  • {i}" for i in issues)
            )

        if issues:
            # Dev/SQLite mode — warn only
            for issue in issues:
                warnings.warn(f"⚠️  Security warning: {issue}", stacklevel=3)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
