"""
Multi-Entity & Holding Consolidation Engine (Roadmap 2.0 - Epic 4).

Consolidates financial statements across multiple group entities and subsidiaries:
1. Intercompany Revenue & COGS Elimination (Grup İçi Satış Eliminasyonu)
2. Intercompany AR / AP Elimination (Grup İçi Alacak/Borç Eliminasyonu)
3. Consolidated P&L & Balance Sheet Synthesis
4. Minority Interest (Azınlık Payları) Allocation
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.financial import cents_to_amount

logger = logging.getLogger(__name__)


@dataclass
class EntityFinancialData:
    entity_id: str
    entity_name: str
    ownership_pct: float        # e.g. 100.0 for wholly owned, 75.0 for subsidiary
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
    transaction_type: str       # "sales", "loan", "management_fee"


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
        """
        Produce consolidated group financials with intercompany eliminations.
        """
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
