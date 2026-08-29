"""
Golden expectations for the TR fixture corpus.

Amounts are in kuruş (TRY * 100). These are hand-derived from the CSV/XML
fixtures and re-verified by the pipeline; a diff here means either a fixture
changed or a computation regressed.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

CORPUS_DIR = Path(__file__).parent

# ── technova_ocak_2024.csv — profitable, clean month ────────────────────────
OCAK = {
    "file": "technova_ocak_2024.csv",
    "transaction_count": 12,
    "pnl": {
        "revenue": 39_200_000,          # 285.000 + 65.000 + 42.000
        "cogs": 1_500_000,
        "gross_profit": 37_700_000,
        "total_opex": 27_300_000,       # salary 197.000 + rent 28.500 + util 7.000 + mkt 18.500 + tech 22.000
        "ebitda": 10_400_000,
        "tax": 3_120_000,
        "loan_payments": 0,
        "net_income": 7_280_000,
        "total_expenses": 31_920_000,
    },
    "net_margin_min": 0.15,             # ~0.1857 — healthy
    "reconciliation_action": "proceed",
    "expect_halted": False,
    "must_flag_anomaly_types": set(),   # nothing critical in a clean month
    "correct": True,                    # a run that completes with these numbers is "correct"
}

# ── technova_subat_2024_zarar.csv — loss month + duplicate payment ──────────
SUBAT = {
    "file": "technova_subat_2024_zarar.csv",
    "transaction_count": 6,
    "pnl": {
        "revenue": 800_000,
        "cogs": 0,
        "gross_profit": 800_000,
        "total_opex": 23_900_000,       # salary 120.000 + rent 35.000 + mkt 60.000 + other 24.000
        "ebitda": -23_100_000,
        "tax": 0,
        "loan_payments": 0,
        "net_income": -23_100_000,
        "total_expenses": 23_900_000,
    },
    "net_margin_max": 0.0,              # deep loss
    "reconciliation_action": "proceed",  # numbers are internally consistent even though the business lost money
    "expect_halted": False,
    "must_flag_anomaly_types": {"duplicate_payment"},
    "correct": True,
}

CSV_CASES = [OCAK, SUBAT]

# ── bozuk_veri.csv — every date unparseable → gate must HOLD it ─────────────
# A "correct" outcome here is the pipeline refusing to auto-proceed, not a set
# of numbers. Used only in the calibration set.
BOZUK = {
    "file": "bozuk_veri.csv",
    "expect_held": True,               # halted OR awaiting_review under a real threshold
    "confidence_below_threshold": True,
}

# ── efatura_gib_2024.xml — UBL-TR e-Fatura ─────────────────────────────────
EFATURA = {
    "file": "efatura_gib_2024.xml",
    "invoice_number": "GIB2024000000108",
    "supplier_vkn": "4560012345",
    "line_extension_total": Decimal("285000.00"),
    "payable_amount": Decimal("342000.00"),
    "tdhp": {
        # account_code -> (debit, credit)
        "120.01": (Decimal("342000.00"), Decimal("0.0")),   # Alıcılar
        "600.01": (Decimal("0.0"), Decimal("285000.00")),   # Yurtiçi Satışlar
        "391.01": (Decimal("0.0"), Decimal("57000.00")),    # Hesaplanan KDV
    },
}
