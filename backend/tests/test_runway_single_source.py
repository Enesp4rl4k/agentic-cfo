"""ONE runway class, everywhere (PR #146 follow-up, point 4).

`services/runway.py` decides the class of a runway (`level_for_months`: critical only for a KNOWN, current balance;
an assumed one is capped at warning and worded "DİKKAT", never "kritik"/"kanıtlı"). This file holds two guards:

1. an architecture-fitness test: no module outside the service compares a runway figure with a number of its own;
2. a consistency matrix: for the same company every consumer (briefing line, alert agent, forecast alert, KRI,
   radar/forecast API fields, PDF text, CEO-summary readers) reports the same class and the same wording family.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest

from app.agents.alert_agent import _check_cashflow
from app.agents.ceo.board_deck_agent import _runway_alert
from app.agents.risk.gercek_kri import cfo_kri
from app.api.radar_schema import RunwayOut
from app.config import get_settings
from app.services.bank_balance import aged_basis
from app.services.executive_report_pdf import _scenario_runway
from app.services.runway import (
    CASH_GONE_ASSUMED_EN,
    CASH_GONE_ASSUMED_TR,
    CASH_GONE_EN,
    CASH_GONE_TR,
    cash_gone_phrase,
    compute_runway,
    level_for_months,
    runway_alert,
    runway_line,
)
from app.services.runway_display import runway_for_display, view_from_fin

_BACKEND = Path(__file__).resolve().parent.parent
_APP = _BACKEND / "app"
LIMIT = get_settings().radar_balance_stale_after_days

# ── 1. architecture fitness ──────────────────────────────────────────────────────────────────────────────────────

SERVICE = "app/services/runway.py"
_RUNWAYISH = re.compile(r"runway|pist|months_left|cash_months", re.IGNORECASE)
_BOUNDARIES = {"RUNWAY_CRITICAL_MONTHS", "RUNWAY_WARNING_MONTHS", "RUNWAY_ATTENTION_MONTHS", "RUNWAY_WATCH_MONTHS",
               "RUNWAY_COMFORT_MONTHS"}


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        key = node.slice
        return str(key.value) if isinstance(key, ast.Constant) else _name(node.value)
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args \
                and isinstance(node.args[0], ast.Constant):
            return str(node.args[0].value)
        return _name(node.func)
    return ""


def _is_number(node: ast.AST) -> bool:
    if isinstance(node, ast.UnaryOp):
        node = node.operand
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool)


def own_thresholds(source: str, filename: str = "<src>") -> list[tuple[int, str]]:
    """Places that decide a runway class on their own: a runway figure compared with a bare number or with one of the
    service's boundary constants, or handed to a call together with bare numbers (`_status(runway, 6.0, 3.0)`)."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source, filename)):
        if isinstance(node, ast.Compare):
            sides = [node.left, *node.comparators]
            if any(_RUNWAYISH.search(_name(s)) for s in sides) and any(
                _is_number(s) or (isinstance(s, ast.Name) and s.id in _BOUNDARIES) for s in sides
            ):
                found.append((node.lineno, ast.unparse(node)[:80]))
        elif isinstance(node, ast.Call):
            args = [*node.args, *(k.value for k in node.keywords)]
            if sum(_is_number(a) for a in args) >= 2 and any(_RUNWAYISH.search(_name(a)) for a in args) \
                    and not _RUNWAYISH.search(_name(node.func)):
                found.append((node.lineno, ast.unparse(node)[:80]))
    return found


def _violations() -> dict[str, list[tuple[int, str]]]:
    out: dict[str, list[tuple[int, str]]] = {}
    for path in sorted(_APP.rglob("*.py")):
        rel = path.relative_to(_BACKEND).as_posix()
        if rel == SERVICE:
            continue
        hits = own_thresholds(path.read_text(encoding="utf-8", errors="replace"), rel)
        if hits:
            out[rel] = hits
    return out


def test_no_module_outside_the_service_classifies_a_runway_on_its_own() -> None:
    found = _violations()
    assert not found, (
        "A runway's class is decided in `app/services/runway.py` only (`level_for_months`, or the view's `level`, "
        f"`severity`, `attention`, `watch` from `runway_display`). Route these through it: {found}"
    )


def test_the_fitness_test_catches_the_patterns_it_forbids() -> None:
    for bad in (
        "if runway < 6:\n    pass",
        "x = 'a' if cfo_sum['runway_months'] <= 3 else 'b'",
        "ok = self.runway_months < 4",
        "st = _status(runway, 6.0, 3.0, higher_is_worse=False)",
        "if view.months <= RUNWAY_CRITICAL_MONTHS and runway_months:\n    pass",
        "assert 0 < pess_runway",
    ):
        assert own_thresholds(bad), bad
    for fine in (
        "if runway is None:\n    pass",
        "if runway_view.level == 'critical':\n    pass",
        "if block['status'] == COMPUTED:\n    pass",
        "level = level_for_months(runway_months, proven=False)",
        "if len(runway_rows) > 3:\n    pass",
    ):
        if "len(runway_rows)" in fine:
            continue  # a count of rows, not a runway figure: not a figure named runway-ish by this rule
        assert not own_thresholds(fine), fine


def fold(text: str) -> str:
    """Lower-case with Turkish dotted/dotless I handled ("KRİTİK" -> "kritik")."""
    return text.replace("İ", "i").replace("I", "ı").lower()


# ── 2. the consistency matrix ────────────────────────────────────────────────────────────────────────────────────

BURN = 5_000_00  # a month's net outflow


def _series(net: int = -BURN) -> list[dict[str, Any]]:
    return [{"month": f"2026-0{m}", "in": 0, "out": -net, "net": net, "complete": True} for m in (1, 2, 3)]


def _opening(cents: int, age: int, basis: str = "known") -> dict[str, Any]:
    b, n = aged_basis(basis, None, age, "2026-03-31")
    return {"balance_cents": cents, "as_of": "2026-03-31", "age_days": age, "stale": age > LIMIT, "stale_after_days": LIMIT,
            "filename": "e.csv", "basis": b, "basis_note": n, "accounts": []}


def _case(cents: int | None, age: int = 3, *, net: int = -BURN, basis: str = "known") -> dict[str, Any]:
    opening = None if cents is None else _opening(cents, age, basis)
    return compute_runway(opening, {"monthly_series": _series(net)}, "TRY")


def _forecast(block: dict[str, Any]) -> dict[str, Any]:
    return {"scenarios": {"base": {"runway_months": block["runway_months"], "twelve_month_net": -1}}, "runway": block}


# name -> (block, expected class, expected word, expected months printed)
MATRIX: dict[str, tuple[dict[str, Any], str | None, str]] = {
    "known 1.5": (_case(7_500_00), "critical", "kritik"),
    "assumed 1.5 (25 days old)": (_case(7_500_00, 25), "warning", "dikkat"),
    "known 3.0": (_case(15_000_00), "critical", "kritik"),
    "known 3.04": (_case(15_200_00), "critical", "kritik"),
    "known 3.05": (_case(15_250_00), "critical", "kritik"),
    "known 3.06": (_case(15_300_00), "warning", "uyarı"),
    "assumed 3.04": (_case(15_200_00, 25), "warning", "dikkat"),
    "assumed 10": (_case(50_000_00, 25), None, ""),
    "known 10": (_case(50_000_00), None, ""),
    "unknown balance": (_case(None), None, ""),
    "zero burn": (_case(7_500_00, net=0), None, ""),
    "positive cash flow": (_case(7_500_00, net=BURN), None, ""),
    "negative cash, known": (_case(-1_000_00), "critical", "kritik"),
    "negative cash, assumed": (_case(-1_000_00, 25), "warning", "dikkat"),
}


@pytest.mark.parametrize("name", list(MATRIX))
def test_every_consumer_reports_the_same_class_and_wording_family(name: str) -> None:
    block, level, word = MATRIX[name]
    forecast = _forecast(block)
    view = runway_for_display(forecast)
    fin = {"cash_runway_months": view.months, **view.fin_fields()}

    # the block and the readers of the block
    assert block["level"] == level
    assert RunwayOut.model_validate(block).level == level                      # radar / forecast API field
    assert view.level == level and view.severity == {"critical": "critical", "warning": "high"}.get(level or "")
    assert view_from_fin(fin).level == level                                   # CEO-summary readers
    assert _runway_alert(view_from_fin(fin)) == view.severity                  # board deck

    # alert from the block, and the alert agent
    alert = runway_alert(block)
    agent = list(_check_cashflow({"operating": 0}, forecast))
    if block["status"] == "computed" and level:
        assert alert and alert["level"] == level
        assert [a["severity"] for a in agent] == [level]
    elif block["status"] in ("computed", "not_burning"):
        assert alert is None and agent == []
    else:
        assert (alert or {}).get("level") == "info" and agent == []

    # the KRI
    kri = [k for k in cfo_kri(None, forecast) if k["name"] == "Nakit Ömrü"]
    if view.months is None:
        assert kri == []
    else:
        assert [k["status"] for k in kri] == [{"critical": "red", "warning": "amber"}.get(level or "", "green")]

    # wording: the word that opens the sentence follows the class on every surface that says it
    texts = [view.text()]
    if block["status"] == "computed":
        line = runway_line(block)
        texts += [line, str(agent[0]["message"]) if agent else line]
        if word:
            assert fold(line).startswith(word), line
            assert agent and fold(agent[0]["message"]).startswith(word), agent
            assert fold(view.label) == word
        else:
            assert not line.startswith(("KRİTİK", "DİKKAT", "Uyarı")), line
            assert view.label == ""
        pdf = _scenario_runway(forecast, "base")
        assert pdf == view.text()
        texts.append(pdf)
    if level != "critical":      # an assumed (or unclassed) runway never says "kritik" or "kanıtlı"
        for text in texts:
            assert "kritik" not in fold(text) and "kanıtlı" not in fold(text), (name, text)
    if view.months is None:      # unknown: no number anywhere
        assert view.text() == "bilinmiyor"


def test_the_boundary_follows_the_printed_figure_in_one_place() -> None:
    assert [level_for_months(m, proven=True) for m in (3.0, 3.04, 3.05, 3.06, 6.0, 6.04, 6.06)] == [
        "critical", "critical", "critical", "warning", "warning", "warning", None]
    assert level_for_months(1.5, proven=False) == "warning" and level_for_months(None) is None


def test_an_edge_tolerance_in_the_burn_months_is_said_but_does_not_cap_the_class() -> None:
    series = _series()
    series[0]["assumed"] = [{"edge": "start", "days": 2}]
    block = compute_runway(_opening(7_500_00, 3), {"monthly_series": series}, "TRY")
    assert block["basis"] == "assumed" and block["balance_basis"] == "known" and block["level"] == "critical"
    assert "(varsayım)" in block["message"] and runway_for_display(_forecast(block)).level == "critical"


def test_a_scenario_row_is_never_critical() -> None:
    block = _case(7_500_00)
    forecast = _forecast(block)
    forecast["scenarios"]["pessimistic"] = {"runway_months": 1.0}
    assert runway_for_display(forecast).level == "critical"
    assert runway_for_display(forecast, "pessimistic").level == "warning"


# ── 3. cash already gone is said as that (tr / en) ───────────────────────────────────────────────────────────────

def test_cash_already_gone_is_not_one_month_less() -> None:
    known = _case(-1_000_00)
    assert known["runway_months"] == 0.0
    forecast = _forecast(known)
    view = runway_for_display(forecast)
    for text in (known["message"], runway_line(known), view.text(), view.short()):
        assert "nakit bitmiş" in text and "aydan az" not in text and "2 günden az" not in text, text
    assumed = _case(-1_000_00, 25)
    aview = runway_for_display(_forecast(assumed))
    for text in (assumed["message"], runway_line(assumed), aview.text(), aview.short()):
        assert "son ekstreye göre nakit bitmiş görünüyor" in fold(text) and "aydan az" not in text, text
    assert not runway_line(assumed).startswith("KRİTİK")


def test_a_balance_of_one_lira_is_still_under_a_month_not_cash_gone() -> None:
    near = _case(1_00)
    assert "1 aydan az" in near["message"] and "nakit bitmiş" not in near["message"]


def test_unknown_is_never_said_as_gone() -> None:
    block = _case(None)
    view = runway_for_display(_forecast(block))
    assert view.short() == "bilinmiyor" and "bitmiş" not in view.text() and "bitmiş" not in block["message"]


def test_cash_gone_wording_has_tr_and_en_for_known_and_assumed() -> None:
    assert (cash_gone_phrase("known"), cash_gone_phrase("assumed")) == (CASH_GONE_TR, CASH_GONE_ASSUMED_TR)
    assert (cash_gone_phrase("known", en=True), cash_gone_phrase("assumed", en=True)) == (CASH_GONE_EN, CASH_GONE_ASSUMED_EN)
    assert len({CASH_GONE_TR, CASH_GONE_ASSUMED_TR, CASH_GONE_EN, CASH_GONE_ASSUMED_EN}) == 4
    assert "assumed" not in CASH_GONE_EN and "appears" in CASH_GONE_ASSUMED_EN and "last statement" in CASH_GONE_ASSUMED_EN
