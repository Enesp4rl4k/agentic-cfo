import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.middleware.audit import AuditLogMiddleware

from app.config import get_settings
from app.api.upload import router as upload_router
from app.api.analysis import router as analysis_router
from app.api.dashboard import router as dashboard_router
from app.api.reports import router as reports_router
from app.api.corrections import router as corrections_router
from app.api.anomalies import router as anomalies_router
from app.api.chat import router as chat_router
from app.api.datasource import router as datasource_router
from app.api.stream import router as stream_router
from app.api.sensitivity import router as sensitivity_router
from app.api.alerts import router as alerts_router
from app.api.brief import router as brief_router
from app.api.auth import router as auth_router
from app.api.benchmark import router as benchmark_router
from app.api.open_banking import router as open_banking_router
from app.api.causal import router as causal_router
from app.api.efatura import router as efatura_router
from app.api.cto import router as cto_router
from app.api.ceo import router as ceo_router
from app.api.cmo import router as cmo_router
from app.api.coo import router as coo_router
from app.api.chro import router as chro_router
from app.api.compliance import router as compliance_router
from app.api.risk import router as risk_router
from app.api.audit import router as audit_router
from app.api.demo import router as demo_router
from app.api.org import router as org_router
from app.api.pilot import router as pilot_router

logger = logging.getLogger(__name__)
settings = get_settings()

# Initialize telemetry early (before any imports that use loggers)
from app.services.telemetry import initialize_telemetry  # noqa: E402
initialize_telemetry(
    log_level=os.environ.get("LOG_LEVEL", "INFO"),
    json_logs=os.environ.get("LOG_FORMAT", "json").lower() == "json",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan: create all DB tables on startup.
    In production, use Alembic migrations instead (alembic upgrade head).
    This create_all is a safe no-op if tables already exist.
    """
    from app.database import engine
    from app.database import Base  # noqa: F401 — triggers model registration
    from app.scheduler import start_scheduler, stop_scheduler
    # Import all models so SQLAlchemy knows about them before create_all
    import app.models.analysis_job  # noqa: F401
    import app.models.transaction   # noqa: F401
    import app.models.report        # noqa: F401
    import app.models.category_rule  # noqa: F401
    import app.models.anomaly        # noqa: F401
    import app.models.data_source    # noqa: F401
    import app.models.user           # noqa: F401
    import app.models.audit_log      # noqa: F401
    import app.models.organization   # noqa: F401
    import app.models.pilot          # noqa: F401

    async with engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured.")

    start_scheduler()

    yield

    stop_scheduler()
    await engine().dispose()
    logger.info("Database engine disposed.")


app = FastAPI(
    title="AI CFO API",
    description="Agentic financial analysis — P&L, Cash Flow, Forecasting.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuditLogMiddleware)

app.include_router(upload_router,      prefix="/api/v1", tags=["upload"])
app.include_router(stream_router,      prefix="/api/v1", tags=["stream"])
app.include_router(analysis_router,    prefix="/api/v1", tags=["analysis"])
app.include_router(auth_router,         prefix="/api/v1", tags=["auth"])
app.include_router(benchmark_router,    prefix="/api/v1", tags=["benchmark"])
app.include_router(open_banking_router, prefix="/api/v1", tags=["open-banking"])
app.include_router(causal_router,       prefix="/api/v1", tags=["causal"])
app.include_router(efatura_router,      prefix="/api/v1", tags=["e-fatura"])
app.include_router(sensitivity_router, prefix="/api/v1", tags=["sensitivity"])
app.include_router(alerts_router,      prefix="/api/v1", tags=["alerts"])
app.include_router(brief_router,       prefix="/api/v1", tags=["brief"])
app.include_router(dashboard_router,   prefix="/api/v1", tags=["dashboard"])
app.include_router(reports_router,     prefix="/api/v1", tags=["reports"])
app.include_router(corrections_router, prefix="/api/v1", tags=["corrections"])
app.include_router(anomalies_router,   prefix="/api/v1", tags=["anomalies"])
app.include_router(chat_router,        prefix="/api/v1", tags=["chat"])
app.include_router(datasource_router,  prefix="/api/v1", tags=["datasource"])
app.include_router(cto_router,         prefix="/api/v1", tags=["cto"])
app.include_router(ceo_router,         prefix="/api/v1", tags=["ceo"])
app.include_router(cmo_router,         prefix="/api/v1", tags=["cmo"])
app.include_router(coo_router,         prefix="/api/v1", tags=["coo"])
app.include_router(chro_router,        prefix="/api/v1", tags=["chro"])
app.include_router(compliance_router,  prefix="/api/v1", tags=["compliance"])
app.include_router(risk_router,        prefix="/api/v1", tags=["risk"])
app.include_router(audit_router,       prefix="/api/v1", tags=["audit"])
app.include_router(demo_router,        prefix="/api/v1", tags=["demo"])
app.include_router(org_router,         prefix="/api/v1", tags=["org"])
app.include_router(pilot_router,       prefix="/api/v1", tags=["pilot"])


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}
