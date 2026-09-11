import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.registry import register_routers
from app.config import get_settings
from app.middleware.audit import AuditLogMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware

logger = logging.getLogger(__name__)
settings = get_settings()

# Initialize telemetry early (before any imports that use loggers)
from app.services.telemetry import initialize_telemetry

initialize_telemetry(
    log_level=os.environ.get("LOG_LEVEL", "INFO"),
    json_logs=os.environ.get("LOG_FORMAT", "json").lower() == "json",
)

# Initialize Sentry (PROD-2) — graceful if DSN not configured
from app.services.sentry_monitoring import init_sentry

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
    # Register all models so SQLAlchemy sees them before create_all
    import app.models.agent_conflict
    import app.models.agent_job
    import app.models.agent_run
    import app.models.alert_preference
    import app.models.alert_rule
    import app.models.analysis_job
    import app.models.anomaly
    import app.models.audit_log
    import app.models.authority_policy
    import app.models.canonical_eng_signal
    import app.models.canonical_transaction
    import app.models.category_rule
    import app.models.company_context
    import app.models.company_semantic_snapshot
    import app.models.compliance_extended
    import app.models.connector_connection
    import app.models.data_source
    import app.models.defensibility_packet
    import app.models.erp_integration
    import app.models.in_app_notification
    import app.models.institutionalization_snapshot
    import app.models.llm_call_log
    import app.models.organization
    import app.models.pilot
    import app.models.rag_chunk
    import app.models.related_party
    import app.models.report
    import app.models.smmm_onay
    import app.models.smmm_portal
    import app.models.sync_run
    import app.models.sync_schedule
    import app.models.transaction
    import app.models.user  # noqa: F401
    from app.database import Base, engine
    from app.scheduler import start_scheduler, stop_scheduler

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

# ── SEC: Security Headers (OWASP) ─────────────────────────────────────────────
app.add_middleware(SecurityHeadersMiddleware)

# ── PERF: GZip Compression for payloads > 1KB ────────────────────────────────
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ── SEC-4: Rate limiting ──────────────────────────────────────────────────────
app.add_middleware(RateLimitMiddleware)

# ── Audit logging ─────────────────────────────────────────────────────────────
app.add_middleware(AuditLogMiddleware)

# ── SEC-5: Hardened CORS ──────────────────────────────────────────────────────
# Registered LAST on purpose. Starlette runs middleware in reverse registration
# order, so the last one added is the outermost. CORS used to sit *inside* the
# rate limiter, which meant a 429 short-circuited before CORS could run: the
# response went out with no Access-Control-Allow-Origin, the browser reported an
# opaque CORS failure instead of a 429, and the client could not read the
# Retry-After this very config already tries to expose.
#
# Outermost also means preflight OPTIONS are answered here and never reach the
# limiter — a browser's own preflight should not spend a user's request budget.
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
    # A browser hands JavaScript only the CORS-safelisted response headers
    # unless the server names the others here. Everything the client is meant
    # to read has to be on this list, and anything set but missing from it is
    # a header the browser silently drops — see
    # tests/test_cors_exposed_headers.py, which keeps the two in step.
    expose_headers=[
        # Rate limiting: without these a 429 cannot tell the client when to retry.
        "X-RateLimit-Limit", "X-RateLimit-Remaining", "Retry-After", "X-RateLimit-Reset",
        # Downloads. The server names files deliberately — GİB's e-Defter
        # convention among them — and without this the browser cannot see the
        # name, so every download in the app fell back to a filename the client
        # guessed.
        "Content-Disposition",
        # e-Defter: what was produced, and the fact that it cannot be filed.
        "X-EDefter-Entry-Count", "X-EDefter-Line-Count", "X-EDefter-SHA256",
        "X-EDefter-Filable", "X-EDefter-Unfilable-Code",
        # Berat preview: which defter it was derived from, and what it says.
        "X-EDefter-Berat-Of", "X-EDefter-Berat-Unique-ID", "X-EDefter-Berat-Size-MiB",
        "X-EDefter-KDV-Unverified",
        # Journal listing — deliberately not an e-Defter, and it says so.
        "X-Yevmiye-Entry-Count", "X-Yevmiye-SHA256", "X-Not-A-GIB-Filing",
        # Board deck size, so the UI can show it before opening the file.
        "X-PDF-Size-KB",
    ],
    max_age=600,
)

# ── SEC-8: Global Exception Handlers (Prevent traceback leakage) ──────────────
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning("Validation error on %s %s: %s", request.method, request.url.path, exc.errors())
    return JSONResponse(
        status_code=422,
        content={
            "data": None,
            "error": "Geçersiz istek parametreleri",
            "details": exc.errors(),
            "status_code": 422,
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "data": None,
            "error": exc.detail if isinstance(exc.detail, str) else "İstek hatası",
            "details": exc.detail if not isinstance(exc.detail, str) else None,
            "status_code": exc.status_code,
        },
    )


@app.exception_handler(Exception)
async def global_unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("CRITICAL UNHANDLED ERROR on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={
            "data": None,
            "error": "İç sunucu hatası oluştu. Lütfen sistem yöneticisiyle iletişime geçiniz.",
            "status_code": 500,
        },
    )


# ── SOLID-3: Register all routers via registry ────────────────────────────────
register_routers(app)


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}
