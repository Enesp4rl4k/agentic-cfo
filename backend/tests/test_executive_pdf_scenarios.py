"""The executive PDF's scenario table: what-ifs, labelled as such, with the base row's basis (PR #133 follow-up)."""
from __future__ import annotations

from typing import Any

from app.services.executive_report_pdf import _build_html

SCENARIOS = {
    "pessimistic": {"label": "Kötümser", "twelve_month_net": -900_000, "runway_months": 1.5},
    "base": {"label": "Temel", "twelve_month_net": -600_000, "runway_months": 2.0},
    "optimistic": {"label": "İyimser", "twelve_month_net": -300_000, "runway_months": 4.0},
}


def _html(runway: dict[str, Any] | None, scenarios: dict[str, Any] = SCENARIOS) -> str:
    forecast: dict[str, Any] = {"scenarios": scenarios}
    if runway is not None:
        forecast["runway"] = runway
    return _build_html({"pnl": {"currency": "TRY"}, "forecast": forecast}, "Acme", "2026-Q1", "2026-04-01T00:00:00+00:00")


def _table(html: str) -> str:
    start = html.index("12 Aylık Tahmin")
    return html[start: html.index("</table>", start)]


KNOWN = {"status": "computed", "basis": "known", "balance_basis": "known", "as_of": "2026-03-31", "message": "m"}


def test_the_table_is_labelled_as_scenarios_and_never_as_measurement() -> None:
    table = _table(_html(KNOWN))
    assert "senaryo — varsayım, ölçüm değil" in table
    assert table.count('<span style="color:#64748b">(senaryo — varsayım)</span>') == 3   # every row carries the label


def test_the_base_row_is_the_runway_as_the_headline_shows_it() -> None:
    table = _table(_html(KNOWN))
    assert "2 ay (31 Mart 2026 ekstresine göre)" in table
    assert "1.5 ay (senaryo — varsayım)" in table and "4 ay (senaryo — varsayım)" in table   # derived rows say what they are


def test_an_assumed_base_says_so_on_every_row() -> None:
    table = _table(_html({**KNOWN, "balance_basis": "assumed", "message": "yalnızca 1 bakiye adımı"}))
    assert "varsayıma dayanıyor" in table
    assert table.count("temel nakit ömrü varsayıma dayanıyor") == 2      # the two derived rows


def test_a_scenario_from_an_unknown_base_is_unknown_not_a_number() -> None:
    table = _table(_html({"status": "no_balance", "message": "Kasa bakiyesi bilinmiyor"}))
    assert "2.0 ay" not in table and "4.0 ay" not in table and "1.5 ay" not in table
    assert table.count("bilinmiyor") >= 3


def test_a_forecast_with_no_runway_block_is_not_shown_as_proven() -> None:
    table = _table(_html(None))
    assert "doğrulanmadı" in table and "(31 Mart" not in table


def test_a_zero_month_runway_is_a_figure_not_unknown() -> None:
    table = _table(_html(KNOWN, {**SCENARIOS, "base": {**SCENARIOS["base"], "runway_months": 0.0}}))
    assert "0 ay (31 Mart 2026 ekstresine göre)" in table
