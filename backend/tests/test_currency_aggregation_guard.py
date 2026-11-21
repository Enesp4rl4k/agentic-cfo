"""Structural guard: no money is summed across currencies.

Every function under `app/` that adds up money (`sum(...)` or `+=` over an amount) must either
go through the currency helpers (`app/core/currency_totals.py`, or an explicit currency
`group_by` / comparison), or be listed in `SAFE` below with the reason its input is one
currency by construction. A new aggregation that is neither fails this test, so a sum over
mixed currencies cannot be added by accident.

The list is also a ratchet the other way: an entry whose function no longer aggregates money,
or now handles currency itself, is stale and fails, so the list cannot rot.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

MONEY = re.compile(r"amount_cents|amount_kurus|_cents\b|_kurus\b|\bamount\b|kurus", re.I)
# What counts as handling currency: the shared helpers, or an explicit currency comparison / grouping.
HANDLES = re.compile(
    r"split_by_currency|totals_by_currency|foreign_summaries|code_of\(|"
    r"currency\s*(==|!=)|(==|!=)\s*[\w.\"']*currency|group_by\([^)]*currency|\"currency\"\s*:|currency=",
    re.I,
)

PIPELINE = "pipeline rows: `node_data_ingestion` keeps base-currency rows only (`_keep_base_currency`)"
JOURNAL = "a statutory journal / trial balance is one currency; `muhasebe_analiz` keeps base-currency rows only"
NOT_COMPANY_MONEY = "not company ledger money: one platform's own figures, or an input that is one currency by definition"
RECONCILIATION = "matches are made only between rows of the same currency (`reconciliation.py`)"
RADAR = "counts non-TRY items and never converts them (listed as not included)"
ONE_FILE = "totals of the rows of one parsed document, before the base-currency split"

SAFE: dict[str, str] = {
    "agents/anomaly_agent.py::detect_expense_spikes": PIPELINE,
    "agents/anomaly_agent.py::detect_round_numbers": PIPELINE,
    "agents/anomaly_agent.py::detect_vendor_concentration": PIPELINE,
    "agents/ceo/board_deck_agent.py::_build_slides": "adds the strategic priorities' own impact estimates, not ledger rows",
    "agents/chat_agent.py::_build_executive_context": "formats figures already computed by the pipeline (base currency)",
    "agents/cmo/campaign_agent.py::_build_campaign_alerts": NOT_COMPANY_MONEY,
    "agents/cmo/campaign_agent.py::_compute_campaign_metrics": NOT_COMPANY_MONEY,
    "agents/cmo/orchestrator.py::node_cmo_summary": NOT_COMPANY_MONEY,
    "agents/coo/resource_agent.py::_compute_resource_metrics": NOT_COMPANY_MONEY,
    "agents/cto/infra_agent.py::_compute_infra_metrics": NOT_COMPANY_MONEY,
    "agents/data_ingestion.py::_csv_sonucu": ONE_FILE,
    "agents/multi_period_agent.py::_aggregate_by_month": PIPELINE,
    "agents/pnl_agent.py::_monthly_buckets": "called by `_compute_pnl` after `split_by_currency`",
    "agents/reconciliation_node.py::_check_pnl_identities": PIPELINE,
    "agents/reconciliation_node.py::_uncategorized_expense_note": PIPELINE,
    "agents/tax_agent.py::_compute_vat": PIPELINE,
    "agents/tax_agent.py::_compute_withholding": PIPELINE,
    "agents/tax_agent.py::_paid_taxes": PIPELINE,
    "api/ledger.py::get_proposed_settlements": RECONCILIATION,
    "parsers/base.py::total_expense_cents": ONE_FILE,
    "parsers/base.py::total_income_cents": ONE_FILE,
    "services/accounting/journal_tables.py::_neden_yazilmaz": JOURNAL,
    "services/accounting/journal_tables.py::yaz": JOURNAL,
    "services/cash_radar.py::_split": RADAR,
    "services/consolidation_engine.py::consolidate": "no caller; entity figures are supplied in one reporting currency",
    "services/edefter_berat.py::_tax_detail": JOURNAL,
    "services/edefter_xbrl.py::generate_ledger": JOURNAL,
    "services/executive_report_pdf.py::_build_html": "renders figures already computed by the pipeline (base currency)",
    "services/forecast_backtest.py::build_backtest": PIPELINE,
    "services/inflation_accounting.py::calculate_adjustment": "TRY indexation of a statutory balance (VUK mükerrer 298)",
    "services/ingest/mizan.py::_ust_hesaplari_ayir": JOURNAL,
    "services/ingest/mizan.py::mizan_oku": JOURNAL,
    "services/monday_briefing.py::_inflow_estimated_share": RADAR,
    "services/prescriptive_recommender.py::analyze_and_prescribe": RADAR,
    "services/reconciliation.py::_note_payment": RECONCILIATION,
    "services/reconciliation.py::settle_from_matches": RECONCILIATION,
    "services/smmm_defensibility.py::build_packet": JOURNAL,
}


def _aggregations() -> dict[str, bool]:
    """'file::function' -> whether it handles currency, for every function that adds up money."""
    found: dict[str, bool] = {}
    for path in sorted(APP.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        rel = path.relative_to(APP).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            adds = False
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call):
                    name = inner.func.id if isinstance(inner.func, ast.Name) else (
                        inner.func.attr if isinstance(inner.func, ast.Attribute) else "")
                    adds = adds or (name == "sum" and bool(MONEY.search(ast.get_source_segment(source, inner) or "")))
                elif isinstance(inner, ast.AugAssign) and isinstance(inner.op, ast.Add):
                    adds = adds or bool(MONEY.search(ast.get_source_segment(source, inner) or ""))
            if adds:
                found[f"{rel}::{node.name}"] = bool(HANDLES.search(ast.get_source_segment(source, node) or ""))
    return found


def test_every_money_aggregation_handles_currency_or_is_listed_as_safe():
    found = _aggregations()
    unguarded = sorted(k for k, handles in found.items() if not handles and k not in SAFE)
    assert not unguarded, (
        "These functions add up money without handling currency (use app/core/currency_totals.py: "
        "split_by_currency / totals_by_currency, group by currency, or filter to one), or add them to "
        f"SAFE with the reason their input is one currency: {unguarded}"
    )


def test_the_safe_list_has_no_stale_entries():
    found = _aggregations()
    stale = sorted(k for k in SAFE if k not in found or found[k])
    assert not stale, f"SAFE lists functions that no longer aggregate money or now handle currency: {stale}"


def test_the_ledger_readers_use_the_shared_helper():
    """The ledger's own totals are not on the safe list: they go through `split_by_currency`."""
    for name in ("services/ledger.py::ledger_summary", "services/company_view.py::ledger_view",
                 "agents/pnl_agent.py::_compute_pnl", "agents/cashflow_agent.py::_classify_cashflow"):
        rel, func = name.split("::")
        source = (APP / rel).read_text(encoding="utf-8")
        node = next(n for n in ast.walk(ast.parse(source))
                    if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == func)
        assert "split_by_currency" in (ast.get_source_segment(source, node) or ""), name
        assert name not in SAFE
