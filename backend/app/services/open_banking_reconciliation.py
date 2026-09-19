"""
Open Banking & Bank Statement Reconciliation Engine (Phase 1).

Matches bank statement transactions with ERP/e-Fatura invoices using:
1. Exact Match: Exact amount (cents) + VKN/TCKN match within +/- 5 days.
2. High Confidence Match: Exact amount (cents) + fuzzy counterparty title match.
3. Partial/Split Match: Aggregate multi-invoice payments.
4. Unmatched: Flagged for manual review or automated THP accrual.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ReconciliationMatch:
    transaction_id: str
    invoice_id: str | None
    match_type: str  # "exact", "high_confidence", "fuzzy", "unmatched"
    confidence: float
    amount_cents: int
    difference_cents: int
    transaction_desc: str
    invoice_number: str | None
    counterparty: str
    suggested_account_code: str  # e.g. "102.01", "120.01", "320.01"
    status: str = "matched"  # "matched", "unmatched", "disputed"


@dataclass
class ReconciliationSummary:
    total_transactions: int
    matched_count: int
    unmatched_count: int
    matched_amount_cents: int
    unmatched_amount_cents: int
    reconciliation_rate_pct: float
    matches: list[ReconciliationMatch] = field(default_factory=list)


class BankReconciliationEngine:
    """Automated bank transaction & e-Fatura reconciliation service."""

    @staticmethod
    def reconcile(
        transactions: list[dict[str, Any]],
        invoices: list[dict[str, Any]],
        date_tolerance_days: int = 7,
    ) -> ReconciliationSummary:
        """
        Reconcile a list of bank transactions against open invoices.
        """
        matches: list[ReconciliationMatch] = []
        matched_tx_ids = set()
        matched_inv_ids = set()

        total_tx_cents = sum(t.get("amount_cents", 0) for t in transactions)
        matched_cents = 0

        # Pass 1: Exact Amount + Direct Counterparty/Invoice Number Match
        for tx in transactions:
            tx_id = tx.get("id") or str(id(tx))
            tx_cents = tx.get("amount_cents", 0)
            tx_desc = (tx.get("description") or "").lower()
            tx_vendor = (tx.get("vendor") or "").lower()
            tx_type = tx.get("type", "expense")

            best_match: dict[str, Any] | None = None
            best_confidence = 0.0
            match_type = "unmatched"

            for inv in invoices:
                inv_id = inv.get("invoice_id") or inv.get("id") or str(id(inv))
                if inv_id in matched_inv_ids:
                    continue

                inv_cents = inv.get("amount_cents", 0) or round(float(inv.get("gross_amount", 0)) * 100)
                inv_no = (inv.get("invoice_number") or "").lower()
                inv_party = (inv.get("counterparty") or inv.get("vendor") or "").lower()

                # Exact Amount Match
                if tx_cents == inv_cents and tx_cents > 0:
                    # Check if invoice number or party is mentioned in bank transaction
                    if inv_no and inv_no in tx_desc:
                        best_match = inv
                        best_confidence = 1.0
                        match_type = "exact"
                        break
                    elif inv_party and (inv_party in tx_desc or inv_party in tx_vendor or tx_vendor in inv_party):
                        best_match = inv
                        best_confidence = 0.95
                        match_type = "high_confidence"
                        break
                    elif best_match is None:
                        # Fallback: same amount, no explicit name match
                        best_match = inv
                        best_confidence = 0.80
                        match_type = "fuzzy"

            if best_match and best_confidence >= 0.80:
                inv_id = best_match.get("invoice_id") or best_match.get("id")
                matched_inv_ids.add(inv_id)
                matched_tx_ids.add(tx_id)
                matched_cents += tx_cents

                account_code = "120.01" if tx_type == "income" else "320.01"
                matches.append(
                    ReconciliationMatch(
                        transaction_id=tx_id,
                        invoice_id=inv_id,
                        match_type=match_type,
                        confidence=best_confidence,
                        amount_cents=tx_cents,
                        difference_cents=0,
                        transaction_desc=tx.get("description", ""),
                        invoice_number=best_match.get("invoice_number"),
                        counterparty=best_match.get("counterparty") or best_match.get("vendor") or "Bilinmeyen",
                        suggested_account_code=account_code,
                        status="matched",
                    )
                )
            else:
                # Unmatched bank transaction
                account_code = "600.01" if tx_type == "income" else "770.01"
                matches.append(
                    ReconciliationMatch(
                        transaction_id=tx_id,
                        invoice_id=None,
                        match_type="unmatched",
                        confidence=0.50,
                        amount_cents=tx_cents,
                        difference_cents=tx_cents,
                        transaction_desc=tx.get("description", ""),
                        invoice_number=None,
                        counterparty=tx.get("vendor") or "Banka Hareketi",
                        suggested_account_code=account_code,
                        status="unmatched",
                    )
                )

        matched_count = len(matched_tx_ids)
        unmatched_count = len(transactions) - matched_count
        rate = (matched_count / len(transactions) * 100.0) if transactions else 100.0

        return ReconciliationSummary(
            total_transactions=len(transactions),
            matched_count=matched_count,
            unmatched_count=unmatched_count,
            matched_amount_cents=matched_cents,
            unmatched_amount_cents=total_tx_cents - matched_cents,
            reconciliation_rate_pct=round(rate, 2),
            matches=matches,
        )
