"""
Tests for Master Roadmap Phases 1, 2, 3, 4.

Verifies:
1. Open Banking Reconciliation Engine (Phase 1).
2. Monte Carlo Financial Stress Testing & VaR (Phase 2).
3. Tekdüzen Hesap Planı (THP) Yevmiye & GİB e-Defter Engine (Phase 3).
4. Immutable Cryptographic SHA-256 Audit Trail (Phase 4).
"""
from __future__ import annotations

from app.services.audit_trail import ImmutableAuditTrail
from app.services.gib_edefter import EDefterGenerator
from app.services.monte_carlo import MonteCarloEngine
from app.services.open_banking_reconciliation import BankReconciliationEngine
from app.services.thp_classifier import THPClassifier

# ── Phase 1: Open Banking Reconciliation ──────────────────────────────────────

def test_open_banking_reconciliation_exact_and_fuzzy():
    transactions = [
        {"id": "tx-1", "amount_cents": 500000, "description": "GIB20240001 ACME Odemesi", "type": "expense"},
        {"id": "tx-2", "amount_cents": 1200000, "description": "Beta Holding Tahsilat", "type": "income"},
        {"id": "tx-3", "amount_cents": 50000, "description": "Bilinmeyen Kahve Harcamasi", "type": "expense"},
    ]
    invoices = [
        {"invoice_id": "inv-1", "invoice_number": "GIB20240001", "gross_amount": 5000.0, "amount_cents": 500000, "counterparty": "ACME"},
        {"invoice_id": "inv-2", "invoice_number": "GIB20240002", "gross_amount": 12000.0, "amount_cents": 1200000, "counterparty": "Beta Holding"},
    ]

    summary = BankReconciliationEngine.reconcile(transactions, invoices)
    assert summary.total_transactions == 3
    assert summary.matched_count == 2
    assert summary.unmatched_count == 1
    assert summary.reconciliation_rate_pct == 66.67
    assert summary.matched_amount_cents == 1700000


# ── Phase 2: Monte Carlo Simulation ───────────────────────────────────────────

def test_monte_carlo_simulation_runs_10000_iterations():
    res = MonteCarloEngine.simulate(
        initial_cash_cents=10000000,      # 100,000 TL
        base_monthly_in_cents=2000000,    # 20,000 TL / month
        base_monthly_out_cents=1500000,   # 15,000 TL / month
        volatility_pct=15.0,
        fx_shock_pct=10.0,
        iterations=1000,
        random_seed=42,
    )

    assert res.iterations == 1000
    assert len(res.monthly_series) == 12
    assert res.default_probability_pct >= 0.0
    assert res.var_95_cents >= 0
    assert res.expected_ending_cash_cents > 0
    assert "Monte Carlo" in res.narrative


# ── Phase 3: THP Yevmiye & e-Defter XML ────────────────────────────────────────

def test_thp_classifier_and_edefter_xml():
    tx_income = {
        "id": "tx-101",
        "amount_cents": 120000,  # 1,200 TL (%20 KDV dahil)
        "description": "Danışmanlık Fatura Tahsilatı",
        "type": "income",
        "category": "services",
        "transaction_date": "2024-03-01",
    }
    entry = THPClassifier.classify_transaction(tx_income)
    assert entry.is_balanced
    assert entry.total_debit_cents == entry.total_credit_cents == 120000
    assert any(line.account_code.startswith("102") for line in entry.lines)
    assert any(line.account_code.startswith("600") for line in entry.lines)
    assert any(line.account_code.startswith("391") for line in entry.lines)

    # e-Defter XML generation
    edefter_pkg = EDefterGenerator.generate_journal_xml(
        entries=[entry],
        period="2024-03",
        vkn="1234567890",
        company_title="Test CFO A.S.",
    )
    assert edefter_pkg.is_valid
    assert "<edefter:journal" in edefter_pkg.journal_xml
    assert edefter_pkg.sha256_hash != ""


# ── Phase 4: Cryptographic Immutable Audit Trail ──────────────────────────────

def test_immutable_audit_trail_integrity():
    trail = ImmutableAuditTrail()

    b1 = trail.record_event("org-1", "user:cfo", "UPLOAD_STATEMENT", {"filename": "bank.pdf"})
    b2 = trail.record_event("org-1", "agent:pnl", "CALCULATE_PNL", {"net_income": 50000})
    b3 = trail.record_event("org-1", "user:smmm", "APPROVE_JOURNAL", {"entry_id": "yevmiye-1"})

    assert b1.sequence_id == 1
    assert b2.sequence_id == 2
    assert b3.sequence_id == 3
    assert b2.previous_hash == b1.current_hash
    assert b3.previous_hash == b2.current_hash

    assert trail.verify_integrity() is True

    # Tampering test: modify b2 payload hash
    b2.payload_hash = "tampered_hash_00000"
    assert trail.verify_integrity() is False
