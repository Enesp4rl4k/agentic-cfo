"""Konsolide Grup ve İlişkili Taraf Eliminasyon Motoru (Plan v12 Faz 4).

Amaç:
Grup şirketleri veya holding yapıları altındaki birden fazla firmanın (Şirket A, Şirket B)
nakit akışlarını tek bir konsolide radarda birleştirmek; şirketler arasındaki borç, alacak
ve fon transferlerini (intercompany) netleştirerek (elimination) çift sayımı sıfırlamak.

Temel Kurallar:
1. DDIA Çift Sayım Koruması: Şirket A'nın Şirket B'den olan alacağı ve Şirket B'nin Şirket A'ya
   olan borcu konsolide görünümde aynı haftada elenir; harici gelir veya gider gibi gösterilmez.
2. Sıfır Float: Tüm paralar tamsayı kuruş (cents) cinsinden hesaplanır.
3. Kanıtlanabilirlik: Her eliminasyon hangi ilişkili taraf kaydı ve açık kalemle eşleştiğini
   açıkça listeler.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.financial import cents_to_amount
from app.models.organization import Organization
from app.services.cash_radar import HORIZON_WEEKS, CashRadar, compute_cash_radar
from app.services.related_party import load_active_parties, normalize_name, normalize_tax_id

logger = logging.getLogger(__name__)


# ── Legacy Roadmap 2.0 Epic 4: Multi-Entity P&L/Bilanço Konsolidasyonu ────────


@dataclass
class EntityFinancialData:
    entity_id: str
    entity_name: str
    ownership_pct: float  # e.g. 100.0 for wholly owned, 75.0 for subsidiary
    revenue_cents: int
    cogs_cents: int
    operating_expenses_cents: int
    net_income_cents: int
    cash_cents: int
    receivables_cents: int
    payables_cents: int


@dataclass
class IntercompanyTransaction:
    seller_entity_id: str
    buyer_entity_id: str
    amount_cents: int
    transaction_type: str  # "sales", "loan", "management_fee"


@dataclass
class ConsolidatedFinancialReport:
    reporting_period: str
    entities_count: int
    gross_combined_revenue_cents: int
    intercompany_eliminations_revenue_cents: int
    consolidated_revenue_cents: int
    consolidated_cogs_cents: int
    consolidated_gross_profit_cents: int
    consolidated_net_income_cents: int
    parent_share_net_income_cents: int
    minority_interest_cents: int
    consolidated_cash_cents: int
    executive_summary: str = ""


class ConsolidationEngine:
    """Consolidates financial statements across multiple legal entities."""

    @classmethod
    def consolidate(
        cls,
        reporting_period: str,
        entities: list[EntityFinancialData],
        intercompany_txs: list[IntercompanyTransaction] | None = None,
    ) -> ConsolidatedFinancialReport:
        """Produce consolidated group financials with intercompany eliminations."""
        txs = intercompany_txs or []

        # 1. Ham Toplamlar (Combined Totals)
        gross_rev = sum(e.revenue_cents for e in entities)
        gross_cogs = sum(e.cogs_cents for e in entities)
        gross_opex = sum(e.operating_expenses_cents for e in entities)
        gross_cash = sum(e.cash_cents for e in entities)

        # 2. Grup İçi Eliminasyonlar (Intercompany Eliminations)
        elim_sales_cents = sum(
            tx.amount_cents for tx in txs if tx.transaction_type in ["sales", "management_fee"]
        )

        cons_rev = max(0, gross_rev - elim_sales_cents)
        cons_cogs = max(0, gross_cogs - elim_sales_cents)  # Satış maliyeti de elimine edilir
        cons_gross_profit = cons_rev - cons_cogs
        cons_net_income = cons_gross_profit - gross_opex

        # 3. Azınlık Payları (Minority Interest Calculation)
        minority_net_cents = 0
        for e in entities:
            if e.ownership_pct < 100.0:
                minority_ratio = (100.0 - e.ownership_pct) / 100.0
                minority_net_cents += int(e.net_income_cents * minority_ratio)

        parent_share_cents = cons_net_income - minority_net_cents

        summary = (
            f"{reporting_period} dönemi grup konsolidasyonunda {len(entities)} şirket birleştirilmiştir. "
            f"Grup içi {cents_to_amount(elim_sales_cents):,.2f} TL tutarındaki işlemler elimine edildikten sonra "
            f"konsolide net gelir {cents_to_amount(cons_rev):,.2f} TL, konsolide net kâr "
            f"{cents_to_amount(cons_net_income):,.2f} TL (Ana Ortaklık Payı: {cents_to_amount(parent_share_cents):,.2f} TL) "
            f"olarak gerçekleşmiştir."
        )

        return ConsolidatedFinancialReport(
            reporting_period=reporting_period,
            entities_count=len(entities),
            gross_combined_revenue_cents=gross_rev,
            intercompany_eliminations_revenue_cents=elim_sales_cents,
            consolidated_revenue_cents=cons_rev,
            consolidated_cogs_cents=cons_cogs,
            consolidated_gross_profit_cents=cons_gross_profit,
            consolidated_net_income_cents=cons_net_income,
            parent_share_net_income_cents=parent_share_cents,
            minority_interest_cents=minority_net_cents,
            consolidated_cash_cents=gross_cash,
            executive_summary=summary,
        )


# ── Plan v12 Faz 4: Konsolide Grup & İlişkili Taraf Nakit Radarı ──────────────


@dataclass(frozen=True)
class IntercompanyElimination:
    item_id: str
    org_id: str
    org_name: str
    direction: str  # receivable | payable
    counterparty: str
    amount_cents: int
    due_date: str
    week: int
    eliminated_reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConsolidatedWeek:
    week: int
    start_date: str
    end_date: str
    gross_inflow_cents: int
    gross_outflow_cents: int
    eliminated_inflow_cents: int
    eliminated_outflow_cents: int
    net_inflow_cents: int
    net_outflow_cents: int
    consolidated_balance_cents: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConsolidatedCashRadar:
    group_name: str
    participating_org_ids: list[str]
    total_starting_cash_cents: int
    weeks: list[ConsolidatedWeek]
    eliminations: list[IntercompanyElimination]
    total_eliminated_cents: int
    insights: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_name": self.group_name,
            "participating_org_ids": self.participating_org_ids,
            "total_starting_cash_cents": self.total_starting_cash_cents,
            "weeks": [w.to_dict() for w in self.weeks],
            "eliminations": [e.to_dict() for e in self.eliminations],
            "total_eliminated_cents": self.total_eliminated_cents,
            "insights": self.insights,
        }


def _is_intercompany_match(
    counterparty: str | None,
    other_org_names: set[str],
    other_org_tax_ids: set[str],
    registered_related_names: set[str],
) -> tuple[bool, str]:
    """Check if a counterparty corresponds to another group entity."""
    if not counterparty:
        return False, ""
    norm = normalize_name(counterparty)
    tax_clean = normalize_tax_id(counterparty)

    # 1. Match on Tax ID
    if tax_clean and tax_clean in other_org_tax_ids:
        return True, f"Vergi Kimlik Numarası eşleşmesi ({tax_clean})"

    # 2. Match on Sister Org Name
    for o_name in other_org_names:
        if o_name and (o_name == norm or o_name in norm or norm in o_name):
            return True, f"Grup şirketi unvan eşleşmesi ({counterparty} ~ {o_name})"

    # 3. Match on registered related party registry
    for r_name in registered_related_names:
        if r_name and (r_name == norm or r_name in norm or norm in r_name):
            return True, f"İlişkili taraf sicil eşleşmesi ({counterparty})"

    return False, ""


async def compute_consolidated_cash_radar(
    db: AsyncSession,
    org_ids: list[str],
    *,
    group_name: str = "Konsolide Grup",
    anchor_date: date | None = None,
) -> ConsolidatedCashRadar:
    """Compute 13-week consolidated cash radar across multiple organizations with intercompany elimination."""
    if not org_ids:
        raise ValueError("Konsolidasyon için en az bir organizasyon ID gereklidir.")

    # 1. Load participating organizations
    org_rows = (
        (await db.execute(select(Organization).where(Organization.id.in_(org_ids)))).scalars().all()
    )
    org_map = {o.id: o for o in org_rows}

    # Gather normalized names and tax ids of the group
    other_org_names = {normalize_name(o.name) for o in org_rows if o.name}
    other_org_tax_ids: set[str] = set()

    # Load active related parties across all orgs in the group
    registered_related_names: set[str] = set()
    for oid in org_ids:
        parties = await load_active_parties(oid, db)
        for p in parties:
            if p.relationship_type in ("istirak", "ana_ortaklik", "ortak", "grup_sirketi"):
                if p.normalized_name:
                    registered_related_names.add(p.normalized_name)
                if p.tax_id:
                    other_org_tax_ids.add(normalize_tax_id(p.tax_id))

    # 2. Compute individual standalone radars for each entity
    individual_radars: dict[str, CashRadar] = {}
    for oid in org_ids:
        individual_radars[oid] = await compute_cash_radar(db, oid, anchor_date=anchor_date)

    # 3. Sum up starting cash
    total_starting_cash = sum((r.starting_cash_cents or 0) for r in individual_radars.values())

    # 4. 13-week consolidation and elimination tracking
    gross_inflows = [0] * HORIZON_WEEKS
    gross_outflows = [0] * HORIZON_WEEKS
    eliminated_inflows = [0] * HORIZON_WEEKS
    eliminated_outflows = [0] * HORIZON_WEEKS
    eliminations: list[IntercompanyElimination] = []

    # Iterate through all weeks of all entities
    for oid, radar in individual_radars.items():
        org_name = org_map.get(oid).name if oid in org_map else oid
        for w_idx, week in enumerate(radar.weeks):
            # Tally gross
            gross_inflows[w_idx] += week.inflow_cents
            gross_outflows[w_idx] += week.outflow_cents

            # Check individual receivables for intercompany match
            for rec in week.receivables:
                is_match, reason = _is_intercompany_match(
                    rec.get("counterparty"),
                    other_org_names,
                    other_org_tax_ids,
                    registered_related_names,
                )
                if is_match:
                    amt = rec.get("amount_cents", 0)
                    eliminated_inflows[w_idx] += amt
                    eliminations.append(
                        IntercompanyElimination(
                            item_id=rec.get("id", ""),
                            org_id=oid,
                            org_name=org_name,
                            direction="receivable",
                            counterparty=rec.get("counterparty") or "Grup Şirketi",
                            amount_cents=amt,
                            due_date=rec.get("expected_date") or "",
                            week=w_idx + 1,
                            eliminated_reason=f"Grup içi alacak eliminasyonu: {reason}",
                        )
                    )

            # Check individual payables for intercompany match
            for pay in week.payables:
                is_match, reason = _is_intercompany_match(
                    pay.get("counterparty"),
                    other_org_names,
                    other_org_tax_ids,
                    registered_related_names,
                )
                if is_match:
                    amt = pay.get("amount_cents", 0)
                    eliminated_outflows[w_idx] += amt
                    eliminations.append(
                        IntercompanyElimination(
                            item_id=pay.get("id", ""),
                            org_id=oid,
                            org_name=org_name,
                            direction="payable",
                            counterparty=pay.get("counterparty") or "Grup Şirketi",
                            amount_cents=amt,
                            due_date=pay.get("expected_date") or "",
                            week=w_idx + 1,
                            eliminated_reason=f"Grup içi borç eliminasyonu: {reason}",
                        )
                    )

    # 5. Build consolidated weeks
    sample_weeks = next(iter(individual_radars.values())).weeks if individual_radars else []
    consolidated_weeks: list[ConsolidatedWeek] = []
    running_balance = total_starting_cash
    total_eliminated_cents = sum(e.amount_cents for e in eliminations)

    for i in range(HORIZON_WEEKS):
        net_in = max(0, gross_inflows[i] - eliminated_inflows[i])
        net_out = max(0, gross_outflows[i] - eliminated_outflows[i])
        running_balance += net_in - net_out

        start_str = sample_weeks[i].start_date if i < len(sample_weeks) else ""
        end_str = sample_weeks[i].end_date if i < len(sample_weeks) else ""

        consolidated_weeks.append(
            ConsolidatedWeek(
                week=i + 1,
                start_date=start_str,
                end_date=end_str,
                gross_inflow_cents=gross_inflows[i],
                gross_outflow_cents=gross_outflows[i],
                eliminated_inflow_cents=eliminated_inflows[i],
                eliminated_outflow_cents=eliminated_outflows[i],
                net_inflow_cents=net_in,
                net_outflow_cents=net_out,
                consolidated_balance_cents=running_balance,
            )
        )

    # 6. Generate Insights
    insights: list[str] = [
        f"Grup genelinde {len(org_ids)} şirket konsolide edildi. Toplam başlangıç nakdi: ₺{total_starting_cash / 100:,.2f}."
    ]
    if eliminations:
        insights.append(
            f"Toplam {len(eliminations)} adet grup içi hareket tespit edildi ve ₺{total_eliminated_cents / 100:,.2f} tutarında çift sayım elendi."
        )
    else:
        insights.append(
            "Şirketler arasında karşılıklı açık işlem veya eliminasyon gerektiren fon hareketi bulunamadı."
        )

    return ConsolidatedCashRadar(
        group_name=group_name,
        participating_org_ids=org_ids,
        total_starting_cash_cents=total_starting_cash,
        weeks=consolidated_weeks,
        eliminations=eliminations,
        total_eliminated_cents=total_eliminated_cents,
        insights=insights,
    )
