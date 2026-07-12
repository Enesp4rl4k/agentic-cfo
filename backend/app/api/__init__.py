from app.api.upload import router as upload_router
from app.api.analysis import router as analysis_router
from app.api.dashboard import router as dashboard_router
from app.api.reports import router as reports_router

__all__ = ["upload_router", "analysis_router", "dashboard_router", "reports_router"]
