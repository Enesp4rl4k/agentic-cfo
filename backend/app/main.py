import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.middleware.audit import AuditLogMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.api.registry import register_routers
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Initialize telemetry early (before any imports that use loggers)
from app.services.telemetry import initialize_telemetry  # noqa: E402
initialize_telemetry(
    log_level=os.environ.get("LOG_LEVEL", "INFO"),
    json_logs=os.environ.get("LOG_FORMAT", "json").lower() == "json",
)

# Initialize Sentry (PROD-2) — graceful if DSN not configured
from app.services.sentry_monitoring import init_sentry  # noqa: E402
init_sentry(settings)

# ── SEC-7: Security validation (centralised in config.validate_production_security) ──
# In prod (USE_SQLITE=False) this raises ValueError and prevents startup.
# In dev (USE_SQLITE=True) it emits warnings only so local dev is not blocked.
try:
    settings.validate_production_security()
except ValueError as _sec_err:
    logger.critical("STARTUP ABORTED — production security check failed: %s", _sec_err)
    raise SystemExit(1) from _sec_err


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan.

    SQLite (dev): create_all ensures tables exist without running Alembic.
    PostgreSQL (prod): skip create_all — run `alembic upgrade head` in CI/CD.
    """
    from app.database import engine, Base  # noqa: F401
    from app.scheduler import start_scheduler, stop_scheduler

    # Register all models so SQLAlchemy sees them before create_all
    import app.models.analysis_job     # noqa: F401
    import app.models.transaction      # noqa: F401
    import app.models.rag_chunk        # noqa: F401
    import app.models.report           # noqa: F401
    import app.models.category_rule    # noqa: F401
    import app.models.anomaly          # noqa: F401
    import app.models.data_source      # noqa: F401
    import app.models.user             # noqa: F401
    import app.models.audit_log        # noqa: F401
    import app.models.organization     # noqa: F401
    import app.models.pilot            # noqa: F401
    import app.models.company_context  # noqa: F401
    import app.models.canonical_transaction  # noqa: F401
    import app.models.sync_run  # noqa: F401
    import app.models.alert_preference     # noqa: F401
    import app.models.in_app_notification  # noqa: F401
    import app.models.agent_job            # noqa: F401
    import app.models.smmm_onay            # noqa: F401  MUHASEBE-4
    import app.models.smmm_portal          # noqa: F401  MUHASEBE-5 (SMMM portal tabloları)

    # SOLID-4: create_all only in SQLite dev mode
    if settings.use_sqlite:
        async with engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("SQLite: tables ensured via create_all.")
    else:
        logger.info("PostgreSQL mode: skipping create_all — expecting Alembic migrations.")

    start_scheduler()
    yield
    stop_scheduler()
    await engine().dispose()
    logger.info("Database engine disposed.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI CFO API",
    description="Agentic financial analysis — P&L, Cash Flow, Forecasting.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── SEC-5: Hardened CORS ──────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization", "Content-Type", "X-API-Key",
        "X-Audit-Reason", "X-Requested-With",
        "Accept", "Accept-Language", "Cache-Control",
    ],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "Retry-After"],
    max_age=600,
)

# ── SEC-4: Rate limiting ──────────────────────────────────────────────────────
app.add_middleware(RateLimitMiddleware)

# ── Audit logging ─────────────────────────────────────────────────────────────
app.add_middleware(AuditLogMiddleware)

# ── SOLID-3: Register all routers via registry ────────────────────────────────
register_routers(app)


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}
