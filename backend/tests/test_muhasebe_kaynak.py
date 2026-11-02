"""Plan v8 §A4 (W8) — the journal copies the source's account; the queue holds policy, not doubt.

Live audit 2026-10-24: `/muhasebe/analiz` on the demo Logo export held 163 of
163 entries (average confidence 0.527) and re-guessed every account from the
description — revenue on 602, rent on 730, five rows on 260 (fixed assets).

Expected, from `demo/data/logo_tiger_2024.csv` by hand:
- every entry is on the account the source names;
- the bank side closes at the file's last running balance, 4.057.250,00;
- 48 rows are above ₺100.000 (the default policy's owner threshold) — those,
  and only those, wait for approval.
"""
from __future__ import annotations

from pathlib import Path

from app.agents.accounting.orchestrator import MuhasebeAgent
from app.agents.data_ingestion import _tablo_ekstresi
from app.services.accounting import guven

DEMO = Path(__file__).resolve().parents[2] / "demo" / "data" / "logo_tiger_2024.csv"


def _run(txs: list[dict]):
    return MuhasebeAgent(use_llm_fallback=False, regional_packs=["tr"]).run_sync("t", txs)


def test_every_entry_is_on_the_account_the_source_names():
    txs = _tablo_ekstresi(str(DEMO))
    sonuc = _run(txs)
    assert [k["thp_hesap_kodu"] for k in sonuc.yevmiye_kayitlari] == [t["account_code"] for t in txs]
    assert sonuc.dengeli


def test_the_bank_side_closes_at_the_files_running_balance():
    sonuc = _run(_tablo_ekstresi(str(DEMO)))
    assert sonuc.mizan["102"]["bakiye"] == 4_057_250_00


def test_only_the_policy_threshold_holds_source_coded_entries():
    txs = _tablo_ekstresi(str(DEMO))
    sonuc = _run(txs)
    held = [k for k in sonuc.yevmiye_kayitlari if k["onay_gerekli"]]
    assert len(held) == sum(1 for t in txs if abs(t["amount_cents"]) > 100_000_00) == 48
    assert {k["authority"]["matched_rule_id"] for k in held} == {"high_value"}


def test_a_correction_in_the_source_is_booked_the_other_way_round():
    sonuc = _run([{"id": "c1", "type": "income", "amount_cents": -50_000_00, "account_code": "600",
                   "description": "Satış iadesi", "transaction_date": "2024-03-01"}])
    satir_600 = next(s for s in sonuc.yevmiye_kayitlari[0]["satirlar"] if s["hesap_kodu"] == "600")
    assert (satir_600["borc"], satir_600["alacak"]) == (50_000_00, 0)


def test_a_row_without_a_code_is_still_classified_and_says_so():
    sonuc = _run([{"id": "k1", "type": "expense", "amount_cents": 28_500_00,
                   "description": "Ofis kirası Ocak", "transaction_date": "2024-01-05"}])
    kayit = sonuc.yevmiye_kayitlari[0]
    assert kayit["thp_hesap_kodu"] == "770"
    assert kayit["guven"]["seviye"] != guven.KAYNAK


def test_marketing_and_rnd_are_on_the_plans_accounts_not_transfer_accounts():
    """771/772 are the 770 group's transfer and variance accounts under 7/A."""
    sonuc = _run([
        {"id": "m", "type": "expense", "amount_cents": 18_500_00, "description": "Google Ads reklam harcaması",
         "transaction_date": "2024-01-18"},
        {"id": "r", "type": "expense", "amount_cents": 40_000_00, "description": "Ar-Ge prototip gideri",
         "transaction_date": "2024-01-20"},
    ])
    assert [k["thp_hesap_kodu"] for k in sonuc.yevmiye_kayitlari] == ["760", "750"]


def test_the_source_account_is_trusted_until_the_organisations_own_record_says_otherwise():
    assert guven.degerlendir(guven.KAYNAK, "kaynak hesap kodu 600").skor == 1.0
    kotu_gecmis = {guven.KAYNAK: (12, 25)}   # the SMMM corrected 13 of 25
    assert guven.degerlendir(guven.KAYNAK, "600", kotu_gecmis).skor < 0.8
