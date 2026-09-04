"""
Reports PDF API — Sprint M2

PDF rapor üretimi endpoint'leri.

POST /reports/pdf/cfo-summary       → CFO özet raporu (A4, 7 sayfa)
POST /reports/pdf/executive-brief   → Tek sayfa C-suite özet
POST /reports/pdf/compliance-cert   → SOX/GDPR sertifikasyon belgesi
GET  /reports/pdf/{report_id}/download → Oluşturulan raporu indir
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.branding import get_brand
from app.database import get_db
from app.models.user import User

router = APIRouter(tags=["reports-pdf"])
logger = logging.getLogger(__name__)


# ── Request schemas ───────────────────────────────────────────────────────────

class CFOSummaryRequest(BaseModel):
    job_id:      str
    period:      str = ""
    branding:    dict | None = None   # {"logo_url": ..., "company_color": ...}


class ExecutiveBriefRequest(BaseModel):
    job_id:       str
    max_pages:    int = 1


class ComplianceCertRequest(BaseModel):
    certification_id:  str
    include_qr:        bool = True


# ── PDF streaming helper ──────────────────────────────────────────────────────

def _pdf_response(pdf_bytes: bytes, filename: str) -> Response:
    return Response(
        content          = pdf_bytes,
        media_type       = "application/pdf",
        headers          = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length":      str(len(pdf_bytes)),
            "X-PDF-Size-KB":       str(round(len(pdf_bytes) / 1024, 1)),
        },
    )


async def _load_dashboard_for_job(job_id: str, db: AsyncSession) -> dict[str, Any]:
    """Load dashboard JSON from report table."""
    try:
        from sqlalchemy import desc, select

        from app.models.report import Report, ReportFormat

        result = await db.execute(
            select(Report).where(
                Report.job_id == job_id,
                Report.report_format == ReportFormat.JSON,
            ).order_by(desc(Report.created_at)).limit(1)
        )
        report = result.scalar_one_or_none()
        if report and report.data:
            return report.data
    except Exception as exc:
        logger.warning("Failed to load dashboard for job=%s: %s", job_id, exc)
    return {}


async def _get_company_name(user: User, db: AsyncSession) -> str:
    """Get company name from CompanyContext or Organization."""
    try:
        org_id = str(user.org_id) if user.org_id else None
        if org_id:
            from app.services.company_context import get_company_context
            ctx = await get_company_context(org_id, db)
            if ctx.company_name:
                return ctx.company_name
    except Exception:
        pass
    return ""


# ── POST /reports/pdf/cfo-summary ────────────────────────────────────────────

@router.post("/reports/pdf/cfo-summary")
async def generate_cfo_summary_pdf(
    body: CFOSummaryRequest,
    user: User = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
) -> Response:
    """
    Generate a comprehensive CFO Summary PDF (A4, ~7 pages).

    Sections:
    1. Cover — company name, period, date
    2. Executive Summary — top KPIs
    3. P&L Summary — revenue, margins, costs
    4. Cash Flow — operating/investing/financing
    5. Forecast — 6-month projection
    6. Anomalies — critical/high findings
    7. Recommendations — top 5 action items

    Returns PDF as binary stream.
    Falls back to minimal PDF if WeasyPrint unavailable.
    """
    from app.services.pdf import PDFEngine, build_cfo_summary_context

    dashboard = await _load_dashboard_for_job(body.job_id, db)
    if not dashboard:
        raise HTTPException(
            status_code=404,
            detail=f"job_id={body.job_id} için rapor verisi bulunamadı.",
        )

    company_name = await _get_company_name(user, db)

    context = build_cfo_summary_context(
        dashboard_json = dashboard,
        company_name   = company_name,
        period         = body.period,
    )

    engine    = PDFEngine()
    pdf_bytes = await engine.render("cfo_summary", context)

    date_str = datetime.now(UTC).strftime("%Y%m%d")
    filename = f"cfo_summary_{date_str}.pdf"

    logger.info(
        "PDF generated: cfo_summary job=%s size=%dKB",
        body.job_id, len(pdf_bytes) // 1024,
    )

    return _pdf_response(pdf_bytes, filename)


# ── POST /reports/pdf/executive-brief ────────────────────────────────────────

@router.post("/reports/pdf/executive-brief")
async def generate_executive_brief_pdf(
    body: ExecutiveBriefRequest,
    user: User = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
) -> Response:
    """
    Generate a 1-page C-suite executive brief.

    Compact format: top 3 KPIs, top 3 alerts, top 3 recommendations.
    Ideal for board meetings and quick stakeholder reviews.
    """
    from app.services.pdf import PDFEngine, build_cfo_summary_context

    dashboard = await _load_dashboard_for_job(body.job_id, db)
    if not dashboard:
        raise HTTPException(
            status_code=404,
            detail=f"job_id={body.job_id} için rapor verisi bulunamadı.",
        )

    company_name = await _get_company_name(user, db)

    context = build_cfo_summary_context(
        dashboard_json = dashboard,
        company_name   = company_name,
    )

    engine    = PDFEngine()
    pdf_bytes = await engine.render("executive_brief", context)

    date_str = datetime.now(UTC).strftime("%Y%m%d")
    filename = f"executive_brief_{date_str}.pdf"

    logger.info(
        "PDF generated: executive_brief job=%s size=%dKB",
        body.job_id, len(pdf_bytes) // 1024,
    )

    return _pdf_response(pdf_bytes, filename)


# ── POST /reports/pdf/compliance-cert ────────────────────────────────────────

@router.post("/reports/pdf/compliance-cert")
async def generate_compliance_cert_pdf(
    body: ComplianceCertRequest,
    user: User = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db),
) -> Response:
    """
    Generate a compliance certification PDF (SOX 302 / GDPR DPA).

    Includes:
    - Certification details (name, role, period)
    - Signed statements
    - SHA-256 signature hash
    - QR code for verification (if include_qr=True)
    """
    from app.services.pdf.pdf_engine import PDFEngine

    # Load certification from DB
    try:
        from app.models.compliance_extended import ComplianceCertification

        cert = await db.get(ComplianceCertification, body.certification_id)
        # Scope to the caller's org — the raw SELECT looked up the id alone, so
        # any certification could be rendered by anyone who knew its id.
        if cert is not None and str(cert.org_id) != str(getattr(user, "org_id", "")):
            cert = None
    except Exception:
        logger.exception("certification lookup failed id=%s", body.certification_id)
        cert = None

    if not cert:
        raise HTTPException(
            status_code=404,
            detail=f"Sertifikasyon bulunamadı: {body.certification_id}",
        )

    company_name = await _get_company_name(user, db)

    # Build simple compliance cert HTML
    cert_html = _build_compliance_cert_html(
        company_name   = company_name,
        framework      = cert.framework or "sox_302",
        period         = cert.period or "",
        certifier_name = cert.certifier_name or "",
        certifier_role = cert.certifier_role or "",
        signature_hash = cert.signature_hash or "",
        certified_at   = (
            cert.certified_at.strftime("%d.%m.%Y %H:%M UTC") if cert.certified_at else ""
        ),
        cert_id        = body.certification_id,
    )

    engine    = PDFEngine()
    pdf_bytes = await engine._html_to_pdf.__func__(engine, cert_html)  # type: ignore[attr-defined]

    filename = f"compliance_cert_{body.certification_id[:8]}.pdf"
    return _pdf_response(pdf_bytes, filename)


def _build_compliance_cert_html(
    company_name:   str,
    framework:      str,
    period:         str,
    certifier_name: str,
    certifier_role: str,
    signature_hash: str,
    certified_at:   str,
    cert_id:        str,
) -> str:
    framework_label = {
        "sox_302": "SOX Section 302 — CEO/CFO Sertifikasyonu",
        "sox_404": "SOX Section 404 — İç Kontrol Değerlendirmesi",
        "gdpr_dpa": "GDPR — Veri İşleme Sözleşmesi",
    }.get(framework, framework.upper())

    brand = get_brand()
    brand_name = brand.name
    brand_legal = brand.legal_name

    return f"""
<!DOCTYPE html><html lang="tr"><head><meta charset="UTF-8">
<style>
  body {{ font-family: Arial; margin: 60px; color: #1a1a2e; }}
  .header {{ text-align: center; border-bottom: 3px solid #2563eb; padding-bottom: 20px; }}
  .header h1 {{ font-size: 22px; color: #2563eb; }}
  .body {{ margin: 30px 0; }}
  .field {{ margin: 12px 0; }}
  .field .label {{ font-size: 10px; color: #666; text-transform: uppercase; }}
  .field .value {{ font-size: 14px; font-weight: bold; }}
  .hash {{ font-family: monospace; font-size: 10px; color: #555; word-break: break-all;
           background: #f4f4f5; padding: 8px; border-radius: 4px; margin-top: 20px; }}
  .seal {{ text-align: center; margin-top: 40px; }}
  .seal .circle {{ display: inline-block; width: 80px; height: 80px; border: 4px solid #2563eb;
                   border-radius: 50%; line-height: 72px; font-size: 12px; color: #2563eb; font-weight: bold; }}
  .footer {{ font-size: 9px; color: #aaa; margin-top: 40px; text-align: center; }}
  @page {{ size: A4; margin: 2cm; }}
</style>
</head>
<body>
<div class="header">
  <div style="font-size:36px;">🔏</div>
  <h1>{framework_label}</h1>
  <div>{company_name}</div>
</div>

<div class="body">
  <div class="field"><div class="label">Dönem</div><div class="value">{period}</div></div>
  <div class="field"><div class="label">Sertifikayı İmzalayan</div><div class="value">{certifier_name}</div></div>
  <div class="field"><div class="label">Unvan</div><div class="value">{certifier_role}</div></div>
  <div class="field"><div class="label">Sertifika Tarihi</div><div class="value">{certified_at}</div></div>
  <div class="field"><div class="label">Sertifika ID</div><div class="value">{cert_id}</div></div>

  <div class="hash">
    SHA-256 İmza: {signature_hash}
  </div>
</div>

<div class="seal">
  <div class="circle">ONAY</div>
  <div style="font-size:10px;color:#555;margin-top:8px;">{brand_legal} tarafından doğrulandı</div>
</div>

<div class="footer">
  Bu belge {brand_name} tarafından otomatik olarak üretilmiştir. &nbsp;|&nbsp; {certified_at}
</div>
</body></html>"""
