from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.analysis_job import AnalysisJob
from app.streaming.sse import sse_manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/stream/{job_id}")
async def stream_job_events(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Server-Sent Events endpoint — streams real-time agent progress for a job.

    Connect with EventSource in the browser:
        const es = new EventSource(`/api/v1/stream/${jobId}`);
        es.onmessage = (e) => {
            const event = JSON.parse(e.data);
            // event.event: "step" | "done" | "error" | "close"
        };

    Events:
        step  — a LangGraph node completed
        done  — pipeline finished (status: completed | failed | awaiting_review)
        error — pipeline failed with message
        close — max connection time reached

    The connection auto-closes when a done/error/close event is received.
    If the job is already completed when the client connects, a synthetic
    done event is sent immediately.
    """
    job = await db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    # If job already finished, stream existing logs then done — no blocking wait
    from app.models.analysis_job import JobStatus

    async def _already_done_stream():
        import json
        from datetime import datetime, timezone
        logs = job.logs or []
        for log in logs:
            yield (
                "data: "
                + json.dumps({
                    "event": "step",
                    "job_id": job_id,
                    "step": log.get("step", ""),
                    "ok": log.get("ok", True),
                    "detail": log.get("detail"),
                    "confidence": log.get("confidence"),
                    "ts": datetime.now(timezone.utc).isoformat(),
                })
                + "\n\n"
            )
        yield (
            "data: "
            + json.dumps({
                "event": "done",
                "job_id": job_id,
                "status": str(job.status),
                "ts": datetime.now(timezone.utc).isoformat(),
            })
            + "\n\n"
        )

    terminal_statuses = {
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.AWAITING_REVIEW,
    }
    if job.status in terminal_statuses:
        return StreamingResponse(
            _already_done_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # Job still running — subscribe to live events
    return StreamingResponse(
        sse_manager.subscribe(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
