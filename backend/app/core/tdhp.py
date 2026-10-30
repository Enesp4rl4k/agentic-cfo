"""Tekdüzen Hesap Planı — what an account code says about a posting.

One map for every source that carries an account code: the e-Defter journal,
Logo/Mikro/Netsis exports, ERP pulls. When a source names the account, the
account decides the direction and whether the row is an income-statement event;
a keyword guess never overrides it (plan v8 §A1 — live audit 2026-10-24: the
"Hesap Kodu" column was never read and a salary row on a sales account became
revenue).

- Income accounts (60x, 64x, 67x) grow on the credit side; a debit is a
  correction. Sales deductions (61x) grow on the debit side and reduce revenue.
- Expense accounts (62x, 63x, 65x, 66x, 68x, 691, the 7/A cost accounts 7x0 and
  the 7/B accounts 790–797) grow on the debit side.
- Transfer (7x1 "yansıtma", 798/799) and closing (690, 692) postings move what
  is already counted; reading them would count it twice.
- Balance-sheet accounts (1xx–5xx) are not income-statement events. Cash still
  moves when a liability is paid, so those rows stay in the cash flow under a
  category the P&L does not read: `tax_payment` for tax and social-security
  accounts (KDV, stopaj, geçici vergi, SGK), `transfer` for the rest.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# account main-code prefix → category. Longest prefix wins.
GELIR: dict[str, str] = {
    "600": "revenue", "601": "revenue", "602": "revenue",
    "610": "revenue", "611": "revenue", "612": "revenue",   # deductions: reduce revenue
    "64": "other_income", "67": "other_income",
}
GIDER: dict[str, str] = {
    "62": "cogs",
    "630": "other_expense", "631": "marketing", "632": "other_expense",
    "65": "other_expense", "66": "other_expense", "68": "other_expense",
    "691": "tax",
    # 7/A cost accounts, before they are transferred into 6xx
    "710": "cogs", "720": "cogs", "730": "cogs", "740": "cogs",
    "750": "other_expense", "760": "marketing", "770": "other_expense", "780": "other_expense",
    # 7/B expense-by-nature accounts
    "790": "other_expense", "791": "other_expense", "792": "other_expense",
    "793": "other_expense", "794": "other_expense", "795": "other_expense",
    "796": "other_expense", "797": "other_expense",
}
# Sales deductions carry a debit balance: a debit reduces revenue.
GELIR_INDIRIMI = ("610", "611", "612")
# Postings to these are transfers or closings.
YANSITMA = ("711", "721", "731", "741", "751", "761", "771", "781", "798", "799")
KAPANIS = ("690", "692")
# KDV (190, 191, 391, 392), taxes and funds payable (360), SGK (361), deferred
# and prepaid tax (193, 368, 370, 371).
VERGI_BILANCO = ("190", "191", "193", "360", "361", "368", "370", "371", "391", "392")

# Categories the income statement does not read: the cash moved, the profit did not.
BILANCO_KATEGORILERI = frozenset({"tax_payment", "transfer"})

_KOD = re.compile(r"^\s*(\d{3})")


@dataclass(frozen=True)
class Hesap:
    kod: str        # three-digit main account, e.g. "600"
    rol: str        # gelir | gelir_indirimi | gider | bilanco | yansitma | kapanis
    kategori: str   # the account's category; for gider, the default when the nature is unknown


def ana_hesap(kod: str | None) -> str | None:
    """The three-digit main account of "600", "600.01.001" or "600 01"; None if unreadable."""
    m = _KOD.match(kod or "")
    return m.group(1) if m else None


def eslestir(kod: str, tablo: dict[str, str]) -> str | None:
    for uzunluk in (3, 2):
        kategori = tablo.get(kod[:uzunluk])
        if kategori is not None:
            return kategori
    return None


def hesap(kod: str | None) -> Hesap | None:
    """What the account is. None for an unreadable code or an income-statement
    account this map does not know — those are reported, never guessed."""
    ana = ana_hesap(kod)
    if ana is None:
        return None
    if ana in YANSITMA:
        return Hesap(ana, "yansitma", "transfer")
    if ana in KAPANIS:
        return Hesap(ana, "kapanis", "transfer")
    if ana[0] in "12345":
        return Hesap(ana, "bilanco", "tax_payment" if ana in VERGI_BILANCO else "transfer")
    gelir = eslestir(ana, GELIR)
    if gelir is not None:
        return Hesap(ana, "gelir_indirimi" if ana in GELIR_INDIRIMI else "gelir", gelir)
    gider = eslestir(ana, GIDER)
    if gider is not None:
        return Hesap(ana, "gider", gider)
    return None


def hareket(h: Hesap, borc_kurus: int, alacak_kurus: int) -> tuple[str, int] | None:
    """(type, signed amount in kuruş) of one posting; None when it must not be read.

    Income and expense rows keep a correction's sign (a debit on a sales account
    reduces revenue), as the e-Defter journal reader does. A balance-sheet row
    is the cash side of a single-entry listing: a debit (a liability paid) is
    money out, a credit money in.
    """
    if h.rol in ("yansitma", "kapanis"):
        return None
    if h.rol in ("gelir", "gelir_indirimi"):
        return "income", alacak_kurus - borc_kurus
    if h.rol == "gider":
        return "expense", borc_kurus - alacak_kurus
    net = borc_kurus - alacak_kurus
    return ("expense", net) if net >= 0 else ("income", -net)
