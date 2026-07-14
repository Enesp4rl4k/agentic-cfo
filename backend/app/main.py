from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.api.upload import router as upload_router
from app.api.analysis import router as analysis_router
from app.api.dashboard import router as dashboard_router
from app.api.reports import router as reports_router
from app.api.corrections import router as corrections_router
from app.api.insights import router as insights_router
from app.api.auth import router as auth_router

settings = get_settings()

app = FastAPI(
    title="AI CFO API",
    description="Agentic financial analysis — P&L, Cash Flow, Forecasting.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
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
app.include_router(insights_router, prefix="/api/v1", tags=["insights"])
app.include_router(auth_router, prefix="/api/v1", tags=["auth"])


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}
