"""Structural guard: no money is summed across currencies.

Every function under `app/` that adds up money (`sum(...)` or `+=` over an amount) must either go through
the currency helpers (`app/core/currency_totals.py`, or an explicit currency `group_by` / comparison), or be
listed in `SAFE` below with its OWN reason it is single-currency, and (where that can be checked by reading
the code) a check that the claim still holds. A new aggregation that is neither fails this test.

The list is also a ratchet the other way: an entry whose function no longer aggregates money, or now handles
currency itself, is stale and fails, so the list cannot rot. A "domain" entry names something that cannot be
checked mechanically (a statutory document, a record with no currency field); each says why in one line.
"""
from __future__ import annotations

import ast
import re
from collections.abc import Callable
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"

MONEY = re.compile(r"amount_cents|amount_kurus|_cents\b|_kurus\b|\bamount\b|kurus", re.I)
# What counts as handling currency: the shared helpers, or an explicit currency comparison / grouping.
HANDLES = re.compile(
    r"split_by_currency|totals_by_currency|foreign_summaries|code_of\(|"
    r"currency\s*(==|!=)|(==|!=)\s*[\w.\"']*currency|group_by\([^)]*currency|\"currency\"\s*:|currency=",
    re.I,
)


def _read(rel: str) -> str:
    return (APP / rel).read_text(encoding="utf-8")


def _function_source(rel: str, name: str) -> str:
    source = _read(rel)
    node = next(n for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == name)
    return ast.get_source_segment(source, node) or ""


def _callers(name: str, *, excluding: str) -> list[str]:
    """Files under app/ (other than `excluding`) that mention `name` followed by a call or an import."""
    hits = []
    for path in APP.rglob("*.py"):
        rel = path.relative_to(APP).as_posix()
        if rel != excluding and re.search(rf"\b{name}\b", path.read_text(encoding="utf-8")):
            hits.append(rel)
    return hits


# -- checks: each one reads the code and fails if the single-currency claim stops being true ------------

def _after_ingestion_split(rel: str) -> Callable[[], None]:
    """The module is a pipeline step wired into the graph after `keep_base_currency` ran on ingestion."""
    def check() -> None:
        graph = _read("agents/orchestrator.py")
        module = "app." + rel.removesuffix(".py").replace("/", ".")
        assert f"from {module} import" in graph, f"{rel} is not a node of the CFO graph"
        ingestion = _function_source("agents/orchestrator.py", "node_data_ingestion")
        assert "_keep_base_currency(state, patch)" in ingestion
        assert 'set_entry_point("data_ingestion' in graph.replace("'", '"')
    return check


def _only_called_after_split() -> None:
    body = _function_source("agents/pnl_agent.py", "_compute_pnl")
    assert body.index("split_by_currency") < body.index("_monthly_buckets(")
    assert _callers("_monthly_buckets", excluding="agents/pnl_agent.py") == []


def _matches_are_same_currency() -> None:
    source = _read("services/reconciliation.py")
    assert source.count("i.currency == row.currency") >= 2, "reconciliation must only match same-currency rows"


def _radar_items_are_one_currency() -> None:
    body = _function_source("services/cash_radar.py", "compute_cash_radar")
    assert "normalise(item.currency) != cur" in body and body.index("!= cur") < body.index("RadarItem(")


def _journal_is_primary_currency() -> None:
    assert "entries_of" in _function_source("services/accounting/approved_journal.py", "yukle")
    assert "entries_of" in _read("services/accounting/journal_store.py")
    assert "groups_by_currency" in _read("api/muhasebe.py")


def _has_no_caller(name: str, module: str) -> Callable[[], None]:
    def check() -> None:
        outside = _callers(name, excluding=module)
        assert outside == [], f"{name} is now called from {outside}: it needs currency handling"
    return check


# key -> (reason, check or None). A None check is a domain claim; the reason says why.
SAFE: dict[str, tuple[str, Callable[[], None] | None]] = {
    # --- pipeline steps: rows arrive after ingestion kept ONE currency ---
    "agents/anomaly_agent.py::detect_expense_spikes": (
        "monthly expense per month over pipeline rows, which hold one currency after ingestion",
        _after_ingestion_split("agents/anomaly_agent.py")),
    "agents/anomaly_agent.py::detect_vendor_concentration": (
        "a vendor's share of total expense, over pipeline rows of one currency",
        _after_ingestion_split("agents/anomaly_agent.py")),
    "agents/multi_period_agent.py::_aggregate_by_month": (
        "revenue and expense per month over pipeline rows of one currency",
        _after_ingestion_split("agents/multi_period_agent.py")),
    "agents/reconciliation_node.py::_check_pnl_identities": (
        "re-adds the same pipeline rows the P&L used, to verify the P&L's own identities",
        _after_ingestion_split("agents/reconciliation_node.py")),
    "agents/reconciliation_node.py::_uncategorized_expense_note": (
        "sums uncategorised expense among pipeline rows of one currency",
        _after_ingestion_split("agents/reconciliation_node.py")),
    "agents/tax_agent.py::_compute_vat": (
        "VAT on pipeline rows of one currency (a foreign-currency invoice's lira VAT needs a rate we do not keep)",
        _after_ingestion_split("agents/tax_agent.py")),
    "agents/tax_agent.py::_compute_withholding": (
        "withholding over pipeline rows of one currency",
        _after_ingestion_split("agents/tax_agent.py")),
    "agents/tax_agent.py::_paid_taxes": (
        "tax payments among pipeline rows of one currency",
        _after_ingestion_split("agents/tax_agent.py")),
    "agents/pnl_agent.py::_monthly_buckets": (
        "private helper of `_compute_pnl`, called only after its `split_by_currency`",
        _only_called_after_split),
    # --- matching and the radar: same currency by construction ---
    "services/reconciliation.py::_note_payment": (
        "adds a matched bank line to an open item; matches are made only between same-currency rows",
        _matches_are_same_currency),
    "services/reconciliation.py::settle_from_matches": (
        "sums the matches of one open item; matches are same-currency only",
        _matches_are_same_currency),
    "api/ledger.py::get_proposed_settlements": (
        "one transfer paying several invoices: the lumped matches are same-currency (reconciliation)",
        _matches_are_same_currency),
    "services/cash_radar.py::_split": (
        "splits the radar's items by basis; the radar only holds items in its own currency",
        _radar_items_are_one_currency),
    "services/monday_briefing.py::_inflow_estimated_share": (
        "a ratio over the radar's weekly basis splits, which are in the radar's one currency",
        _radar_items_are_one_currency),
    # --- journals: per-currency runs, statutory outputs restricted to the primary currency ---
    "services/accounting/journal_tables.py::_neden_yazilmaz": (
        "checks ONE entry's debit equals credit (an entry is in one currency)", _journal_is_primary_currency),
    "services/accounting/journal_tables.py::yaz": (
        "writes the journal tables from entries `journal_store` already restricted to the primary currency",
        _journal_is_primary_currency),
    "services/edefter_xbrl.py::generate_ledger": (
        "the e-Defter is built from the approved journal, which `yukle` restricts to the primary currency",
        _journal_is_primary_currency),
    "services/edefter_berat.py::_tax_detail": (
        "sums amounts in the e-Defter file just generated from the primary-currency journal",
        _journal_is_primary_currency),
    # --- no caller: wiring it up must come with currency handling ---
    "services/consolidation_engine.py::consolidate": (
        "no module calls the consolidation engine", _has_no_caller("consolidation_engine", "services/consolidation_engine.py")),
    "services/prescriptive_recommender.py::analyze_and_prescribe": (
        "no module calls the recommender", _has_no_caller("prescriptive_recommender", "services/prescriptive_recommender.py")),
    "parsers/base.py::total_income_cents": (
        "statement totals property that nothing reads", _has_no_caller("total_income_cents", "parsers/base.py")),
    "parsers/base.py::total_expense_cents": (
        "statement totals property that nothing reads", _has_no_caller("total_expense_cents", "parsers/base.py")),
    "services/inflation_accounting.py::calculate_adjustment": (
        "no module calls the inflation adjustment", _has_no_caller("inflation_accounting", "services/inflation_accounting.py")),
    # --- domain claims that cannot be checked by reading code ---
    "services/ingest/mizan.py::mizan_oku": (
        "domain: an uploaded trial balance is one company's statutory TRY document (VUK)", None),
    "services/ingest/mizan.py::_ust_hesaplari_ayir": (
        "domain: parent-account totals inside that one TRY trial balance", None),
    "agents/cmo/campaign_agent.py::_compute_campaign_metrics": (
        "domain: ad-campaign records (spend/revenue) from the marketing input, which has no currency field", None),
    "agents/cmo/campaign_agent.py::_build_campaign_alerts": (
        "domain: the same campaign records", None),
    "agents/cmo/orchestrator.py::node_cmo_summary": (
        "domain: the same campaign records", None),
    "agents/coo/resource_agent.py::_compute_resource_metrics": (
        "domain: resource cost records from the operations input, which has no currency field", None),
    "agents/cto/infra_agent.py::_compute_infra_metrics": (
        "domain: cloud cost records from the infrastructure input, which has no currency field", None),
}


def _is_count(call: ast.Call) -> bool:
    """`sum(1 for ...)`: a count, not money."""
    return bool(call.args) and isinstance(call.args[0], ast.GeneratorExp) and isinstance(
        call.args[0].elt, ast.Constant)


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
                segment = ast.get_source_segment(source, inner) or ""
                if isinstance(inner, ast.Call):
                    name = inner.func.id if isinstance(inner.func, ast.Name) else (
                        inner.func.attr if isinstance(inner.func, ast.Attribute) else "")
                    adds = adds or (name == "sum" and not _is_count(inner) and bool(MONEY.search(segment)))
                elif isinstance(inner, ast.AugAssign) and isinstance(inner.op, ast.Add):
                    adds = adds or (not isinstance(inner.value, ast.JoinedStr | ast.Constant | ast.List)
                                    and bool(MONEY.search(segment)))
            if adds:
                found[f"{rel}::{node.name}"] = bool(HANDLES.search(ast.get_source_segment(source, node) or ""))
    return found


def test_every_money_aggregation_handles_currency_or_is_listed_as_safe():
    found = _aggregations()
    unguarded = sorted(k for k, handles in found.items() if not handles and k not in SAFE)
    assert not unguarded, (
        "These functions add up money without handling currency (use app/core/currency_totals.py: "
        "split_by_currency / totals_by_currency, group by currency, or filter to one), or add them to "
        f"SAFE with their own reason and a check: {unguarded}"
    )


def test_the_safe_list_has_no_stale_entries():
    found = _aggregations()
    stale = sorted(k for k in SAFE if k not in found or found[k])
    assert not stale, f"SAFE lists functions that no longer aggregate money or now handle currency: {stale}"


def test_every_safe_entry_has_its_own_reason_and_the_checkable_ones_are_checked():
    reasons = [reason for reason, _ in SAFE.values()]
    assert all(len(r) > 20 for r in reasons)
    # Reasons that are not shared constants: each may repeat only when the claim really is the same one.
    domain = [k for k, (_, check) in SAFE.items() if check is None]
    assert len(domain) <= 10, "keep unchecked (domain) entries few; check or remove the rest"
    for key in SAFE:
        assert (APP / key.split("::")[0]).exists(), key


@pytest.mark.parametrize("key", [k for k, (_, check) in SAFE.items() if check is not None])
def test_the_safe_claim_still_holds(key):
    check = SAFE[key][1]
    assert check is not None
    check()


def test_the_ledger_readers_use_the_shared_helper():
    """The ledger's own totals are not on the safe list: they go through `split_by_currency`."""
    for name in ("services/ledger.py::ledger_summary", "services/company_view.py::ledger_view",
                 "agents/pnl_agent.py::_compute_pnl", "agents/cashflow_agent.py::_classify_cashflow"):
        rel, func = name.split("::")
        assert "split_by_currency" in _function_source(rel, func), name
        assert name not in SAFE
