"""Golden THP classification cases.

Ground truth is the Turkish uniform chart of accounts (Tekdüzen Hesap Planı),
not the classifier's current output. Each expectation below was written from the
accounting rule first and only then run — three of the first fourteen came back
wrong, and all three were defects in the classifier rather than in the
expectation:

  * "SGK primi ödemesi" landed in 360 (Ödenecek Vergi ve Fonlar) because `sgk`
    was listed as a keyword on *both* 360 and 361; the tie was broken by dict
    insertion order. A social-security withholding booked as a tax is a real
    misstatement — different balance-sheet line, different declaration.
  * "Banka kredi faizi gideri" landed in 102 (Bankalar) because scores were
    summed across keywords, so 102 counted both "banka" and "bank" against the
    same words and beat 657's specific "kredi faiz".
  * "Müşteri tahsilatı havale" landed in 102 as well. `double_entry` already
    supplies the cash side of every entry, so a classifier that answers 102
    produces a 102/102 entry. Payment-instrument words ("havale", "eft") name
    how money moved, not what to book against.

Writing these by copying the classifier's output would have preserved all three.

Only the rule engine is exercised: the LLM path needs a live key and would make
the eval non-deterministic. Cases are therefore phrased the way a Turkish bank
statement or invoice line actually reads.
"""
from __future__ import annotations

# (description, transaction_type, expected THP account, why)
THP_GOLDEN_CASES: list[tuple[str, str, str, str]] = [
    # ── Personnel ─────────────────────────────────────────────────────────────
    ("Ocak ayi personel maas odemesi", "expense", "730",
     "Ücret gideri personel hesabına"),
    ("SGK primi odemesi", "expense", "361",
     "Sosyal güvenlik kesintisi 361'e; 360 vergi hesabıdır"),

    # ── Operating expenses ────────────────────────────────────────────────────
    ("Ofis kira odemesi", "expense", "770",
     "Kira genel yönetim gideri"),
    ("Elektrik faturasi odemesi", "expense", "770",
     "Genel yönetim gideri"),
    ("Google Ads reklam harcamasi", "expense", "771",
     "Reklam pazarlama-satış-dağıtım giderine"),
    ("Ar-Ge prototip gideri", "expense", "772",
     "Ar-Ge ayrı bir gider hesabıdır"),

    # ── Taxes ─────────────────────────────────────────────────────────────────
    ("KDV beyannamesi odemesi", "expense", "360",
     "Ödenecek vergi ve fonlar"),

    # ── Financing ─────────────────────────────────────────────────────────────
    ("Banka kredi faizi gideri", "expense", "657",
     "Faiz gideri; 102 Bankalar bir varlık hesabıdır"),

    # ── Assets ────────────────────────────────────────────────────────────────
    ("Bilgisayar alimi demirbas", "expense", "255",
     "Demirbaş, gider değil duran varlık"),
    ("Yazilim lisans bedeli", "expense", "260",
     "Lisans bir haktır"),
    ("Ticari mal alisi stok girisi", "expense", "153",
     "Stok girişi"),

    # ── Revenue ───────────────────────────────────────────────────────────────
    ("Yurt ici satis faturasi", "income", "600",
     "Yurt içi satış"),
    ("Ihracat bedeli doviz geliri", "income", "601",
     "İhracat yurt dışı satışa"),
    ("Musteri tahsilati havale", "income", "120",
     "Tahsilat alacağı azaltır; gelir fatura kesildiğinde tanınmıştı"),

    # ── Direction ─────────────────────────────────────────────────────────────
    # Both came from a live run on the TechNova fixture. The classifier ignored
    # which way the money moved and let one keyword decide.
    ("Ocak Yazılım Lisans Geliri - ABC Holding", "income", "600",
     "Lisans *geliri* hasılattır; 260 Haklar bir varlık alımıdır, gelir değil"),
    ("Ocak Maaş Ödemeleri - Satış Ekibi", "expense", "730",
     "Satış ekibinin maaşı bir giderdir; çıkan para 600 hasılata yazılamaz"),
]

# Accounts `double_entry` supplies structurally as the cash side of every entry.
# The classifier must never return one: doing so yields a 102/102 entry that
# balances and means nothing.
COUNTER_ACCOUNTS = frozenset({"100", "102"})
