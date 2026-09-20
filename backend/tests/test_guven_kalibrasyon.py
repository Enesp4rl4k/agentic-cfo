"""Yayımlanan güven, ölçülen güvenle aynı olmalı.

`guven.KORPUS_OLCUMU` is what a reviewer sees as "test setinde x/n doğru". It
is measured here on every run, and the test fails when the table and the
measurement disagree — after a keyword is added, a rule changes, a case is
fixed. A calibration that is not re-measured describes a classifier that no
longer exists.

When this fails, read the diff it prints, check the change was intended, and
copy the measured table into `app/services/accounting/guven.py`.
"""
from __future__ import annotations

import pytest

from app.services.accounting import guven
from app.services.accounting.thp_classifier import get_thp_classifier
from tests.fixtures.tr_corpus.thp_calibration import THP_CALIBRATION_CASES


def olc() -> dict[str, tuple[int, int]]:
    counts: dict[str, list[int]] = {k: [0, 0] for k in guven.SEVIYELER}
    clf = get_thp_classifier()
    for description, tx_type, expected, _why in THP_CALIBRATION_CASES:
        r = clf.classify(description=description, amount_kurus=100_000, transaction_type=tx_type)
        counts[r.guven_seviyesi][1] += 1
        counts[r.guven_seviyesi][0] += int(r.hesap_kodu == expected)
    # Offline, the LLM path never runs and the default is not evidence.
    counts[guven.LLM] = [0, 0]
    counts[guven.VARSAYILAN] = [0, 0]
    return {k: (v[0], v[1]) for k, v in counts.items()}


def test_the_published_calibration_is_the_measured_one() -> None:
    measured = olc()
    assert measured == guven.KORPUS_OLCUMU, (
        "guven.KORPUS_OLCUMU ölçümle aynı değil — sınıflandırıcı ya da set "
        f"değişmiş. Ölçülen: {measured}"
    )


def test_the_set_is_not_rigged_to_pass() -> None:
    """A calibration set where everything is right measures nothing."""
    measured = olc()
    wrong = sum(t - d for d, t in measured.values())
    assert wrong > 0, "kalibrasyon setinde hiç hata yok — zor satırlar eksik"
    assert len(THP_CALIBRATION_CASES) >= 50


def test_every_rule_level_is_measured() -> None:
    measured = olc()
    for level in (guven.GUCLU_KURAL, guven.KURAL, guven.ZAYIF_KURAL):
        assert measured[level][1] > 0, f"{level} düzeyinde ölçüm yok"


# ── The number ───────────────────────────────────────────────────────────────

def test_fewer_examples_mean_less_confidence_at_the_same_hit_rate() -> None:
    assert guven.wilson_alt_sinir(6, 6) < guven.wilson_alt_sinir(60, 60)
    assert guven.wilson_alt_sinir(0, 0) == 0.0
    assert 0.0 < guven.wilson_alt_sinir(9, 10) < 0.9


def test_an_unmeasured_level_has_no_confidence_and_says_so() -> None:
    g = guven.degerlendir(guven.LLM, "dil modeli önerisi → 770")
    assert g.skor == 0.0
    assert g.to_dict()["olcum"] == "isabeti ölçülmedi"


def test_the_organisations_own_record_replaces_the_corpus_once_it_is_enough() -> None:
    thin = guven.degerlendir(guven.KURAL, "k", {guven.KURAL: (5, 5)})
    assert thin.kaynak != "kurum", "5 karar kurum geçmişi sayılmamalı"
    own = guven.degerlendir(guven.KURAL, "k", {guven.KURAL: (40, 45)})
    assert own.kaynak == "kurum"
    assert own.to_dict()["olcum"] == "sizin onaylarınızda 40/45 doğru"


def test_history_counts_approvals_as_right_and_corrections_as_wrong() -> None:
    kararlar = [
        (guven.KURAL, "onaylandi"), (guven.KURAL, "onaylandi"),
        (guven.KURAL, "duzeltildi"),
        (guven.KURAL, "reddedildi"),     # not about the account
        (guven.KURAL, "bekliyor"),       # no verdict yet
        (None, "onaylandi"),             # entries from before levels existed
    ]
    assert guven.gecmisten_olc(kararlar) == {guven.KURAL: (2, 3)}


# ── The classifier ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(("description", "tx_type", "level"), [
    ("Google Ads reklam harcamasi", "expense", guven.GUCLU_KURAL),  # 'google ads' birebir, iki kelime
    ("Ofis kira odemesi", "expense", guven.KURAL),                # 'kira' tek kelime
    ("Kiralama bedeli", "expense", guven.ZAYIF_KURAL),            # 'kira' kelime içinde
])
def test_the_level_names_the_evidence(description: str, tx_type: str, level: str) -> None:
    r = get_thp_classifier().classify(description=description, amount_kurus=1, transaction_type=tx_type)
    assert r.guven_seviyesi == level
    assert "→" in r.kanit


def test_no_match_is_not_dressed_up_as_a_percentage() -> None:
    """The fallback used to report 0.3 — '%30 güven' for no evidence at all."""
    r = get_thp_classifier().classify(description="zxqv", amount_kurus=1, transaction_type="expense")
    assert r.guven_seviyesi == guven.VARSAYILAN
    assert r.confidence == 0.0


# ── The journal entry ────────────────────────────────────────────────────────

def _entry(desc: str, gecmis=None):
    from app.agents.accounting.double_entry import DoubleEntryEngine

    tx = {"id": "t", "amount_kurus": 50_000, "type": "expense", "description": desc,
          "transaction_date": "2024-01-10T00:00:00+00:00", "kdv_kurus": 0}
    thp = get_thp_classifier().classify(description=desc, amount_kurus=50_000, transaction_type="expense")
    return DoubleEntryEngine().create_entry(tx, thp, guven_gecmisi=gecmis)


def test_the_entry_carries_why_it_can_be_trusted() -> None:
    k = _entry("Ofis kira odemesi")
    g = k.to_dict()["guven"]
    assert g["seviye"] == guven.KURAL
    assert "kira" in g["kanit"]
    assert g["olcum"] == "test setinde 26/29 doğru"
    assert k.confidence == g["skor"]


def test_corpus_evidence_alone_does_not_pass_the_gate() -> None:
    """Every rule level measures below 0.80 on the corpus, so entries are held —
    and the reason names the measurement instead of a bare percentage."""
    k = _entry("Ofis kira odemesi")
    assert k.onay_gerekli
    assert k.authority.get("matched_rule_id") == "low_confidence"


def test_an_organisation_whose_smmm_keeps_agreeing_earns_automatic_entries() -> None:
    k = _entry("Ofis kira odemesi", {guven.KURAL: (80, 81)})
    assert k.to_dict()["guven"]["kaynak"] == "kurum"
    assert k.confidence >= 0.8
    assert k.authority.get("matched_rule_id") != "low_confidence"


def test_a_history_of_corrections_keeps_entries_held() -> None:
    k = _entry("Ofis kira odemesi", {guven.KURAL: (12, 30)})
    assert k.confidence < 0.8
    assert k.onay_gerekli


def test_bulk_approvals_are_not_evidence() -> None:
    """Clearing the queue a page at a time must not raise the system's trust."""
    kararlar = [(guven.KURAL, "onaylandi", True)] * 50 + [(guven.KURAL, "onaylandi", False)] * 3
    assert guven.gecmisten_olc(kararlar) == {guven.KURAL: (3, 3)}
