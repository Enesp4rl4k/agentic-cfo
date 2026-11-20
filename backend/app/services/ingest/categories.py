"""Transaction categories: keyword rules, the account-code bridge and the type/category check.

Moved out of app/agents/data_ingestion.py unchanged (plan v11 A0.3); that module
re-exports what its callers import from it.
"""

from __future__ import annotations

from typing import Any

from app.core import tdhp
from app.core.turkish import fold

# Category keywords ordered by SPECIFICITY (most specific first wins on tie).
# Each entry: (category, keywords, priority)
# Higher priority = wins when multiple categories match.
_CATEGORY_RULES: list[tuple[str, list[str], int]] = [
    # ── Income ────────────────────────────────────────────────────────────────
    ("revenue",       ["sales invoice", "payment received", "customer payment",
                       "invoice issued", "gelir", "satış", "tahsilat",
                       "sales", "income", "revenue"],                           90),
    ("other_income",  ["other income", "diğer gelir", "grant", "refund received"], 85),
    # ── COGS ──────────────────────────────────────────────────────────────────
    ("cogs",          ["raw material", "hammadde", "goods purchased",
                       "product cost", "manufacturing", "inventory",
                       "mal alımı", "stok alımı"],                              80),
    # ── Payroll ───────────────────────────────────────────────────────────────
    ("salary",        ["salary", "payroll", "maaş", "ücret", "sigorta",
                       "wages", "employee", "social security",
                       "sgk", "personel", "staff",
                       # a bonus or severance is pay: "Yıl Sonu Prim" fell to
                       # its sales account's default, marketing
                       "prim", "ikramiye", "kıdem", "bonus"],                   75),
    # ── KDV ── collected for the state and paid over: cash, not profit, for a
    # KDV-registered company. Above "tax", which would put it under EBITDA.
    ("tax_payment",   ["kdv", "katma değer vergisi", "vat payment", "vat"],     74),
    # ── Tax ── (before "loan" to avoid confusing withholding with bank payment)
    ("tax",           ["stopaj", "kurumlar vergisi", "gelir vergisi",
                       "withholding", "corporate tax", "income tax",
                       "tax payment", "vergi"],                                 73),
    # ── Loan / Finance ────────────────────────────────────────────────────────
    ("loan",          ["kredi ödemesi", "taksit", "loan repayment",
                       "debt payment", "faiz", "interest payment",
                       "installment", "loan", "debt", "credit",
                       "bank loan"],                                             70),
    # ── Rent ──────────────────────────────────────────────────────────────────
    ("rent",          ["kira", "office rent", "rent payment",
                       "lease payment", "rent", "lease"],                       65),
    # ── Utilities ─────────────────────────────────────────────────────────────
    # Not bare "fatura": every bill is a fatura, and "AWS ... Faturası"
    # became a utility, out-ranking "aws".
    ("utilities",     ["elektrik", "su faturası", "doğalgaz",
                       "electricity", "water bill", "gas bill",
                       "internet", "phone", "telecom", "utilities"],           60),
    # ── Marketing ─────────────────────────────────────────────────────────────
    ("marketing",     ["google ads", "meta ads", "facebook ads", "reklam",
                       "advertising", "marketing", "social media",
                       "campaign", "dijital reklam"],                           55),
    # ── Technology ────────────────────────────────────────────────────────────
    ("technology",    ["aws", "azure", "google cloud", "digitalocean",
                       "github", "jira", "figma", "saas",
                       "software license", "server", "cloud",
                       "subscription", "license", "yazılım"],                  50),
    # ── Other expense fallback ────────────────────────────────────────────────
    ("other_expense", [],                                                       0),
    # ── Balance-sheet movement; only an account code or a person sets it ─────
    ("transfer",      [],                                                       0),
]


# Build a fast lookup: category → (keywords, priority)
_CATEGORY_MAP: list[tuple[str, list[str], int]] = [
    (cat, kws, pri) for cat, kws, pri in _CATEGORY_RULES if kws
]


# Public alias for tests / callers that still import CATEGORY_KEYWORDS.
CATEGORY_KEYWORDS: dict[str, list[str]] = {cat: list(kws) for cat, kws, _pri in _CATEGORY_RULES}


# The categories anything downstream knows how to group by. A row carrying
# anything else is invisible to every report that groups on category, and
# nothing complains — so a category read off a file has to be checked against
# this before it is believed.
KNOWN_CATEGORIES: frozenset[str] = frozenset(cat for cat, _kw, _pri in _CATEGORY_RULES)


INCOME_CATEGORIES: frozenset[str] = frozenset({"revenue", "other_income"})


def _yonle_uyumlu(category: str, tx_type: str | None) -> bool:
    """A P&L category belongs to one direction; a balance-sheet one to either
    (a KDV refund comes in, a KDV payment goes out)."""
    if tx_type is None or category in tdhp.BILANCO_KATEGORILERI:
        return True
    return (category in INCOME_CATEGORIES) == (tx_type == "income")


def _guess_category(description: str, tx_type: str | None = None) -> str:
    """
    Match description against CATEGORY_RULES using keyword matching.

    When multiple categories match, the one with the highest priority wins.
    This prevents "bank payment" (loan) from beating "salary" (payroll)
    just because it appears first in a naive loop.

    Given the row's direction, only a category of that direction can win:
    "Satış Ekibi Maaşı" is money out, and "satış" (revenue, the highest
    priority) used to take it out of every expense line of the P&L.
    """
    fallback = "revenue" if tx_type == "income" else "other_expense"
    if not description:
        return fallback
    # Folded on both sides: statements write "maas" and "dogalgaz" at least as
    # often as "maaş" and "doğalgaz".
    desc_lower = fold(description)
    best_category = fallback
    best_priority = -1

    for category, keywords, priority in _CATEGORY_MAP:
        if not _yonle_uyumlu(category, tx_type):
            continue
        if priority <= best_priority:
            continue  # can't beat current winner even if matched
        if any(fold(kw) in desc_lower for kw in keywords):
            best_category = category
            best_priority = priority

    return best_category


def tur_kategori_celiskisi(txs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows whose category belongs to the other direction.

    An expense row filed under "revenue" is in no expense line of the P&L and
    in no revenue line either — it vanished from the statement without a word.
    """
    return [
        t for t in txs
        if t.get("category") in KNOWN_CATEGORIES
        and not _yonle_uyumlu(str(t.get("category")), str(t.get("type")))
    ]
