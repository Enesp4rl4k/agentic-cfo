"""SMMM invariants (plan M0): one journal, as the accountant left it.

D2 — nothing invented: a missing date holds the invoice, it is not 2024-01-01.
D3 — one ledger: e-Defter, yevmiye dump and mizan are built from the same
     approved entries, so they cannot disagree.
D4 — the accountant's decision is not lost: a correction changes the account
     it corrected and nothing else; a rejection removes the entry everywhere.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.models.smmm_onay import OnayDurumu
from app.services.accounting.approved_journal import mizan, uygula


def _entry(kayit_id, *, gerek=False, code="770", amount=10000):
    return {
        "kayit_id": kayit_id,
        "tarih": "2026-09-01",
        "onay_gerekli": gerek,
        "thp_hesap_kodu": code,
        "satirlar": [
            {"hesap_kodu": code, "hesap_adi": "Genel Yönetim Giderleri", "borc": amount, "alacak": 0},
            {"hesap_kodu": "102", "hesap_adi": "Bankalar", "borc": 0, "alacak": amount},
        ],
    }


def _onay(kayit_id, durum, *, yeni=None, eski="770"):
    return SimpleNamespace(
        kayit_id=kayit_id,
        durum=durum,
        otomatik_hesap_kodu=eski,
        duzeltilmis_hesap_kodu=yeni,
        duzeltilmis_hesap_adi="Pazarlama Giderleri" if yeni else None,
    )


def test_auto_posted_entries_are_in_the_journal_without_any_review_row():
    r = uygula([_entry("a")], [])
    assert [e["kayit_id"] for e in r.entries] == ["a"]
    assert r.excluded == {}


def test_rejected_entry_is_not_filed():
    r = uygula([_entry("a", gerek=True)], [_onay("a", OnayDurumu.REDDEDILDI)])
    assert r.entries == []
    assert r.excluded == {"a": "reddedildi"}


def test_pending_entry_is_not_filed():
    # Held for review and nobody decided: absent, and said to be absent.
    r = uygula([_entry("a", gerek=True)], [])
    assert r.entries == []
    assert r.excluded == {"a": "bekliyor"}


def test_correction_changes_only_the_classified_line_not_the_bank_side():
    r = uygula(
        [_entry("a", gerek=True)],
        [_onay("a", OnayDurumu.DUZELTILDI, yeni="760")],
    )
    (e,) = r.entries
    kodlar = [s["hesap_kodu"] for s in e["satirlar"]]
    assert kodlar == ["760", "102"]
    assert e["thp_hesap_kodu"] == "760"
    assert e["satirlar"][0]["hesap_adi"] == "Pazarlama Giderleri"
    assert e["satirlar"][1]["hesap_adi"] == "Bankalar"


def test_input_is_not_mutated():
    src = [_entry("a", gerek=True)]
    uygula(src, [_onay("a", OnayDurumu.DUZELTILDI, yeni="760")])
    assert src[0]["satirlar"][0]["hesap_kodu"] == "770"


def test_mizan_includes_auto_posted_and_stays_balanced():
    entries = [
        _entry("auto"),
        _entry("fixed", gerek=True, amount=5000),
        _entry("rejected", gerek=True, amount=7777),
    ]
    onaylar = [
        _onay("fixed", OnayDurumu.DUZELTILDI, yeni="760"),
        _onay("rejected", OnayDurumu.REDDEDILDI),
    ]
    m = mizan(uygula(entries, onaylar).entries)
    assert m["770"]["borc"] == 10000  # the auto-posted one
    assert m["760"]["borc"] == 5000  # corrected, on its own line
    assert m["102"]["alacak"] == 15000  # bank credited for both, not 22777
    assert sum(r["borc"] for r in m.values()) == sum(r["alacak"] for r in m.values())
