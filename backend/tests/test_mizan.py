"""SMMM M2: a trial balance (mizan) is recognised, checked and previewed.

Owner's scope (2026-11-14): recognise it, validate it, show what it says —
and do NOT write it to the ledger. A mizan is a snapshot of balances, usually
cumulative from 1 January, and counting one as movements would double-count the
months before it. Landing it waits for a real sample from a pilot accountant.

FIXTURES ARE HAND-WRITTEN from the layouts accounting packages are known to
export, not real exports. A fixture written against the parser cannot fail, so
these prove the logic (columns, units, hierarchy, the balance check), not that a
particular package's file will be read. See memory: authority-published corpora.
"""

from __future__ import annotations

import pytest

from app.services.ingest.mizan import mizan_oku
from app.services.ingest.recognize import KESIN, tani
from app.services.ingest.table import satirlari_oku, tabloyu_bul

LOGO = (
    "ÖRNEK GIDA SAN. TİC. A.Ş.\n"
    "01.01.2026 - 31.03.2026 MİZAN\n"
    "\n"
    "Hesap Kodu;Hesap Adı;Borç;Alacak;Borç Bakiye;Alacak Bakiye\n"
    "100;KASA;125.000,00;100.000,00;25.000,00;0,00\n"
    "102;BANKALAR;900.000,00;600.000,00;300.000,00;0,00\n"
    "320;SATICILAR;400.000,00;700.000,00;0,00;300.000,00\n"
    "500;SERMAYE;0,00;50.000,00;0,00;50.000,00\n"
    "600;YURT İÇİ SATIŞLAR;0,00;800.000,00;0,00;800.000,00\n"
    "621;SATILAN TİCARİ MAL MALİYETİ;520.000,00;0,00;520.000,00;0,00\n"
    "770;GENEL YÖNETİM GİDERLERİ;305.000,00;0,00;305.000,00;0,00\n"
    "TOPLAM;;2.250.000,00;2.250.000,00;1.150.000,00;1.150.000,00\n"
)


def _tablo(metin: str, ad: str = "mizan.csv"):
    from app.services.ingest.recognize import BILINEN

    (sayfa,) = satirlari_oku(metin.encode("cp1254", errors="replace"), "csv")
    return tabloyu_bul(sayfa[1], BILINEN, sayfa=sayfa[0])


def test_a_logo_style_mizan_is_recognised_as_a_trial_balance():
    t = tani(LOGO.encode("cp1254"), "mizan.csv")
    assert t.durum == KESIN and t.tur == "trial_balance" and t.alan == "cfo"


def test_a_bank_statement_is_not_mistaken_for_a_mizan():
    banka = (
        "Tarih;Açıklama;Borç;Alacak;Bakiye\n"
        "05.01.2026;Kira ödemesi;10.000,00;0,00;90.000,00\n"
        "06.01.2026;Müşteri tahsilat;0,00;5.000,00;95.000,00\n"
    )
    t = tani(banka.encode("cp1254"), "ekstre.csv")
    assert t.tur == "bank_statement"


def test_reads_accounts_totals_and_checks_the_books_balance():
    m = mizan_oku(_tablo(LOGO))
    assert len(m.hesaplar) == 7
    assert m.toplam_borc_kurus == 2_250_000_00 and m.toplam_alacak_kurus == 2_250_000_00
    assert m.dengeli and m.bakiye_dengeli
    kasa = next(h for h in m.hesaplar if h.kod == "100")
    assert (kasa.borc_kurus, kasa.alacak_kurus, kasa.borc_bakiye_kurus) == (125_000_00, 100_000_00, 25_000_00)


def test_the_income_statement_side_comes_from_the_account_roles():
    g = mizan_oku(_tablo(LOGO)).gelir_tablosu
    assert g["gelir_kurus"] == 800_000_00
    assert g["gider_kurus"] == 520_000_00 + 305_000_00
    assert g["net_kurus"] == 800_000_00 - 825_000_00  # a loss, said as one


def test_an_unbalanced_mizan_is_reported_not_smoothed_over():
    bozuk = LOGO.replace("125.000,00;100.000,00;25.000,00", "125.000,00;99.000,00;26.000,00")
    m = mizan_oku(_tablo(bozuk))
    assert not m.dengeli
    assert m.fark_kurus == 1_000_00  # the amount, so the accountant can find it
    assert any("denge" in u.lower() for u in m.uyarilar)


def test_parent_rows_are_not_counted_with_their_children():
    hiyerarsi = (
        "Hesap Kodu;Hesap Adı;Borç;Alacak\n"
        "100;KASA;30.000,00;0,00\n"
        "100.01;MERKEZ KASA;20.000,00;0,00\n"
        "100.02;ŞUBE KASA;10.000,00;0,00\n"
        "600;SATIŞLAR;0,00;30.000,00\n"
    )
    m = mizan_oku(_tablo(hiyerarsi))
    assert [h.kod for h in m.hesaplar] == ["100.01", "100.02", "600"]
    assert m.ust_hesap_atlanan == 1
    assert m.toplam_borc_kurus == 30_000_00 and m.dengeli


def test_a_prefix_that_is_not_a_parent_is_kept():
    # 10001 starts with "100" but its amounts are not the sum of anything under 100:
    # two separate accounts, both counted. The parent rule is read from the numbers.
    veri = (
        "Hesap Kodu;Hesap Adı;Borç;Alacak\n"
        "100;KASA;5.000,00;0,00\n"
        "10001;BAŞKA HESAP;7.000,00;0,00\n"
        "600;SATIŞLAR;0,00;12.000,00\n"
    )
    m = mizan_oku(_tablo(veri))
    assert [h.kod for h in m.hesaplar] == ["100", "10001", "600"]
    assert m.ust_hesap_atlanan == 0 and m.toplam_borc_kurus == 12_000_00 and m.dengeli


def test_amounts_are_integer_kurus_whatever_the_decimal_style():
    veri = "Hesap Kodu;Hesap Adı;Borç;Alacak\n102;BANKA;1.234.567,89;0,00\n600;SATIŞ;0,00;1.234.567,89\n"
    m = mizan_oku(_tablo(veri))
    assert m.hesaplar[0].borc_kurus == 123_456_789 and isinstance(m.hesaplar[0].borc_kurus, int)


def test_an_income_account_the_map_does_not_know_is_listed_not_guessed():
    veri = (
        "Hesap Kodu;Hesap Adı;Borç;Alacak\n"
        "102;BANKA;100,00;0,00\n"
        "690;GARİP HESAP;0,00;100,00\n"
        "600;SATIŞ;0,00;0,00\n"
    )
    m = mizan_oku(_tablo(veri))
    assert m.gelir_tablosu["gelir_kurus"] == 0  # 690 is a closing account, never read as revenue


def test_the_period_is_not_invented():
    m = mizan_oku(_tablo(LOGO))
    assert m.donem is None and any("dönem" in u.lower() for u in m.uyarilar)


# ── through the door the page and the inbox use ─────────────────────────────

@pytest.mark.asyncio
async def test_the_ingest_door_previews_a_mizan_and_starts_no_analysis(client):
    from sqlalchemy import func, select

    from app.models.analysis_job import AnalysisJob
    from app.services.ingest.ekle import Sahip, dosyalari_ekle

    async with client._maker() as db:
        out = await dosyalari_ekle(db, Sahip(None, None), [("mizan.csv", LOGO.encode("cp1254"))])
        n = (await db.execute(select(func.count()).select_from(AnalysisJob))).scalar_one()

    (d,) = out["dosyalar"]
    assert d["durum"] == "onizleme" and out["job_id"] is None and n == 0
    assert "deftere işlenmedi" in d["mesaj"]
    assert d["mizan"]["dengeli"] is True and d["mizan"]["hesap_sayisi"] == 7
