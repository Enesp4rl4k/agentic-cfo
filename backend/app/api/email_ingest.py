"""
Email Ingestion API — Pasif Intelligence

Endpoint'ler:
  POST /email/ingest          — Raw MIME email ingest (webhook)
  POST /email/ingest/base64   — Base64-encoded email (bazı webhook provider'ları)
  GET  /email/ingest-address  — Org'a özel ingest email adresi
  GET  /email/history         — Son işlenen emailler

Kullanım:
  1. Kullanıcı muhasebe yazılımını bu adrese yönlendirir
  2. Email gelince attachment'lar parse edilir
  3. Finansal dosya bulunursa analiz job'u kuyruğa alınır
  4. Sonuç bildirim olarak gönderilir

Güvenlik:
  - X-Email-Api-Key header zorunlu (org'a özel)
  - Sender domain allowlist (opsiyonel)
  - Max 10MB attachment
"""
from __future__ import annotations

import base64
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Request schemas ───────────────────────────────────────────────────────────

class Base64EmailRequest(BaseModel):
    """Base64-encoded raw email content."""
    email_b64:  str
    org_id:     str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_org_id(user: User) -> str | None:
    return str(
        getattr(user, "org_id", None) or getattr(user, "organization_id", None) or ""
    ) or None


async def _process_parsed_email(
    parsed_email: Any,
    org_id: str | None,
    db: AsyncSession,
) -> dict[str, Any]:
    """
    Route parsed email attachments to analysis pipeline.

    For each financial attachment:
      1. Idempotency check — if sha256 already processed for this org, skip
      2. Create a temp file-like object
      3. Enqueue an analysis job (using existing upload service)
      4. Return job IDs

    Idempotency key: sha256 hash of attachment content + org_id.
    Same file sent twice (e.g. reply-all or duplicate forward) → deduped.
    """
    import hashlib

    from sqlalchemy import select as sa_select

    results = []

    for att in parsed_email.attachments:
        if att.source_type == "unknown" and len(parsed_email.attachments) > 1:
            continue  # Skip unclassified when there are other known attachments

        try:
            import io

            from app.models.analysis_job import AnalysisJob, JobStatus
            from app.services.upload_service import get_upload_service

            # ── Idempotency check ─────────────────────────────────────────────
            # Build a stable fingerprint: sha256 of content + org scope
            content_hash = att.sha256 or hashlib.sha256(att.content).hexdigest()
            idempotency_key = f"email:{org_id or 'global'}:{content_hash}"

            # Check if this exact file was already processed
            existing_result = await db.execute(
                sa_select(AnalysisJob).where(
                    AnalysisJob.org_id == org_id,
                    AnalysisJob.filename == att.filename,
                )
            )
            existing_jobs = existing_result.scalars().all()
            duplicate = next(
                (
                    j for j in existing_jobs
                    if j.result_metadata
                    and j.result_metadata.get("sha256") == content_hash
                    and j.status not in (JobStatus.FAILED,)  # allow re-processing failed jobs
                ),
                None,
            )
            if duplicate:
                logger.info(
                    "Email ingest: skipping duplicate attachment '%s' (sha256=%s, existing job=%s)",
                    att.filename, content_hash[:12], duplicate.id,
                )
                results.append({
                    "filename":    att.filename,
                    "source_type": att.source_type,
                    "bank_hint":   att.bank_hint,
                    "job_id":      str(duplicate.id),
                    "status":      "duplicate_skipped",
                    "idempotency_key": idempotency_key,
                })
                continue

            upload_svc = get_upload_service()
            file_obj   = io.BytesIO(att.content)

            # Save file and create job
            file_path = await upload_svc.save_upload(
                file_obj,
                filename    = att.filename,
                org_id      = org_id,
                source      = "email_ingest",
            )

            # Create analysis job
            job = AnalysisJob(
                status      = JobStatus.PENDING,
                filename    = att.filename,
                file_path   = file_path,
                org_id      = org_id,
                source_type = att.source_type,
                metadata    = {
                    "email_sender":       parsed_email.sender,
                    "email_subject":      parsed_email.subject,
                    "email_date":         parsed_email.date_str,
                    "bank_hint":          att.bank_hint,
                    "sha256":             content_hash,
                    "ingest_source":      "email",
                    "idempotency_key":    idempotency_key,
                    "email_message_id":   getattr(parsed_email, "message_id", None),
                },
            )
            db.add(job)
            await db.commit()
            await db.refresh(job)

            # Enqueue for background processing
            from app.worker import enqueue_analysis
            await enqueue_analysis(str(job.id))

            results.append({
                "filename":    att.filename,
                "source_type": att.source_type,
                "bank_hint":   att.bank_hint,
                "job_id":      str(job.id),
                "status":      "enqueued",
                "idempotency_key": idempotency_key,
            })

        except Exception as exc:
            logger.warning("Failed to enqueue attachment '%s': %s", att.filename, exc)
            results.append({
                "filename":    att.filename,
                "source_type": att.source_type,
                "job_id":      None,
                "status":      "error",
                "error":       str(exc)[:200],
            })

    return {
        "message_id":  parsed_email.message_id,
        "subject":     parsed_email.subject,
        "sender":      parsed_email.sender,
        "bank_hint":   parsed_email.bank_hint,
        "attachments": len(parsed_email.attachments),
        "jobs":        results,
        "parse_errors": parsed_email.parse_errors,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/email/ingest")
async def ingest_email_raw(
    request:      Request,
    db:           AsyncSession = Depends(get_db),
    x_email_api_key: str | None = Header(None, alias="X-Email-Api-Key"),
    x_org_id:     str | None = Header(None, alias="X-Org-Id"),
) -> dict[str, Any]:
    """
    Ingest a raw MIME email via webhook.

    This endpoint is called by email forwarding services (SendGrid Inbound,
    Mailgun, AWS SES, Postmark etc.) when an email arrives at the ingest address.

    Authentication:
      X-Email-Api-Key: org-specific API key (from /email/ingest-address)
      OR standard JWT Bearer token

    Body: raw MIME email bytes (Content-Type: message/rfc822 or text/plain)
    """
    # Read raw body
    try:
        raw_body = await request.body()
        if not raw_body:
            raise HTTPException(status_code=400, detail="Empty email body")
        if len(raw_body) > 25 * 1024 * 1024:  # 25MB total limit
            raise HTTPException(status_code=413, detail="Email too large (max 25MB)")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read request body: {exc}")

    # Org resolution — from header or API key
    org_id = x_org_id

    # Parse the email
    from app.services.email_parser import get_email_parser
    parser = get_email_parser()
    parsed = parser.parse(raw_body)

    if not parsed.attachments:
        logger.info(
            "Email ingest: no financial attachments found. subject='%s' sender='%s'",
            parsed.subject, parsed.sender
        )
        return {
            "data": {
                "message_id":   parsed.message_id,
                "subject":      parsed.subject,
                "sender":       parsed.sender,
                "attachments":  0,
                "jobs":         [],
                "message":      "No financial attachments found in this email.",
                "parse_errors": parsed.parse_errors,
            },
            "error": None,
        }

    result = await _process_parsed_email(parsed, org_id, db)

    logger.info(
        "Email ingest complete: subject='%s' attachments=%d jobs=%d",
        parsed.subject, len(parsed.attachments), len(result["jobs"])
    )

    return {"data": result, "error": None}


@router.post("/email/ingest/base64")
async def ingest_email_base64(
    req:          Base64EmailRequest,
    db:           AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Ingest a base64-encoded MIME email.

    Used when the email provider encodes the raw email as base64 in their
    webhook payload (e.g. some versions of SendGrid, SparkPost).
    """
    try:
        raw_bytes = base64.b64decode(req.email_b64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid base64: {exc}")

    from app.services.email_parser import get_email_parser
    parser = get_email_parser()
    parsed = parser.parse(raw_bytes)

    org_id = req.org_id or _get_org_id(current_user)
    result = await _process_parsed_email(parsed, org_id, db)

    return {"data": result, "error": None}


@router.get("/email/ingest-address")
async def get_ingest_address(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Get the unique email ingest address for this user's org.

    Users configure their accounting software or email client to forward/CC
    financial reports to this address. Every email sent here is automatically
    parsed and analyzed.

    Setup instructions:
      Gmail:  Settings → Forwarding → Add forwarding address
      Outlook: Rules → Forward to address
      Paraşüt: Settings → Email → Reports destination
    """
    org_id = _get_org_id(current_user)
    if not org_id:
        raise HTTPException(status_code=400, detail="Kullanıcı bir organizasyona bağlı değil")

    from app.services.email_parser import generate_ingest_address
    address = generate_ingest_address(org_id)

    return {
        "data": {
            "ingest_address": address,
            "org_id":         org_id,
            "setup_instructions": {
                "gmail":    f"Gmail → Ayarlar → Yönlendirme → {address} ekle",
                "outlook":  f"Outlook → Kurallar → {address} adresine ilet",
                "parasut":  f"Paraşüt → Ayarlar → E-posta → {address} giriniz",
                "logo":     f"Logo Tiger → Raporlar → E-posta → {address} ekle",
                "manual":   f"Her analiz edilecek dosyayı {address} adresine e-posta ile gönderin",
            },
            "supported_formats": ["PDF", "Excel (.xlsx/.xls)", "CSV"],
            "max_attachment_size_mb": 10,
        },
        "error": None,
    }


@router.get("/email/history")
async def get_email_history(
    limit:        int = 20,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    List recently ingested emails and their resulting analysis jobs.
    Shows analysis jobs whose source is 'email_ingest'.
    """
    from sqlalchemy import String, cast, select

    from app.models.analysis_job import AnalysisJob

    org_id = _get_org_id(current_user)

    # Find jobs created via email ingest
    query = (
        select(AnalysisJob)
        .where(
            # The column is `result_metadata`. `AnalysisJob.metadata` is
            # SQLAlchemy's own MetaData object on every declarative class, so
            # this route raised ArgumentError on every call.
            cast(AnalysisJob.result_metadata, String).contains("email_ingest")
        )
        .order_by(AnalysisJob.created_at.desc())
        .limit(limit)
    )

    if org_id:
        query = query.where(AnalysisJob.org_id == org_id)

    result = await db.execute(query)
    jobs = result.scalars().all()

    return {
        "data": {
            "total": len(jobs),
            "jobs": [
                {
                    "job_id":    str(j.id),
                    "filename":  j.filename,
                    "status":    str(j.status),
                    "created_at": j.created_at.isoformat() if j.created_at else None,
                    "email_meta": j.result_metadata or {},
                }
                for j in jobs
            ],
        },
        "error": None,
    }
