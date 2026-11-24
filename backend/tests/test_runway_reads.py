"""Nothing outside `services/runway_display.py` reads the scenario runway directly.

`forecast.scenarios.<name>.runway_months` is a bare number: it has no basis. A module that reads it shows or
ranks on a runway that may rest on an assumption. Readers take `runway_for_display(forecast)` (value, basis and
the sentence that says both). The allowlist names the producers and the numeric-only readers, each with its reason.
"""
from __future__ import annotations

import ast
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
_APP = _BACKEND / "app"

ALLOWED: dict[str, str] = {
    "app/services/runway_display.py": "the one reader",
    "app/agents/forecast_agent.py": "produces the scenario field from the runway block",
    "app/agents/report_agent.py": "copies the scenario fields (with runway_basis) into the stored dashboard",
    "app/services/decision_log.py": "reads the decision's own stored situation/expected keys; the latest runway comes from runway_for_display and the delta needs it proven",
    "app/services/decision_packet.py": "the situation carries runway_basis and runway_note",
    "app/services/multi_period_comparison.py": "period-over-period arithmetic on stored figures",
    "app/agents/cto/orchestrator.py": "reads the CFO summary's runway_months, which the projector fills only from a KNOWN runway (runway_display)",
    "app/api/advanced_intelligence.py": "returns the raw scenario value to a caller that also receives the runway block",
    "app/services/exporters.py": "reads a flat export payload key, not the scenario",
    "app/services/board_deck_pdf.py": "reads the board-deck payload's flat key, filled by the CEO agents from the helper",
    "app/services/runway.py": "the runway block's own field",
    "app/services/monday_briefing.py": "reads the company_runway block, not the scenario",
    "app/services/cascade_inputs.py": "reads the company_runway block and carries its full basis",
    "app/services/cascade_simulator.py": "kwargs and the stored forecast; its answers carry baseline_basis (test_basis_handoff)",
    "app/services/multidomain_counterfactual.py": "internal what-if input; the output never states the runway",
}
_KEY = "runway_months"


def _reads(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), str(path))
    lines: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
            and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == _KEY
        ) or (
            isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and node.slice.value == _KEY
            and isinstance(node.ctx, ast.Load)
        ):
            lines.append(node.lineno)
    return lines


def _found() -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for path in sorted(_APP.rglob("*.py")):
        hits = _reads(path)
        if hits:
            out[path.relative_to(_BACKEND).as_posix()] = hits
    return out


def test_no_module_reads_the_scenario_runway_directly():
    found = _found()
    new = {rel: lines for rel, lines in found.items() if rel not in ALLOWED}
    assert not new, (
        "Read the runway through `app.services.runway_display.runway_for_display` (value, basis, sentence), "
        f"not the bare scenario field; or allowlist the file with a reason: {new}"
    )


def test_the_allowlist_has_no_stale_entries_and_every_entry_a_reason():
    found = _found()
    stale = sorted(rel for rel in ALLOWED if rel not in found and rel != "app/services/runway_display.py")
    assert not stale, f"These no longer read the field; delete from ALLOWED: {stale}"
    assert all(len(reason.split()) >= 3 for reason in ALLOWED.values())
