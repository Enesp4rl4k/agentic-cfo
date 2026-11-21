"""No hard-coded currency in backend money-presentation code.

A symbol or a currency code in a string is a claim about the user's money. Text that presents money
(chat prompts, narratives, exports, PDFs, briefings, notifications) takes the currency from the data
(`pnl["currency"]`, a row's own currency, `core/currency_totals.effective_base`) through
`fmt_amount` / `fmt_compact` / `fmt_money`, and writes a bare number when the data names none.

This guard fails when a string constant outside the allowlist carries `₺`, `TL`, `TRY`, `USD`, `EUR` or
`GBP` (docstrings and comments are not scanned). Like the other fitness tests it is a ratchet: a NEW file
fails, and an allowlist entry whose code no longer has a literal fails too, so the list can only shrink.

Every entry says why the literal is legitimate. `# DEBT` entries are literals known to be wrong or unproven
and not yet fixed; each names who or what must change.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
_APP = _BACKEND / "app"
_LITERAL = re.compile(r"₺|\bTL\b|\bTRY\b|\bUSD\b|\bEUR\b|\bGBP\b")

# A key is a file, or a directory when it ends in "/".
ALLOWED: dict[str, str] = {
    # ── Upload and ingest: recognising and storing what a document states ─────────────────────────────
    "app/parsers/": "document parsers recognise a stated currency and default per source format on ingest",
    "app/services/ingest/": "the upload path: currency markers read from cells, rows and e-belge fields",
    "app/services/ocr_service.py": "OCR text patterns that detect a currency marker in a scanned document",
    "app/services/csv_validator.py": "strips currency symbols from a pasted amount before parsing it",
    "app/services/data_plane/normalization_service.py": "ingest normalisation of a raw amount and its stated currency",
    "app/services/open_banking/": "bank connector payload shapes (the bank's own currency field and fixtures)",
    "app/services/rag/grounding_validator.py": "recognises currency tokens in model output to check them against the data",
    "app/services/reflection_agent.py": "recognises currency tokens in model output to check them",
    # ── Storage schema and the one place that owns the symbols ────────────────────────────────────────
    "app/models/": "column defaults of the stored schema (migrations own them), not presentation",
    "app/core/currency_totals.py": "the single module that defines DEFAULT_BASE and the lira sign",
    "app/core/financial.py": "format_currency_try / format_currency_usd helpers: the function name states the currency",
    # ── Turkish statute: the amounts are lira by law, whatever the company reports in ─────────────────
    "app/agents/tax_agent.py": "KDV, stopaj and corporate tax are computed and payable in lira",
    "app/agents/compliance/turkey_regulations.py": "Turkish regulatory thresholds are stated in lira",
    "app/services/gib_efatura.py": "GIB e-Fatura tax lines are lira by law",
    "app/services/regional/tax_calculator.py": "Turkish KDV and stopaj summaries are lira by law",
    "app/services/tax_calendar.py": "tax obligations are filtered to lira ledger rows",
    "app/services/recurring_obligations.py": "recurring obligations are matched on lira ledger rows",
    "app/services/edefter_xbrl.py": "e-Defter XBRL declares the iso4217:TRY unit the standard requires",
    "app/services/inflation_accounting.py": "VUK inflation accounting is a lira computation",
    "app/services/consolidation_engine.py": "group consolidation is stated in lira (statutory consolidated statements)",
    "app/services/size_profile.py": "PROVISIONAL owner-decided outflow bands, defined in lira",
    "app/platform/authority_matrix.py": "approval-limit policy note: a lira threshold set by policy",
    # ── Macro data and simulations whose inputs are named in lira (`*_try`) ───────────────────────────
    "app/agents/risk/turkey_macro_risks.py": "Turkish macro risk catalogue: TRY exchange-rate risk is its subject",
    "app/services/tcmb_macro.py": "TCMB exchange-rate series: USD/TRY and EUR/TRY are the data",
    "app/api/macro.py": "serves the TCMB macro snapshot (USD/TRY, EUR/TRY)",
    "app/services/cascade_simulator.py": "what-if simulation: its request inputs are lira (`*_try`)",
    "app/api/cascade.py": "what-if simulation request schema in lira",
    "app/services/counterfactual_engine.py": "what-if simulation: its request inputs are lira (`*_try`)",
    "app/api/counterfactual.py": "what-if simulation request schema and log lines in lira",
    "app/services/multidomain_counterfactual.py": "what-if simulation: its request inputs are lira (`*_try`)",
    "app/api/multidomain_cf.py": "what-if simulation request field labels in lira",
    "app/services/nl_simulation_bridge.py": "answers a what-if simulation whose inputs are lira",
    "app/services/monte_carlo.py": "Monte Carlo request inputs are lira (`*_try`)",
    "app/services/prescriptive_recommender.py": "recommendation impact is `impact_try` by its own definition",
    "app/api/risk.py": "risk request fields documented as TRY per month",
    # ── Bootstrap, fixtures and stubs ─────────────────────────────────────────────────────────────────
    "app/api/org.py": "regional bootstrap for a new org (TR gets TRY) and the stored-default echo",
    "app/services/org_membership.py": "a new Turkish org is created with TRY",
    "app/services/demo_seeder.py": "the demo company's seed rows are lira",
    "app/services/eval_harness.py": "evaluation test cases with fixed sample answers",
    "app/services/bot_gateways.py": "static demo approval card (sample amount, not the user's data)",
    "app/services/benchmark_intelligence.py": "benchmark metric unit label for a revenue-per-employee peer figure",
    # ── DEBT: literal known to be unproven; not fixed here ────────────────────────────────────────────
    "app/agents/forecast_agent.py": "DEBT: `_fmt` labels forecast narratives with the lira sign; owned by the forecast agent's PR",
    "app/api/radar_schema.py": "DEBT: `currency: str = \"TRY\"` schema default, always overridden; changing it regenerates the OpenAPI contract",
    "app/services/cash_radar.py": "DEBT: RadarResult.currency default, always set from effective_base_of",
    "app/services/company_view.py": "DEBT: CompanyView.base_currency default, always set by the ledger view",
    "app/services/integrations.py": "DEBT: connector payloads default a missing currency to TRY (ingest-side)",
    "app/api/muhasebe.py": "DEBT: a journal for a job with no org falls back to TRY",
    "app/services/semantic/": "DEBT: the semantic snapshot defaults a missing currency to USD; needs its own contract change",
}


def _is_docstring(node: ast.AST, docstrings: set[int]) -> bool:
    return id(node) in docstrings


def _hits(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), str(path))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return [
        (node.lineno, node.value.strip()[:60])
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and not _is_docstring(node, docstrings)
        and _LITERAL.search(node.value)
    ]


def _files_with_literals() -> dict[str, list[tuple[int, str]]]:
    found: dict[str, list[tuple[int, str]]] = {}
    for path in sorted(_APP.rglob("*.py")):
        hits = _hits(path)
        if hits:
            found[path.relative_to(_BACKEND).as_posix()] = hits
    return found


def _allowed(rel: str) -> bool:
    return any(rel == key or (key.endswith("/") and rel.startswith(key)) for key in ALLOWED)


def test_no_new_hard_coded_currency_literal() -> None:
    new = {rel: hits[:3] for rel, hits in _files_with_literals().items() if not _allowed(rel)}
    assert not new, (
        "A hard-coded currency literal in presentation code: take the currency from the data "
        "(`fmt_amount` / `fmt_compact` / `fmt_money` in app.core.currency_totals; a bare number when the "
        f"data names none). Or add the file to ALLOWED with a one-line reason: {new}"
    )


def test_allowlist_shrinks_when_a_literal_is_removed() -> None:
    found = _files_with_literals()
    stale = sorted(
        key for key in ALLOWED
        if not any(rel == key or (key.endswith("/") and rel.startswith(key)) for rel in found)
    )
    assert not stale, f"No currency literal left here; delete from ALLOWED: {stale}"


def test_every_allowlist_entry_has_a_reason() -> None:
    assert all(len(reason.split()) >= 4 for reason in ALLOWED.values())
    assert len(ALLOWED) <= 60, "The allowlist is meant to stay short; fix literals instead of adding entries."
