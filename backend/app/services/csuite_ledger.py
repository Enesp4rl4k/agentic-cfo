"""C-Suite Ledger Intelligence — CHRO, COO, CTO metrics derived directly from the company ledger.

Plan v10 §4 (O5) & Plan v11 Faz 4 (E4):
Ayrı veri hatları veya ek CSV yüklemeleri zorunlu kılınmadan, tek doğruluk kaynağı olan
defterden (canonical_transactions ve open_items) türetilen yönetici içgörüleri:
- CHRO: Personel / Ciro oranı ve trendi.
- COO: Tedarikçi yoğunlaşma riski (Pareto / 80-20 analizi).
- CTO: Yazılım ve Bulut altyapı abonelik trendleri.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.turkish import fold
from app.models.canonical_transaction import CanonicalTransaction
from app.services.cash_radar import _fmt
from app.services.ledger import ACTIVE

_PERSONNEL_CATEGORIES = {"payroll", "salary", "personel", "sgk", "maas", "ik"}
_PERSONNEL_KEYWORDS = ["maas", "bordro", "ucret", "sgk prim", "personel", "avans"]

_TECH_CATEGORIES = {"saas", "software", "hosting", "cloud", "yazilim", "bilisim", "it"}
_TECH_VENDORS = [
    "aws",
    "amazon web services",
    "google cloud",
    "gcp",
    "azure",
    "microsoft",
    "digitalocean",
    "github",
    "slack",
    "jira",
    "atlassian",
    "figma",
    "notion",
    "openai",
    "cloudflare",
    "hetzner",
    "vercel",
    "datadog",
    "zoom",
    "sentry",
    "stripe",
    "hubspot",
    "adobe",
    "jetbrains",
    "heroku",
    "mongodb",
]


@dataclass(frozen=True)
class CHROMetrics:
    org_id: str
    revenue_cents: int
    payroll_cents: int
    payroll_ratio_pct: float | None
    monthly_trend: list[dict[str, Any]]
    trend_direction: str  # "increasing" | "stable" | "decreasing"
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class COOMetrics:
    org_id: str
    total_expense_cents: int
    top_suppliers: list[dict[str, Any]]
    top1_share_pct: float
    top3_share_pct: float
    top5_share_pct: float
    concentration_risk: str  # "LOW" | "MEDIUM" | "HIGH"
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CTOMetrics:
    org_id: str
    total_tech_spend_cents: int
    tech_share_pct: float
    monthly_trend: list[dict[str, Any]]
    recurring_tech_vendors: list[dict[str, Any]]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def compute_chro_metrics(
    db: AsyncSession,
    org_id: str,
    *,
    months: int = 6,
    anchor_date: date | None = None,
) -> CHROMetrics:
    """Derive CHRO workforce compensation & revenue ratio directly from ledger transactions."""
    anchor_dt = (
        datetime.combine(anchor_date, datetime.max.time(), tzinfo=UTC)
        if anchor_date
        else datetime.now(UTC)
    )
    cutoff = anchor_dt - timedelta(days=months * 31)

    result = await db.execute(
        select(CanonicalTransaction)
        .where(
            CanonicalTransaction.org_id == org_id,
            CanonicalTransaction.ledger_status == ACTIVE,
            CanonicalTransaction.transaction_date >= cutoff,
            CanonicalTransaction.transaction_date <= anchor_dt,
        )
        .order_by(CanonicalTransaction.transaction_date.asc())
    )
    rows = result.scalars().all()

    total_revenue = 0
    total_payroll = 0
    monthly_rev: dict[str, int] = defaultdict(int)
    monthly_pay: dict[str, int] = defaultdict(int)

    for r in rows:
        m_key = r.transaction_date.strftime("%Y-%m")
        if r.direction == "income":
            total_revenue += r.amount_cents
            monthly_rev[m_key] += r.amount_cents
        elif r.direction == "expense":
            is_personnel = False
            if r.category and r.category.lower() in _PERSONNEL_CATEGORIES:
                is_personnel = True
            else:
                desc = fold(r.description or "")
                cp = fold(r.counterparty or "")
                if any(k in desc or k in cp for k in _PERSONNEL_KEYWORDS):
                    is_personnel = True

            if is_personnel:
                total_payroll += r.amount_cents
                monthly_pay[m_key] += r.amount_cents

    ratio_pct = (total_payroll / total_revenue * 100.0) if total_revenue > 0 else None

    # Compute monthly trend
    all_months = sorted(set(monthly_rev.keys()) | set(monthly_pay.keys()))
    monthly_trend: list[dict[str, Any]] = []
    for m in all_months:
        m_rev = monthly_rev[m]
        m_pay = monthly_pay[m]
        m_ratio = (m_pay / m_rev * 100.0) if m_rev > 0 else None
        monthly_trend.append(
            {
                "month": m,
                "revenue_cents": m_rev,
                "payroll_cents": m_pay,
                "ratio_pct": round(m_ratio, 2) if m_ratio is not None else None,
            }
        )

    # Direction check
    if len(monthly_trend) >= 2:
        last = monthly_trend[-1]["ratio_pct"] or 0
        prev = monthly_trend[-2]["ratio_pct"] or 0
        if last > prev + 2.0:
            direction = "increasing"
        elif last < prev - 2.0:
            direction = "decreasing"
        else:
            direction = "stable"
    else:
        direction = "stable"

    if ratio_pct is not None:
        summary = (
            f"Personel giderleri son {months} ayda toplam cironun %{ratio_pct:.1f}'ini oluşturmaktadır "
            f"(Toplam Bordro: {_fmt(total_payroll)}, Toplam Ciro: {_fmt(total_revenue)})."
        )
    else:
        summary = (
            f"Son {months} ayda kaydedilmiş ciro bulunmadığı için personel oranı hesaplanamadı."
        )

    return CHROMetrics(
        org_id=org_id,
        revenue_cents=total_revenue,
        payroll_cents=total_payroll,
        payroll_ratio_pct=round(ratio_pct, 2) if ratio_pct is not None else None,
        monthly_trend=monthly_trend,
        trend_direction=direction,
        summary=summary,
    )


async def compute_coo_metrics(
    db: AsyncSession,
    org_id: str,
    *,
    days: int = 90,
    anchor_date: date | None = None,
) -> COOMetrics:
    """Derive COO supplier concentration & Pareto risk directly from ledger expenses."""
    anchor_dt = (
        datetime.combine(anchor_date, datetime.max.time(), tzinfo=UTC)
        if anchor_date
        else datetime.now(UTC)
    )
    cutoff = anchor_dt - timedelta(days=days)

    result = await db.execute(
        select(CanonicalTransaction).where(
            CanonicalTransaction.org_id == org_id,
            CanonicalTransaction.ledger_status == ACTIVE,
            CanonicalTransaction.direction == "expense",
            CanonicalTransaction.transaction_date >= cutoff,
            CanonicalTransaction.transaction_date <= anchor_dt,
        )
    )
    rows = result.scalars().all()

    supplier_totals: dict[str, int] = defaultdict(int)
    total_expense = 0

    for r in rows:
        name = (r.counterparty or "").strip()
        if not name:
            # Fallback to description
            words = (r.description or "Diğer").split()
            name = " ".join(words[:2]) if words else "Diğer"
        supplier_totals[name] += r.amount_cents
        total_expense += r.amount_cents

    sorted_suppliers = sorted(supplier_totals.items(), key=lambda x: x[1], reverse=True)

    top_suppliers: list[dict[str, Any]] = []
    for name, cents in sorted_suppliers[:10]:
        share = (cents / total_expense * 100.0) if total_expense > 0 else 0.0
        top_suppliers.append(
            {
                "name": name,
                "amount_cents": cents,
                "share_pct": round(share, 2),
            }
        )

    top1_cents = sum(s[1] for s in sorted_suppliers[:1])
    top3_cents = sum(s[1] for s in sorted_suppliers[:3])
    top5_cents = sum(s[1] for s in sorted_suppliers[:5])

    top1_share = (top1_cents / total_expense * 100.0) if total_expense > 0 else 0.0
    top3_share = (top3_cents / total_expense * 100.0) if total_expense > 0 else 0.0
    top5_share = (top5_cents / total_expense * 100.0) if total_expense > 0 else 0.0

    if top1_share >= 40.0 or top3_share >= 70.0:
        risk = "HIGH"
        risk_tr = "YÜKSEK"
    elif top1_share >= 25.0 or top3_share >= 50.0:
        risk = "MEDIUM"
        risk_tr = "ORTA"
    else:
        risk = "LOW"
        risk_tr = "DÜŞÜK"

    summary = (
        f"Son {days} günlük giderlerde tedarikçi yoğunlaşma riski {risk_tr} seviyededir. "
        f"En büyük 3 tedarikçi toplam harcamaların %{top3_share:.1f}'ini oluşturmaktadır."
    )

    return COOMetrics(
        org_id=org_id,
        total_expense_cents=total_expense,
        top_suppliers=top_suppliers,
        top1_share_pct=round(top1_share, 2),
        top3_share_pct=round(top3_share, 2),
        top5_share_pct=round(top5_share, 2),
        concentration_risk=risk,
        summary=summary,
    )


async def compute_cto_metrics(
    db: AsyncSession,
    org_id: str,
    *,
    months: int = 6,
    anchor_date: date | None = None,
) -> CTOMetrics:
    """Derive CTO cloud infrastructure, software & SaaS subscription trends from ledger."""
    anchor_dt = (
        datetime.combine(anchor_date, datetime.max.time(), tzinfo=UTC)
        if anchor_date
        else datetime.now(UTC)
    )
    cutoff = anchor_dt - timedelta(days=months * 31)

    result = await db.execute(
        select(CanonicalTransaction)
        .where(
            CanonicalTransaction.org_id == org_id,
            CanonicalTransaction.ledger_status == ACTIVE,
            CanonicalTransaction.direction == "expense",
            CanonicalTransaction.transaction_date >= cutoff,
            CanonicalTransaction.transaction_date <= anchor_dt,
        )
        .order_by(CanonicalTransaction.transaction_date.asc())
    )
    rows = result.scalars().all()

    total_expense = 0
    total_tech = 0
    monthly_tech: dict[str, int] = defaultdict(int)
    vendor_counts: dict[str, set[str]] = defaultdict(set)
    vendor_amounts: dict[str, int] = defaultdict(int)

    for r in rows:
        total_expense += r.amount_cents
        desc = fold(r.description or "")
        cp = fold(r.counterparty or "")

        is_tech = False
        matched_vendor: str | None = None

        if r.category and r.category.lower() in _TECH_CATEGORIES:
            is_tech = True
            matched_vendor = r.counterparty or r.description or "Tech Provider"

        for v in _TECH_VENDORS:
            if v in desc or v in cp:
                is_tech = True
                matched_vendor = v.title()
                break

        if is_tech and matched_vendor:
            total_tech += r.amount_cents
            m_key = r.transaction_date.strftime("%Y-%m")
            monthly_tech[m_key] += r.amount_cents
            vendor_counts[matched_vendor].add(m_key)
            vendor_amounts[matched_vendor] += r.amount_cents

    tech_share = (total_tech / total_expense * 100.0) if total_expense > 0 else 0.0

    monthly_trend = [
        {"month": m, "tech_spend_cents": cents} for m, cents in sorted(monthly_tech.items())
    ]

    recurring_vendors: list[dict[str, Any]] = []
    for vendor, m_set in sorted(vendor_counts.items(), key=lambda x: len(x[1]), reverse=True):
        recurring_vendors.append(
            {
                "vendor": vendor,
                "distinct_months": len(m_set),
                "total_spend_cents": vendor_amounts[vendor],
            }
        )

    summary = (
        f"Son {months} ayda yazılım ve bulut altyapı harcamaları toplam {_fmt(total_tech)} "
        f"(giderlerin %{tech_share:.1f}'i) olarak gerçekleşmiştir. {len(recurring_vendors)} adet düzenli servis tespit edildi."
    )

    return CTOMetrics(
        org_id=org_id,
        total_tech_spend_cents=total_tech,
        tech_share_pct=round(tech_share, 2),
        monthly_trend=monthly_trend,
        recurring_tech_vendors=recurring_vendors,
        summary=summary,
    )
