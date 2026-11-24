"""The alert key of a KRI does not depend on the order of the KRI list (PR #146 follow-up, point 1).

The key used to be the KRI's name plus its POSITION among same-named KRIs. If the list order changed between a
failed slot and its retry (a new risk analysis landing in the same hour) and only one of two same-named alerts had
committed, the retry derived the committed id for the other KRI: one alert duplicated, the other lost. The key is
now derived from the KRI's content: name + a hash of what defines it, with a content-sorted rank for twins.
"""
from __future__ import annotations

import itertools
from typing import Any

from app.agents.orchestration.proactive_alerts import ProactiveAlertOrchestrator
from app.agents.orchestration.scan_support import kri_key


def _kri(name: str = "Nakit Rezervi", **extra: Any) -> dict[str, Any]:
    return {"name": name, "category": "financial", "unit": "ay", "threshold_amber": 6.0, "threshold_red": 3.0,
            "higher_is_worse": False, "source": "yüklenen KRI dosyası", "current_value": 2.0, "evidence": "x", **extra}


def _alert_ids(kris: list[dict[str, Any]]) -> dict[int, str]:
    """Alert id per KRI (by its position in the ORIGINAL list), derived the way the scan derives it."""
    scan = ProactiveAlertOrchestrator(db=None, slot="2025-02-03T09")
    return {id(k): scan._alert_id("org-1", "kri_breach", kri_key(k, kris)) for k in kris}


def _assert_order_independent(kris: list[dict[str, Any]]) -> None:
    expected = _alert_ids(kris)
    assert len(set(expected.values())) == len(kris), "two KRIs share an alert id: one alert would be lost"
    for order in itertools.permutations(kris):
        assert _alert_ids(list(order)) == expected, "the key of a KRI changed with the list order"


def test_same_named_kris_with_different_definitions_never_collide_and_ignore_order() -> None:
    _assert_order_independent([_kri(threshold_red=3.0), _kri(threshold_red=2.0), _kri(unit="gün")])


def test_same_named_kris_that_differ_only_by_value_are_told_apart_by_content_not_position() -> None:
    _assert_order_independent([_kri(current_value=2.0), _kri(current_value=1.0, evidence="y"), _kri(current_value=0.5)])


def test_identical_twins_still_get_two_distinct_keys() -> None:
    a, b = _kri(), _kri()
    keys = {kri_key(a, [a, b]), kri_key(b, [a, b])}
    assert len(keys) == 2
    assert {kri_key(b, [b, a]), kri_key(a, [b, a])} == keys, "the same pair of keys in any order"


def test_a_different_name_or_a_stable_id_keeps_its_own_key() -> None:
    a, b, c = _kri("Nakit Rezervi"), _kri("Likidite"), _kri(id="k-7")
    assert len({kri_key(x, [a, b, c]) for x in (a, b, c)}) == 3
    assert kri_key(c, [a, b, c]) == "id:k-7" == kri_key(c, [c])


def test_the_key_of_a_lone_kri_survives_a_new_value_and_a_new_sibling_elsewhere() -> None:
    a = _kri(current_value=2.0)
    other = _kri("Gider / Gelir", category="financial", unit="%")
    before = kri_key(a, [a])
    assert kri_key(_kri(current_value=1.4, evidence="yeni analiz"), [other]) == before   # value is not definition
    assert kri_key(a, [a, other]) == before                                              # another KRI does not shift it


def test_one_committed_and_one_retried_never_derive_the_same_id() -> None:
    """The reviewer's case: A committed in attempt 1; the list comes back reordered in the retry."""
    a, b = _kri(threshold_red=3.0), _kri(threshold_red=2.0)
    scan = ProactiveAlertOrchestrator(db=None, slot="2025-02-03T09")
    first = {n: scan._alert_id("org-1", "kri_breach", kri_key(k, [a, b])) for n, k in (("a", a), ("b", b))}
    retry = {n: scan._alert_id("org-1", "kri_breach", kri_key(k, [b, a])) for n, k in (("a", a), ("b", b))}
    assert retry == first and first["a"] != first["b"]


# ── a low runway on an assumption is amber, never "kritik", and is still alerted ────────────────────────────────

async def test_an_assumed_low_runway_is_alerted_as_attention_capped_and_a_known_one_as_critical(monkeypatch) -> None:
    from app.agents.risk.gercek_kri import gercek_kri
    from app.services.bank_balance import aged_basis
    from app.services.runway import compute_runway

    def forecast(age: int) -> dict[str, Any]:
        basis, note = aged_basis("known", None, age, "2026-03-31")
        opening = {"balance_cents": 7_500_00, "as_of": "2026-03-31", "age_days": age, "stale": age > 7,
                   "stale_after_days": 7, "filename": "e.csv", "basis": basis, "basis_note": note, "accounts": []}
        series = [{"month": f"2026-0{m}", "in": 0, "out": 5_000_00, "net": -5_000_00, "complete": True} for m in (1, 2, 3)]
        block = compute_runway(opening, {"monthly_series": series}, "TRY")
        return {"scenarios": {"base": {"runway_months": block["runway_months"]}}, "runway": block}

    async def channels(self, org_id, severity):
        return ["in_app"]

    async def quiet(self, *_a, **_k):
        return False

    sent: list[Any] = []

    async def collect(self, alert):
        sent.append(alert)

    async def no_cascade(self, *_a, **_k):
        return None

    for name, fn in (("_get_alert_channels", channels), ("_is_cooldown_active", quiet), ("_dispatch_alert", collect),
                     ("_run_cascade_and_alert", no_cascade)):
        monkeypatch.setattr(ProactiveAlertOrchestrator, name, fn)

    for age, severity in ((25, "high"), (3, "critical")):
        kris, posture = gercek_kri(None, forecast(age), None)

        async def current(self, org_id, _p=posture, _k=kris):
            return {"posture": _p, "kris": _k}

        monkeypatch.setattr(ProactiveAlertOrchestrator, "_compute_current_kris", current)
        sent.clear()
        await ProactiveAlertOrchestrator(db=None, slot="2025-02-03T09").scan_and_alert("org-1")
        breach = [a for a in sent if a.trigger == "kri_breach"]
        assert [a.severity for a in breach] == [severity], (age, [(a.trigger, a.severity) for a in sent])
        text = (breach[0].title + breach[0].body).replace("İ", "i").lower()
        assert ("dikkat" in text) == (severity == "high")
        if severity == "high":
            assert "kritik" not in text and "kanıtlı" not in text and "kırmızı" not in text


async def test_known_balance_with_an_edge_tolerance_is_critical_on_every_surface(monkeypatch) -> None:
    """One class: the service says critical (only an assumed BALANCE caps it); the alert agent, the KRI and the proactive
    alert all read that class, none applies an extra cap of its own."""
    from app.agents.alert_agent import _check_cashflow
    from app.agents.risk.gercek_kri import cfo_kri
    from app.services.runway import compute_runway

    series = [{"month": f"2026-0{m}", "in": 0, "out": 5_000_00, "net": -5_000_00, "complete": True} for m in (1, 2, 3)]
    series[0]["assumed"] = [{"edge": "start", "days": 2}]
    opening = {"balance_cents": 7_500_00, "as_of": "2026-03-31", "age_days": 3, "stale": False, "stale_after_days": 7,
               "filename": "e.csv", "basis": "known", "basis_note": None, "accounts": []}
    block = compute_runway(opening, {"monthly_series": series}, "TRY")
    forecast = {"scenarios": {"base": {"runway_months": block["runway_months"]}}, "runway": block}
    assert block["basis"] == "assumed" and block["level"] == "critical"

    assert [a["severity"] for a in _check_cashflow({"operating": 0}, forecast)] == ["critical"]
    kri = next(k for k in cfo_kri(None, forecast) if k["name"] == "Nakit Ömrü")
    assert kri["status"] == "red" and kri["level"] == "critical"

    async def channels(self, org_id, severity):
        return ["in_app"]

    monkeypatch.setattr(ProactiveAlertOrchestrator, "_get_alert_channels", channels)
    alert = await ProactiveAlertOrchestrator(db=None, slot="2025-02-03T09")._create_kri_alert("org-1", kri, "critical")
    assert alert is not None and alert.severity == "critical" and "Kırmızı" in alert.title
