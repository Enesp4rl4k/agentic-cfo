from __future__ import annotations

import warnings
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# ── Known-insecure default values (SEC-7) ─────────────────────────────────────
_INSECURE_SECRETS: frozenset[str] = frozenset({
    "dev-secret-change-in-production",
    "dev-secret-change-in-production-32chars!!",
    "changeme",
    "secret",
    "password",
    "",
})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Product identity ──────────────────────────────────────────────────────
    # Resolved through app/core/branding.py; never typed into a template. The
    # domain defaults to empty on purpose: with no domain configured, contact
    # addresses come back empty and callers say "unconfigured" rather than
    # printing an address the project does not own.
    brand_name: str = "C-Suite"
    brand_domain: str = ""
    brand_app_url: str = "http://localhost:3000"
    brand_contact_email: str = ""
    brand_privacy_email: str = ""
    brand_dpo_email: str = ""

    # OpenAI — optional for dev/test without LLM
    openai_api_key: str = "llm-placeholder-dev"

    # PostgreSQL — optional, falls back to SQLite when not set
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "aicfo"
    postgres_user: str = "aicfo"
    postgres_password: str = "changeme"

    # If set, overrides the postgres_* fields entirely
    database_url_override: str = ""

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
    backend_url:  str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"

    # SSO — Microsoft Entra ID (Azure AD) (SEC-1)
    azure_tenant_id:     str = ""   # "common" for multi-tenant, or specific tenant GUID
    azure_client_id:     str = ""
    azure_client_secret: str = ""

    # SSO — Google Workspace (SEC-1)
    google_client_id:     str = ""
    google_client_secret: str = ""

    # SSO — GitHub (SEC-1, optional)
    github_client_id:     str = ""
    github_client_secret: str = ""

    # Field-level encryption (SEC-2)
    # NOTE: Set field_encryption_key to a 32-byte Fernet key and enable this
    # in production to encrypt OAuth tokens and other sensitive DB fields.
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    field_encryption_key:     str  = ""
    field_encryption_enabled: bool = False  # Set True in production once key is configured

    # Open Banking (INT-2) — per-bank credentials
    openbanking_akbank_client_id:      str = ""
    openbanking_akbank_client_secret:  str = ""
    openbanking_garanti_client_id:     str = ""
    openbanking_garanti_client_secret: str = ""
    openbanking_isbank_client_id:      str = ""
    openbanking_isbank_client_secret:  str = ""
    openbanking_yapikredi_client_id:     str = ""
    openbanking_yapikredi_client_secret: str = ""

    # E-ticaret (INT-4)
    shopify_shop_domain:    str = ""
    shopify_access_token:   str = ""
    trendyol_supplier_id:   str = ""
    trendyol_api_key:       str = ""
    trendyol_api_secret:    str = ""

    # Google Sheets (INT-5) — base64-encoded service account JSON
    google_sheets_service_account: str = ""

    # Webhook / notification outbound (INT-6)
    # NOTE: slack_webhook_url and smtp_* are defined ONCE here.
    # Per-org overrides are stored in the alert_preferences DB table.
    slack_webhook_url:  str = ""          # Global fallback; per-org overrides in DB
    teams_webhook_url:  str = ""
    custom_webhook_url: str = ""

    # WhatsApp Business notifications (optional)
    # Meta Cloud API: https://developers.facebook.com/docs/whatsapp/cloud-api
    whatsapp_phone_number_id: str = ""    # Sender phone number ID from Meta console
    whatsapp_access_token:    str = ""    # System user token (never expires)
    whatsapp_api_version:     str = "v19.0"
    # Twilio WhatsApp fallback (sandbox: https://www.twilio.com/console/sms/whatsapp/sandbox)
    twilio_account_sid:   str = ""
    twilio_auth_token:    str = ""
    twilio_whatsapp_from: str = ""        # e.g. "whatsapp:+14155238886"

    # WhatsApp webhook verification token (self-chosen, set same in Meta console)
    whatsapp_verify_token: str = "agentic-cfo-verify"

    # Slack Bot (for Events API and chat.postMessage)
    slack_bot_token:     str = ""  # xoxb-...
    slack_signing_secret: str = "" # From Slack App Basic Information page

    # SMTP email notifications
    smtp_host:         str = "smtp.gmail.com"
    smtp_port:         int = 587
    smtp_user:         str = ""
    smtp_password:     str = ""
    notification_from: str = "noreply@aicfo.app"

    # TCMB EVDS API (optional — benchmark data falls back to static if not set)
    # Get free key: https://evds2.tcmb.gov.tr/index.php?lang=tr
    tcmb_api_key: str = ""

    # GİB e-Fatura (optional — falls back gracefully if not configured)
    # Test ortamı: https://efatura.gib.gov.tr/test
    gib_vkn:      str  = ""      # Vergi Kimlik Numarası (10 hane)
    gib_username: str  = ""      # e-Fatura portal kullanıcı adı
    gib_password: str  = ""      # e-Fatura portal şifresi
    gib_sandbox:  bool = True    # True = test ortamı

    # Open Banking — Turkish banks (sandbox credentials from developer portals)
    # Akbank: https://developer.akbank.com
    akbank_client_id:     str = ""
    akbank_client_secret: str = ""
    # Garanti BBVA: https://developer.garantibbva.com.tr
    garanti_client_id:     str = ""
    garanti_client_secret: str = ""
    # Sandbox mode (True = no real bank data, safe for development)
    open_banking_sandbox:      bool = True
    open_banking_redirect_uri: str  = "http://localhost:8000/api/v1/open-banking/callback"

    # Storage
    storage_backend:    str = "local"
    storage_local_path: str = "./uploads"

    # LLM — set llm_base_url to use DeepSeek or any OpenAI-compatible API
    llm_model:       str   = "deepseek-chat"
    llm_temperature: float = 0.0
    llm_max_tokens:  int   = 16384
    # DeepSeek: https://api.deepseek.com
    # OpenAI:   https://api.openai.com/v1  (or leave empty)
    llm_base_url: str = "https://api.deepseek.com"

    # File upload
    max_upload_size_mb: int = 10
    # Full-automation mode: upload sonrası analizi otomatik kuyruğa al.
    auto_enqueue_analysis_on_upload: bool = True
    # No Redis? Run the enqueued analysis inline in the API process instead of
    # dropping it. Keeps the upload -> analysis path working on a laptop with no
    # broker. Never a substitute for the worker in production: the job dies with
    # the request process and there is no retry.
    allow_inline_job_fallback: bool = True
    # Confidence gate: min lowest-skill confidence to auto-proceed without a
    # human. Below this the run holds for review. Env-tunable per deployment.
    agent_auto_proceed_min_confidence: float = 0.80
    # RAG maintenance: tamamlanmış job'lar için eksik chunk index backfill.
    rag_backfill_enabled: bool = True
    rag_backfill_lookback_days: int = 14
    rag_embedding_enabled: bool = True
    rag_embedding_model: str = "text-embedding-3-small"
    rag_embedding_dimensions: int = 1536

    # Dev mode: use SQLite instead of PostgreSQL
    use_sqlite: bool = True
    # Seconds a writer waits for the SQLite lock before giving up. The driver
    # default is 0: any concurrent write fails instantly rather than queueing.
    # This buys patience for honest contention — it is not a substitute for
    # closing transactions, which is what actually wedged this app.
    sqlite_busy_timeout_sec: float = 15.0

    # Demo mode: enables /demo/seed endpoint and pre-loaded sample data
    demo_mode:         bool = False
    demo_company_name: str  = "TechNova Yazılım A.Ş."

    # Stripe Billing (STRIPE sprint)
    stripe_secret_key:      str = ""
    stripe_webhook_secret:  str = ""
    stripe_publishable_key: str = ""
    # Stripe Price IDs (set in .env after creating products in Stripe Dashboard)
    stripe_price_starter_monthly:    str = ""
    stripe_price_starter_yearly:     str = ""
    stripe_price_pro_monthly:        str = ""
    stripe_price_pro_yearly:         str = ""
    stripe_price_enterprise_monthly: str = ""
    stripe_price_enterprise_yearly:  str = ""

    # ── Derived properties ────────────────────────────────────────────────────

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        if self.use_sqlite:
            return "sqlite+aiosqlite:///./aicfo_dev.db"
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        if self.use_sqlite:
            return "sqlite:///./aicfo_dev.db"
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",")]

    @property
    def secret_key(self) -> str:
        """JWT signing secret — alias for backend_secret_key."""
        return self.backend_secret_key

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
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )

        if self.field_encryption_enabled and not self.field_encryption_key:
            issues.append(
                "FIELD_ENCRYPTION_ENABLED=true but FIELD_ENCRYPTION_KEY is empty. "
                "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )

        if not self.use_sqlite and issues:
            # Production mode — hard fail
            raise ValueError(
                "Production security check failed:\n"
                + "\n".join(f"  • {i}" for i in issues)
            )

        if issues:
            # Dev/SQLite mode — warn only
            for issue in issues:
                warnings.warn(f"⚠️  Security warning: {issue}", stacklevel=3)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
