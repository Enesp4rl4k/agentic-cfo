import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.api.upload import router as upload_router
from app.api.analysis import router as analysis_router
from app.api.dashboard import router as dashboard_router
from app.api.reports import router as reports_router
from app.api.corrections import router as corrections_router

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan: create all DB tables on startup.
    In production, use Alembic migrations instead (alembic upgrade head).
    This create_all is a safe no-op if tables already exist.
    """
    from app.database import engine
    from app.database import Base  # noqa: F401 — triggers model registration
    # Import all models so SQLAlchemy knows about them before create_all
    import app.models.analysis_job  # noqa: F401
    import app.models.transaction   # noqa: F401
    import app.models.report        # noqa: F401
    import app.models.category_rule  # noqa: F401

    async with engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured.")
    yield
    # Shutdown: close engine connections
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

app.include_router(upload_router, prefix="/api/v1", tags=["upload"])
app.include_router(analysis_router, prefix="/api/v1", tags=["analysis"])
app.include_router(dashboard_router, prefix="/api/v1", tags=["dashboard"])
app.include_router(reports_router, prefix="/api/v1", tags=["reports"])
app.include_router(corrections_router, prefix="/api/v1", tags=["corrections"])


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}
