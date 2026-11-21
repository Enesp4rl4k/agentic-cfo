"""Which way did the money go? One answer for every statement the pipeline reads.

A bank export says it in one of four ways, and the order below is the order of
trust. Nothing here ever defaults to income: a row nobody could place is held.

  (a) separate debit / credit columns ("Borç"/"Alacak", "Çıkan"/"Giren",
      "Ödeme"/"Tahsilat", "Debit"/"Credit", "Withdrawal"/"Deposit" ...): the
      column that is filled is the direction. Blank and "0,00" are empty. A row
      with both filled is held.
  (b) a direction column ("B/A", "Borç/Alacak", "D/C", "İşlem Tipi", "Tür",
      "Tip"): its value is the direction. A value that is not one of the
      vocabulary below is held; a column none of whose values is, is not a
      direction column (an "İşlem Tipi" of EFT/HAVALE/POS).
  (c) the sign of ONE amount column, but only when the sign is informative for
      this file: some amounts are negative (or written in accounting negative
      notation). A column of all-positive numbers says nothing.
  (d) otherwise the row is held "yön belirsiz".

A running balance column is evidence stronger than any of them, because it is
arithmetic: when the balance goes down by the amount, the money left. It
VERIFIES (a)-(c) -- "Borç/Alacak" is the customer's view in some exports and the
bank's in others -- and when nothing else says anything it can READ the
direction. A file whose balance contradicts its mapping is held whole, with the
reason, instead of being booked backwards. A file nothing can place is held
whole too: one question for the file, not one per row.

Pure functions, no I/O: this module is imported by the table reader, the bank
text parsers' post-processing and the tests.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.core.turkish import fold

INCOME = "income"
EXPENSE = "expense"

# Why a whole file waits (the reason codes of `direction_file`).
NO_SIGNAL = "no_signal"
BALANCE_CONTRADICTS = "balance_contradicts"

# ── money ────────────────────────────────────────────────────────────────────

_CURRENCY_TOKEN = re.compile(r"(?<![^\W\d_])(?:tl|try|trl|usd|eur|gbp)(?![^\W\d_])|[₺$€£]", re.IGNORECASE)


def parse_money(raw: Any) -> tuple[int, bool] | None:
    """(magnitude in kuruş, written negative) of an amount cell; None when it holds no number.

    "1.234,56", "-1.234,56", "1.234,56-", "(1.234,56)", "1,234.56", "₺1.234,56",
    "1.234,56 TL", "1234.56", "1.234" (Turkish thousands), "500,00 TL-".
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return round(abs(raw) * 100), raw < 0
    text = str(raw).replace("\xa0", " ").replace("−", "-").replace("–", "-").strip()
    if not text:
        return None
    text = _CURRENCY_TOKEN.sub("", text).strip()
    negative = text.startswith("-") or text.endswith("-") or (text.startswith("(") and text.endswith(")"))
    digits = re.sub(r"[^\d,.]", "", text)
    if not re.search(r"\d", digits):
        return None
    if "," in digits and "." in digits:
        if digits.rfind(",") > digits.rfind("."):
            digits = digits.replace(".", "").replace(",", ".")
        else:
            digits = digits.replace(",", "")
    elif "," in digits:
        parts = digits.split(",")
        thousands = len(parts) > 2 or (len(parts[1]) == 3 and 1 <= len(parts[0]) <= 3)
        digits = digits.replace(",", "") if thousands else digits.replace(",", ".")
    elif "." in digits:
        parts = digits.split(".")
        thousands = len(parts) > 2 or (len(parts[1]) == 3 and 1 <= len(parts[0]) <= 3)
        if thousands:
            digits = digits.replace(".", "")
    try:
        cents = int((Decimal(digits) * 100).to_integral_value(ROUND_HALF_UP))
    except ArithmeticError:
        return None
    return cents, negative


def signed_money(raw: Any) -> int | None:
    """A balance cell: signed kuruş."""
    m = parse_money(raw)
    return None if m is None else (-m[0] if m[1] else m[0])


# ── headers ──────────────────────────────────────────────────────────────────

def norm_header(header: str | None) -> str:
    """A header folded to comparable words: "Borç Tutarı (TL)" -> "borc tutari"; "B/A" -> "b a"."""
    text = re.sub(r"\(.*?\)|\[.*?\]", " ", fold(header))
    words = re.sub(r"[^a-z0-9]+", " ", text).split()
    return " ".join(w for w in words if w not in {"tl", "try", "trl", "usd", "eur", "gbp"})


_DEBIT = frozenset({
    "borc", "borc tutari", "borc tutar", "borclu", "cikan", "cikan tutar", "cikan tutari", "giden", "giden tutar",
    "odeme", "odemeler", "odeme tutari", "cikis", "cikis tutari", "para cikisi", "gider",
    "debit", "debit amount", "debits", "withdrawal", "withdrawals", "dr",
})
_CREDIT = frozenset({
    "alacak", "alacak tutari", "alacak tutar", "alacakli", "giren", "giren tutar", "giren tutari", "gelen", "gelen tutar",
    "tahsilat", "tahsilatlar", "tahsilat tutari", "giris", "giris tutari", "para girisi", "gelir",
    "credit", "credit amount", "credits", "deposit", "deposits", "cr",
})
_AMOUNT = frozenset({"tutar", "amount", "islem tutari", "hareket tutari", "miktar", "tutar tl"})
_BALANCE = frozenset({"bakiye", "balance", "kalan bakiye", "hesap bakiyesi", "running balance"})
_DIRECTION = frozenset({
    "b a", "a b", "borc alacak", "alacak borc", "d c", "c d", "dc", "islem tipi", "islem turu", "hareket tipi",
    "hareket turu", "tur", "tip", "type", "borc alacak durumu", "yon",
})
_DATE = frozenset({"tarih", "date", "islem tarihi", "transaction date", "valor"})
_DESCRIPTION = frozenset({"aciklama", "description", "detay", "islem aciklamasi", "aciklama detayi"})

AMOUNT_COLUMNS = _DEBIT | _CREDIT | _AMOUNT   # any of them makes a table a statement


def is_statement_header(headers: list[str]) -> bool:
    """A header row with a date and something that can carry an amount."""
    names = {norm_header(h) for h in headers if h}
    return bool(names & AMOUNT_COLUMNS) and bool(names & (_DATE | {"islem tarihi"}))


_OUT_VALUES = frozenset({
    "b", "borc", "borclu", "debit", "d", "dr", "cikis", "cikan", "odeme", "gider", "expense", "withdrawal", "giden",
    "para cikisi",
})
_IN_VALUES = frozenset({
    "a", "alacak", "alacakli", "credit", "c", "cr", "giris", "giren", "tahsilat", "gelir", "income", "deposit",
    "gelen", "para girisi",
})
_LEADING_WORDS = {"borc": EXPENSE, "alacak": INCOME, "debit": EXPENSE, "credit": INCOME}


def value_direction(raw: Any) -> str | None:
    """"B"/"Borç"/"Debit"/"Çıkış"/"Ödeme" -> expense; "A"/"Alacak"/"Credit"/"Giriş"/"Tahsilat" -> income."""
    v = norm_header(str(raw or ""))
    if not v:
        return None
    if v in _OUT_VALUES:
        return EXPENSE
    if v in _IN_VALUES:
        return INCOME
    return _LEADING_WORDS.get(v.split()[0]) if len(v.split()) > 1 else None


def header_signature(headers: list[str]) -> str:
    """The identity of a file's layout: its header words, in order. Same bank format, same signature."""
    material = "|".join(norm_header(h) for h in headers if h and h.strip())
    return hashlib.sha256(material.encode()).hexdigest()[:24]


# ── per-file resolution ──────────────────────────────────────────────────────

@dataclass
class RowDirection:
    type: str | None          # what the row is booked as; None = held
    amount_cents: int | None  # magnitude; None = unreadable
    read: str | None = None   # what the file's columns said (kept when a file is held whole)
    balance: str | None = None  # what the balance column says, when it was checked
    note: str = ""


@dataclass
class FileDirection:
    rows: list[RowDirection]
    notes: list[str] = field(default_factory=list)
    # Set when the file as a whole cannot be placed: {reason, signature, question}.
    hold: dict[str, Any] | None = None


def _roles(headers: list[str]) -> dict[str, str]:
    """role -> the header (as written) that plays it; the first of each."""
    tables = (("debit", _DEBIT), ("credit", _CREDIT), ("amount", _AMOUNT), ("balance", _BALANCE),
              ("direction", _DIRECTION), ("date", _DATE), ("description", _DESCRIPTION))
    roles: dict[str, str] = {}
    for h in headers:
        key = norm_header(h)
        for role, names in tables:
            if key in names and role not in roles:
                roles[role] = h
                break
    return roles


def _filled(cell: Any) -> tuple[int, bool] | None:
    """The cell's amount when it holds one that is not zero; blank and "0,00" are empty."""
    m = parse_money(cell)
    return m if m is not None and m[0] != 0 else None


def _flip(direction: str | None) -> str | None:
    return None if direction is None else (EXPENSE if direction == INCOME else INCOME)


def _chain(mags: list[int | None], dirs: list[str | None], bals: list[int | None]) -> tuple[int, int, int, bool]:
    """Compare balance movements with the amounts: (matches, inverted matches, checked pairs, newest_first)."""
    best = (0, 0, 0, False)
    for newest_first in (False, True):
        m = inv = total = 0
        for i in range(1, len(mags)):
            later, earlier = (i, i - 1) if not newest_first else (i - 1, i)
            mag, now, before = mags[later], bals[later], bals[earlier]
            if now is None or before is None or mag is None or dirs[later] is None:
                continue
            delta = now - before
            expected = mag if dirs[later] == INCOME else -mag
            total += 1
            m += delta == expected
            inv += delta == -expected
        if m + inv > best[0] + best[1]:
            best = (m, inv, total, newest_first)
    return best


def verdict(mags: list[int | None], dirs: list[str | None], bals: list[int | None]) -> str:
    """confirmed | inverted | inconclusive | unverified: does the balance agree with the directions read?"""
    m, inv, total, _ = _chain(mags, dirs, bals)
    if total < 2:
        return "unverified"
    if m / total >= 0.9:
        return "confirmed"
    if inv / total >= 0.9 and m / total < 0.5:
        return "inverted"
    return "inconclusive"


def _from_balance(mags: list[int | None], bals: list[int | None]) -> list[str | None] | None:
    """Directions read off the balance alone: every step must equal its amount, in exactly one order."""
    scored: list[tuple[int, int, list[str | None]]] = []
    for newest_first in (False, True):
        out: list[str | None] = [None] * len(mags)
        hits = total = 0
        for i in range(1, len(mags)):
            later, earlier = (i, i - 1) if not newest_first else (i - 1, i)
            mag, now, before = mags[later], bals[later], bals[earlier]
            if now is None or before is None or mag is None:
                continue
            delta = now - before
            total += 1
            if mag and abs(delta) == mag:
                hits += 1
                out[later] = INCOME if delta > 0 else EXPENSE
        scored.append((hits, total, out))
    (h0, t0, o0), (h1, t1, o1) = scored
    best_hits, best_total, best = (h0, t0, o0) if h0 >= h1 else (h1, t1, o1)
    other = min(h0, h1)
    if best_total >= 2 and best_hits / best_total >= 0.9 and best_hits > other:
        return best
    return None


def _question(
    headers: list[str], roles: dict[str, str], rows: list[dict[str, str]], reason: str, note: str,
) -> dict[str, Any]:
    labels = {v: k for k, v in roles.items()}
    columns = [{"name": h, "role": labels.get(h)} for h in headers if h and h.strip()]
    shown = [r for r in ("date", "description", "amount", "debit", "credit", "direction", "balance") if r in roles]
    samples = [{r: str(row.get(roles[r], "")).strip() for r in shown} for row in rows[:3]]
    return {"reason": reason, "columns": columns, "samples": samples, "note": note}


def resolve_file(headers: list[str], rows: list[dict[str, str]]) -> FileDirection:
    """Direction and amount of every row of one statement table, by the precedence in the module doc."""
    roles = _roles(headers)
    # (b) of the module doc: of the columns that could be a direction column, the one that speaks the vocabulary.
    roles.pop("direction", None)
    direction_column, best = None, 0.0
    for h in (h for h in headers if norm_header(h) in _DIRECTION):
        cells = [c for c in (str(r.get(h, "")).strip() for r in rows) if c]
        ratio = sum(value_direction(c) is not None for c in cells) / len(cells) if cells else 0.0
        if ratio >= 0.5 and ratio > best:
            direction_column, best = h, ratio
    if direction_column:
        roles["direction"] = direction_column
    # Both columns, or the one a file has when it has no amount column at all (a payments list).
    split = ("debit" in roles and "credit" in roles) or (
        ("debit" in roles) != ("credit" in roles) and "amount" not in roles
    )
    n = len(rows)
    mags: list[int | None] = [None] * n
    reads: list[str | None] = [None] * n
    notes_per_row = [""] * n
    negative = [False] * n
    via_amount = [False] * n
    column_values: list[str | None] = [None] * n

    for i, row in enumerate(rows):
        if split:
            d, c = _filled(row.get(roles.get("debit", ""))), _filled(row.get(roles.get("credit", "")))
            if d and c:
                notes_per_row[i] = "borç ve alacak sütunlarının ikisi de dolu"
                continue
            if d or c:
                mags[i], reads[i] = (d or c)[0], EXPENSE if d else INCOME  # type: ignore[index]
                continue
        if "amount" in roles:
            cell = str(row.get(roles["amount"], "")).strip()
            m = parse_money(cell)
            if m is not None:
                mags[i], negative[i], via_amount[i] = m[0], m[1], True
        if direction_column:
            column_values[i] = str(row.get(direction_column, "")).strip()

    # (c) the sign, if this file's signs vary
    sign_informative = any(neg and mags[i] for i, neg in enumerate(negative) if via_amount[i])

    for i in range(n):
        if reads[i] is not None or (mags[i] is None and not via_amount[i] and not column_values[i]):
            continue
        if notes_per_row[i]:
            continue
        said = value_direction(column_values[i]) if direction_column and column_values[i] else None
        if direction_column and column_values[i] and said is None:
            notes_per_row[i] = f"yön değeri tanınmadı: {column_values[i]}"
            continue
        if said is not None:
            reads[i] = said
        elif sign_informative and via_amount[i]:
            reads[i] = EXPENSE if negative[i] else INCOME

    bals: list[int | None] = [signed_money(r.get(roles["balance"])) if "balance" in roles else None for r in rows]
    has_signal = split or direction_column is not None or sign_informative
    out_notes: list[str] = []
    balance_dirs: list[str | None] = [None] * n

    if not any(reads) and not has_signal:
        derived = _from_balance(mags, bals)
        if derived is not None:
            reads = derived
            out_notes.append("yön, bakiye hareketinden okundu")
            for i in range(n):
                if reads[i] is None:
                    notes_per_row[i] = "bakiye zincirinin ilk satırı: yön okunamadı"
        else:
            hold = {"reason": NO_SIGNAL, "signature": header_signature(headers),
                    "question": _question(headers, roles, rows, NO_SIGNAL,
                                          "Tutarların yönünü gösteren bir sütun ya da işaret bulunamadı.")}
            return FileDirection([RowDirection(None, mags[i], None, None, "") for i in range(n)],
                                 ["yön belirsiz: dosya tek soruyla bekliyor"], hold)

    state = verdict(mags, reads, bals)
    if state == "inverted":
        balance_dirs = [_flip(r) for r in reads]
        hold = {"reason": BALANCE_CONTRADICTS, "signature": header_signature(headers),
                "question": _question(headers, roles, rows, BALANCE_CONTRADICTS,
                                      "Bakiye hareketi, sütunlardan okunan yönün tersini gösteriyor.")}
        return FileDirection(
            [RowDirection(None, mags[i], reads[i], balance_dirs[i], notes_per_row[i]) for i in range(n)],
            ["yön, bakiyeyle çelişiyor: dosya tek soruyla bekliyor"], hold,
        )
    if state == "confirmed":
        out_notes.append("yön bakiye hareketiyle doğrulandı")
    elif state == "inconclusive":
        out_notes.append("yön bakiyeyle tam doğrulanamadı")
    else:
        out_notes.append("yön doğrulanmadı (bakiye sütunu yok ya da yetersiz)")
    return FileDirection([RowDirection(reads[i], mags[i], reads[i], None, notes_per_row[i]) for i in range(n)], out_notes)


def settle_rows(rows: list[dict[str, Any]], signature_material: str) -> dict[str, Any] | None:
    """The same checks for rows a text parser already read (type, amount_cents, balance_cents).

    Mutates `rows` when the file is held whole (every `type` cleared, `direction_file` set by the
    caller) and returns the hold; returns None otherwise. A row a parser could not place has
    type None/"" and stays held on its own; a statement where none was placed is held whole.
    """
    mags = [r.get("amount_cents") for r in rows]
    reads: list[str | None] = [r["type"] if r.get("type") in (INCOME, EXPENSE) else None for r in rows]
    bals = [r.get("balance_cents") for r in rows]
    signature = hashlib.sha256(signature_material.encode()).hexdigest()[:24]
    samples = [{"description": str(r.get("description", "")), "amount": str(r.get("amount_cents"))} for r in rows[:3]]

    def hold(reason: str, note: str) -> dict[str, Any]:
        return {"signature": signature, "reason": reason,
                "question": {"columns": [], "samples": samples, "reason": reason, "note": note}}

    if rows and not any(reads):
        derived = _from_balance(mags, bals)
        if derived is None:
            return hold(NO_SIGNAL, "Tutarların yönünü gösteren bir sütun ya da işaret bulunamadı.")
        for r, d in zip(rows, derived, strict=True):
            r["type"] = d
        return None
    if verdict(mags, reads, bals) == "inverted":
        for r, d in zip(rows, reads, strict=True):
            r["direction_read"], r["direction_balance"], r["type"] = d, _flip(d), None
        return hold(BALANCE_CONTRADICTS, "Bakiye hareketi, okunan yönün tersini gösteriyor.")
    return None
