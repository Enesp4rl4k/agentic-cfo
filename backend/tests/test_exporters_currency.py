"""The workbook and the dashboard JSON say the currency the figures were computed in, never lira by default."""
from __future__ import annotations

import openpyxl

from app.services.exporters import DashboardExporter, ExcelReportExporter

_SERIES = [{"month": "2026-01", "in": 1_000_00, "out": 400_00, "net": 600_00}]


def _book(tmp_path, currency: str | None):
    pnl = {"revenue": 10_000_00, "cogs": 4_000_00, "gross_profit": 6_000_00, "net_income": 3_000_00}
    cashflow = {"operating": 2_500_00, "net_change": 2_500_00, "monthly_series": _SERIES}
    if currency is not None:
        pnl["currency"] = cashflow["currency"] = currency
    forecast = {"scenarios": {"base": {"label": "Base", "months": _SERIES}}}
    out = str(tmp_path / "r.xlsx")
    ExcelReportExporter().export(pnl, cashflow, forecast, out)
    wb = openpyxl.load_workbook(out)
    return [str(c.value) for ws in wb for row in ws.iter_rows() for c in row if c.value is not None]


def test_a_usd_workbook_has_no_lira_anywhere(tmp_path):
    cells = _book(tmp_path, "USD")
    assert not any("₺" in c for c in cells)
    assert "Amount (USD)" in cells and "Cash In (USD)" in cells
    assert any(c.startswith("10,000.00") and c.endswith("USD") for c in cells)


def test_a_lira_workbook_still_uses_the_lira_sign(tmp_path):
    cells = _book(tmp_path, "TRY")
    assert "Amount (TRY)" in cells and "₺10,000.00" in cells


def test_a_workbook_with_no_currency_says_unknown_not_lira(tmp_path):
    cells = _book(tmp_path, None)
    assert not any("₺" in c for c in cells)
    assert "Amount (currency unknown)" in cells and "Cash In (currency unknown)" in cells
    assert any("10,000.00" in c and "currency unknown" in c for c in cells)


def test_the_dashboard_json_formats_in_the_runs_currency():
    pnl = {"revenue": 5_000_00, "net_income": 1_000_00, "currency": "EUR"}
    d = DashboardExporter.build_dashboard_dict(pnl, {"operating": 800_00, "currency": "EUR"}, {"scenarios": {}})
    assert "₺" not in str(d) and d["summary"]["revenue_formatted"].endswith("EUR")
