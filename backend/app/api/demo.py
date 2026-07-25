"""
Demo API — /api/v1/demo/seed
============================
Seeds the database with TechNova Yazılım A.Ş. sample financial data
without requiring file upload. Useful for automated demo setup.

Only available when DEMO_MODE=true (default off in production).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

_DEMO_DATA_DIR = Path(__file__).parent.parent.parent.parent / "demo" / "data"
_DEMO_CSV = _DEMO_DATA_DIR / "logo_tiger_2024.csv"


def _is_demo_enabled() -> bool:
    settings = get_settings()
    return bool(settings.demo_mode)


@router.get("/demo/status")
async def demo_status() -> dict[str, Any]:
    """Check if demo mode is active and sample data is available."""
    enabled = _is_demo_enabled()
    return {
        "demo_mode": enabled,
        "sample_data_available": _DEMO_CSV.exists(),
        "company": "TechNova Yazılım A.Ş.",
        "period": "2024-01-01 to 2024-12-31",
        "transaction_count": 163,
    }


@router.post("/demo/seed")
async def seed_demo_data() -> JSONResponse:
    """
    Upload and queue analysis of TechNova sample data.

    Returns job_id that can be used to track analysis progress.
    Only works when DEMO_MODE=true.
    """
    if not _is_demo_enabled():
        raise HTTPException(
            status_code=403,
            detail="Demo mode is not enabled. Set DEMO_MODE=true in .env to use this endpoint.",
        )

    if not _DEMO_CSV.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Sample data not found at {_DEMO_CSV}. Run from repository root.",
        )

    # Import here to avoid circular imports
    import io
    from fastapi import UploadFile
    from app.api.upload import upload_file
    from app.api.analysis import start_analysis

    # Read CSV and create a fake UploadFile
    csv_bytes = _DEMO_CSV.read_bytes()
    fake_file = UploadFile(
        filename="technova_2024_logo_tiger.csv",
        file=io.BytesIO(csv_bytes),
        headers={"content-type": "text/csv"},  # type: ignore[arg-type]
    )

    # Use the real upload handler
    try:
        upload_result = await upload_file(fake_file)
        job_id = upload_result.get("data", {}).get("job_id") or upload_result.get("job_id")

        if not job_id:
            raise HTTPException(status_code=500, detail="Upload failed — no job_id returned")

        logger.info("Demo seed: uploaded file, job_id=%s", job_id)

        return JSONResponse(
            status_code=201,
            content={
                "data": {
                    "job_id": job_id,
                    "status": "uploaded",
                    "company": "TechNova Yazılım A.Ş.",
                    "message": (
                        f"Sample data uploaded. "
                        f"POST /api/v1/analyze/{job_id} to start analysis. "
                        f"GET /api/v1/analysis/{job_id} to check status."
                    ),
                    "dashboard_url": f"/?job={job_id}",
                },
                "error": None,
            },
        )

    except Exception as exc:
        logger.exception("Demo seed failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Demo seed failed: {exc}")


@router.delete("/demo/reset")
async def reset_demo() -> dict[str, Any]:
    """
    Clear all demo data (jobs + transactions).
    Only works when DEMO_MODE=true.
    """
    if not _is_demo_enabled():
        raise HTTPException(status_code=403, detail="Demo mode not enabled.")

    # This is intentionally lightweight — just return instructions
    # Full reset requires DB access which varies by deployment
    return {
        "message": "To fully reset: docker-compose -f docker-compose.demo.yml down -v && docker-compose -f docker-compose.demo.yml up -d",
        "quick_reseed": "POST /api/v1/demo/seed",
    }
