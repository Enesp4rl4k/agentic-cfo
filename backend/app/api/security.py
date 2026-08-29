"""
SOC2 Audit Trail Raporu + IP Whitelist API — SEC-4 + SEC-5

SEC-4 Endpoint'ler:
  GET /security/audit-report         → Audit log özeti (zaman aralığı, kullanıcı bazlı)
  GET /security/audit-export         → CSV export (SOC2 kanıtı için)
  GET /security/audit-events         → Filtrelenmiş audit log listesi

SEC-5 Endpoint'ler:
  GET  /security/ip-whitelist        → Org'un IP whitelist'ini oku
  PUT  /security/ip-whitelist        → IP whitelist'i güncelle
  POST /security/ip-whitelist/test   → Bir IP'nin whitelist'te olup olmadığını test et
"""
from __future__ import annotations

import csv
import io
import ipaddress
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


# ── SEC-4: Audit Trail ────────────────────────────────────────────────────────

@router.get("/security/audit-events")
async def list_audit_events(
    limit:      int = Query(50, le=500),
    offset:     int = 0,
    user_email: str | None = None,
    action:     str | None = None,
    from_date:  str | None = None,
    to_date:    str | None = None,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    SOC2 CC7.2: Audit log listesi.
    Admin/Owner rolü gerektirir.
    """
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Sadece admin ve owner erişebilir")


    from app.models.audit_log import AuditLog

    query = select(AuditLog).order_by(AuditLog.created_at.desc())

    if user_email:
        query = query.where(AuditLog.user_email == user_email)
    if action:
        query = query.where(AuditLog.action.contains(action))
    if from_date:
        try:
            dt = datetime.fromisoformat(from_date).replace(tzinfo=UTC)
            query = query.where(AuditLog.created_at >= dt)
        except ValueError:
            pass
    if to_date:
        try:
            dt = datetime.fromisoformat(to_date).replace(tzinfo=UTC)
            query = query.where(AuditLog.created_at <= dt)
        except ValueError:
            pass

    total_q = select(func.count()).select_from(query.subquery())
    total   = (await db.execute(total_q)).scalar_one()
    result  = await db.execute(query.limit(limit).offset(offset))
    events  = result.scalars().all()

    return {
        "data": {
            "total":  total,
            "limit":  limit,
            "offset": offset,
            "events": [
                {
                    "id":              str(e.id),
                    "action":          e.action,
                    "user_email":      e.user_email,
                    "user_role":       e.user_role,
                    "resource":        e.resource,
                    "response_status": e.response_status,
                    "ip_address":      e.ip_address,
                    "duration_ms":     e.duration_ms,
                    "created_at":      e.created_at.isoformat() if e.created_at else None,
                }
                for e in events
            ],
        },
        "error": None,
    }


@router.get("/security/audit-export")
async def export_audit_csv(
    days:         int   = Query(30, le=365, description="Son kaç günü export et"),
    current_user: User  = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    SOC2 kanıtı için audit log CSV export.
    """
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Sadece admin ve owner erişebilir")

    from app.models.audit_log import AuditLog

    cutoff = datetime.now(UTC) - timedelta(days=days)
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.created_at >= cutoff)
        .order_by(AuditLog.created_at.desc())
        .limit(10000)
    )
    events = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "timestamp", "action", "user_email", "user_role",
        "resource", "response_status", "ip_address", "duration_ms", "reason",
    ])
    for e in events:
        writer.writerow([
            str(e.id),
            e.created_at.isoformat() if e.created_at else "",
            e.action or "",
            e.user_email or "",
            e.user_role or "",
            e.resource or "",
            e.response_status or "",
            e.ip_address or "",
            e.duration_ms or "",
            e.reason or "",
        ])

    csv_bytes = output.getvalue().encode("utf-8-sig")  # BOM for Excel
    filename  = f"audit-log-{days}d-{datetime.now().strftime('%Y%m%d')}.csv"

    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length":      str(len(csv_bytes)),
        },
    )


@router.get("/security/audit-report")
async def audit_summary_report(
    days:         int  = Query(7, le=90),
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    SOC2 güvenlik özet raporu.
    Son N günün aktivite özeti.
    """
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Sadece admin ve owner erişebilir")

    from app.models.audit_log import AuditLog

    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Total requests
    total_q  = select(func.count()).where(AuditLog.created_at >= cutoff)
    total    = (await db.execute(total_q)).scalar_one()

    # Unique users
    users_q  = select(func.count(AuditLog.user_email.distinct())).where(
        and_(AuditLog.created_at >= cutoff, AuditLog.user_email.isnot(None))
    )
    users    = (await db.execute(users_q)).scalar_one()

    # Failed requests (4xx/5xx)
    failed_q = select(func.count()).where(
        and_(AuditLog.created_at >= cutoff, AuditLog.response_status >= 400)
    )
    failed   = (await db.execute(failed_q)).scalar_one()

    return {
        "data": {
            "period_days":    days,
            "generated_at":   datetime.now(UTC).isoformat(),
            "total_requests": total,
            "unique_users":   users,
            "failed_requests": failed,
            "error_rate_pct": round(failed / max(1, total) * 100, 2),
            "soc2_controls": {
                "CC6.1_access_controls":     "Audit log aktif",
                "CC7.2_security_monitoring": f"Son {days} gün izleniyor",
                "CC9.1_change_management":   "Tüm POST/PUT/DELETE loglanıyor",
            },
        },
        "error": None,
    }


# ── SEC-5: IP Whitelist ───────────────────────────────────────────────────────

class IPWhitelistUpdate(BaseModel):
    cidrs:   list[str]  # ["10.0.0.0/8", "203.0.113.42/32"]
    enabled: bool = True


def _validate_cidrs(cidrs: list[str]) -> list[str]:
    """Validate and normalize CIDR notations."""
    valid = []
    for cidr in cidrs:
        cidr = cidr.strip()
        if not cidr:
            continue
        try:
            network = ipaddress.ip_network(cidr, strict=False)
            valid.append(str(network))
        except ValueError:
            # Single IP without prefix?
            try:
                addr = ipaddress.ip_address(cidr)
                valid.append(str(ipaddress.ip_network(f"{addr}/32")))
            except ValueError:
                raise HTTPException(400, f"Geçersiz CIDR formatı: '{cidr}'")
    return valid


def check_ip_in_whitelist(ip: str, whitelist: str) -> bool:
    """Check if an IP is in a comma-separated CIDR whitelist."""
    if not whitelist:
        return True  # No whitelist = allow all
    try:
        client_ip = ipaddress.ip_address(ip)
        for cidr in whitelist.split(","):
            cidr = cidr.strip()
            if not cidr:
                continue
            if client_ip in ipaddress.ip_network(cidr, strict=False):
                return True
        return False
    except Exception:
        return True  # On parse error, be permissive


@router.get("/security/ip-whitelist")
async def get_ip_whitelist(
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the org's current IP whitelist configuration."""
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Sadece admin ve owner erişebilir")

    org_id = getattr(current_user, "org_id", None)
    if not org_id:
        return {"data": {"enabled": False, "cidrs": []}, "error": None}

    from app.models.organization import Organization
    result = await db.execute(select(Organization).where(Organization.id == str(org_id)))
    org    = result.scalar_one_or_none()

    if not org:
        return {"data": {"enabled": False, "cidrs": []}, "error": None}

    whitelist = getattr(org, "ip_whitelist", "") or ""
    enabled   = getattr(org, "ip_whitelist_enabled", False) or False

    return {
        "data": {
            "enabled": bool(enabled),
            "cidrs":   [c.strip() for c in whitelist.split(",") if c.strip()],
        },
        "error": None,
    }


@router.put("/security/ip-whitelist")
async def update_ip_whitelist(
    req:          IPWhitelistUpdate,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Update IP whitelist for the org.
    WARNING: Wrong config can lock out all users. Always include your own IP.
    """
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Sadece admin ve owner erişebilir")

    org_id = getattr(current_user, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=400, detail="Org bağlamı gerekli")

    valid_cidrs = _validate_cidrs(req.cidrs)

    from app.models.organization import Organization
    result = await db.execute(select(Organization).where(Organization.id == str(org_id)))
    org    = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organizasyon bulunamadı")

    org.ip_whitelist         = ",".join(valid_cidrs)  # type: ignore[attr-defined]
    org.ip_whitelist_enabled = req.enabled             # type: ignore[attr-defined]
    await db.commit()

    logger.info(
        "IP whitelist updated: org=%s cidrs=%s enabled=%s user=%s",
        org_id, valid_cidrs, req.enabled, current_user.id
    )

    return {
        "data": {
            "enabled": req.enabled,
            "cidrs":   valid_cidrs,
            "message": "IP whitelist güncellendi",
        },
        "error": None,
    }


@router.post("/security/ip-whitelist/test")
async def test_ip_whitelist(
    ip:           str,
    current_user: User = Depends(get_current_user),
    db:           AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Test whether an IP address is allowed by the current whitelist."""
    org_id = getattr(current_user, "org_id", None)
    if not org_id:
        return {"data": {"allowed": True, "reason": "Whitelist devre dışı (org yok)"}, "error": None}

    from app.models.organization import Organization
    result = await db.execute(select(Organization).where(Organization.id == str(org_id)))
    org    = result.scalar_one_or_none()

    if not org or not getattr(org, "ip_whitelist_enabled", False):
        return {"data": {"allowed": True, "reason": "Whitelist devre dışı"}, "error": None}

    whitelist = getattr(org, "ip_whitelist", "") or ""
    allowed   = check_ip_in_whitelist(ip, whitelist)

    return {
        "data": {
            "ip":        ip,
            "allowed":   allowed,
            "whitelist": whitelist,
            "reason":    "Whitelist'te mevcut" if allowed else "Whitelist'te yok — erişim reddedilecek",
        },
        "error": None,
    }
