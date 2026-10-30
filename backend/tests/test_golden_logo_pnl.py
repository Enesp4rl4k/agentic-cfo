"""Plan v8 §A1 — the demo Logo export's P&L, computed by hand from the file.

The expectations below were summed from `demo/data/logo_tiger_2024.csv` per
account code (Tekdüzen Hesap Planı), not read off this pipeline's output:

    600  revenue (49 rows)                         9.799.500,00
    740, 750, 760, 770  expenses (97 rows)         4.585.700,00
        740 hizmet üretim maliyeti     391.500
        750 AR-GE                      632.800
        760 pazarlama/satış          3.129.500
        770 genel yönetim              431.900
    EBITDA                                         5.213.800,00
    360  KDV / stopaj payments (13 rows)             571.550,00  — balance sheet
    193  geçici vergi (4 rows)                       585.000,00  — balance sheet

Live audit 2026-10-24 (W4): the "Hesap Kodu" column was never read, categories
came from keywords, and the dashboard showed EBITDA ₺6,03M.
"""
from __future__ import annotations

from pathlib import Path

from app.agents.data_ingestion import _tablo_ekstresi
from app.agents.pnl_agent import _compute_pnl

DEMO = Path(__file__).resolve().parents[2] / "demo" / "data" / "logo_tiger_2024.csv"


def _txs() -> list[dict]:
    txs = _tablo_ekstresi(str(DEMO))
    assert txs, "the demo export did not parse"
    return txs


def test_demo_pnl_matches_the_hand_calculation():
    pnl = _compute_pnl(_txs())
    assert pnl["revenue"] == 9_799_500_00
    assert pnl["cogs"] + pnl["total_opex"] == 4_585_700_00
    assert pnl["ebitda"] == 5_213_800_00


def test_vat_and_prepaid_tax_stay_out_of_the_pnl_but_in_the_cash_flow():
    txs = _txs()
    pnl = _compute_pnl(txs)
    assert pnl["tax"] == 0
    assert pnl["net_income"] == pnl["ebitda"]
    tax_payments = [t for t in txs if t["category"] == "tax_payment"]
    assert len(tax_payments) == 17
    assert sum(t["amount_cents"] for t in tax_payments) == 1_156_550_00
    assert all(t["type"] == "expense" for t in tax_payments)  # cash still leaves


def test_every_row_keeps_its_account_code():
    txs = _txs()
    assert len(txs) == 163
    assert {t["account_code"] for t in txs} == {"193", "360", "600", "740", "750", "760", "770"}


def test_a_salary_row_on_a_sales_account_is_an_expense_not_revenue():
    """'Satış Ekibi' matched the revenue keyword; the account code says expense."""
    row = next(t for t in _txs() if "Satış Ekibi" in t["description"])
    assert row["type"] == "expense"
    assert row["category"] == "salary"


def test_balance_sheet_cash_is_neither_revenue_nor_expense():
    """A loan drawn (credit on 300) and a KDV payment move cash, not profit."""
    pnl = _compute_pnl([
        {"type": "income", "category": "revenue", "amount_cents": 100_00, "transaction_date": "2024-01-02"},
        {"type": "income", "category": "transfer", "amount_cents": 500_00, "transaction_date": "2024-01-03"},
        {"type": "expense", "category": "tax_payment", "amount_cents": 18_00, "transaction_date": "2024-01-26"},
    ])
    assert (pnl["revenue"], pnl["total_expenses"], pnl["ebitda"]) == (100_00, 0, 100_00)


async def test_the_tax_section_reports_what_the_books_say_was_paid():
    from app.agents.state import AgentRunConfig
    from app.agents.tax_agent import run_tax

    txs = _txs()
    result = await run_tax({"transactions": txs, "pnl": _compute_pnl(txs)}, AgentRunConfig())
    paid = result.patch["tax"]["paid"]
    assert (paid["total"], paid["row_count"], paid["basis"]) == (1_156_550_00, 17, "ledger")
    assert paid["by_month"]["2024-03"] == 32_500_00 + 85_000_00  # F029 KDV Mart + F030 geçici vergi Q1


async def test_the_dashboard_carries_the_tax_shape_the_tax_page_reads():
    """frontend/src/app/(dashboard)/tax/page.tsx reads tax.vat.net_vat_payable,
    tax.corporate, tax.reference_month and tax.paid. The dashboard flattened the
    block into other keys; it never showed because tax was always skipped."""
    from app.agents.report_agent import _build_dashboard_json
    from app.agents.state import AgentRunConfig
    from app.agents.tax_agent import run_tax

    txs = _txs()
    pnl = _compute_pnl(txs)
    tax = (await run_tax({"transactions": txs, "pnl": pnl}, AgentRunConfig())).patch["tax"]
    block = _build_dashboard_json({"transactions": txs, "pnl": pnl, "tax": tax})["tax"]
    assert {"vat", "withholding", "corporate", "payment_calendar", "reference_month", "paid"} <= set(block)
    assert block["vat"]["net_vat_payable"] >= 0
    assert block["paid"]["total"] == 1_156_550_00
