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
# The balance reconciles only part of the rows: neither confirmed nor contradicted.
BALANCE_INCONCLUSIVE = "balance_inconclusive"
# A direction from a debit/credit word (the bank's book or the customer's?) that no balance can verify.
CONVENTION_UNVERIFIED = "convention_unverified"

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
    "para cikisi", "para cekme", "havale giden",
})
_IN_VALUES = frozenset({
    "a", "alacak", "alacakli", "credit", "c", "cr", "giris", "giren", "tahsilat", "gelir", "income", "deposit",
    "gelen", "para girisi", "para yatirma", "havale gelen",
})
_LEADING_WORDS = {"borc": EXPENSE, "alacak": INCOME, "debit": EXPENSE, "credit": INCOME}

# Debit/credit words are the BOOK's words: whose book (the customer's or the bank's) differs between
# exports. Words that name the movement itself (Çıkış, Giden, Ödeme, Withdrawal ...) do not.
_AMBIGUOUS_WORDS = frozenset({
    "b", "a", "borc", "alacak", "borclu", "alacakli", "debit", "credit", "d", "c", "dr", "cr",
    "borc tutari", "borc tutar", "alacak tutari", "alacak tutar", "debit amount", "credit amount", "debits", "credits",
})


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


def value_is_ambiguous(raw: Any) -> bool:
    """Whether a direction value is a debit/credit word (the convention is the bank's to choose)."""
    v = norm_header(str(raw or ""))
    return v in _AMBIGUOUS_WORDS or (len(v.split()) > 1 and v.split()[0] in _LEADING_WORDS)


def header_signature(headers: list[str], identity: str = "") -> str:
    """The identity of a file's layout: its header words in order, and which bank account it is from
    when the file says (`statement_identity`). Same format of the same account, same signature."""
    material = "|".join(norm_header(h) for h in headers if h and h.strip()) + "||" + identity
    return hashlib.sha256(material.encode()).hexdigest()[:24]


_IBAN = re.compile(r"\bTR\d{2}(?:\s?\d{4}){5}\s?\d{2}\b", re.IGNORECASE)
_ACCOUNT_NO = re.compile(r"hesap\s*(?:no|numaras[ıi])\s*[:\-]?\s*(\d[\d\s\-]{5,})", re.IGNORECASE)
_BANKS = ("akbank", "garanti", "is bankasi", "ziraat", "yapi kredi", "qnb", "enpara", "halkbank", "vakifbank",
          "denizbank", "teb", "ing", "kuveyt turk", "albaraka", "fibabanka", "odeabank", "sekerbank", "papara")


def statement_identity(text: str) -> str:
    """Which account a statement is from, when its header says: IBAN, else account number, else bank name; "" if none."""
    head = (text or "")[:4000]
    if m := _IBAN.search(head):
        return "iban:" + re.sub(r"\s", "", m.group(0)).upper()
    if m := _ACCOUNT_NO.search(head):
        return "acct:" + re.sub(r"\D", "", m.group(1))
    folded = " " + fold(head) + " "
    for bank in _BANKS:
        if f" {bank} " in folded or f" {bank}," in folded:
            return "bank:" + bank
    return ""


_NON_TRANSACTION = ("devreden", "devir", "toplam", "genel toplam", "ara toplam", "acilis bakiye", "kapanis bakiye",
                    "donem sonu", "opening balance", "closing balance", "balance forward", "brought forward",
                    "total", "subtotal")


def is_non_transaction(description: str) -> bool:
    """A "Devreden Bakiye", "Toplam" or "Ara Toplam" line: a total or a carried balance, not a movement."""
    words = norm_header(description)
    return bool(words) and any(words == p or words.startswith(p + " ") for p in _NON_TRANSACTION)


def sign_is_informative(negatives: list[bool]) -> bool:
    """Whether the signs of one amount column say which way money went: both signs are present and the
    rarer one is a real share (15%) of the rows. One reversal in a column of positives is not a direction,
    and neither is a column of only negatives (the sign may just be how that export writes amounts)."""
    if not negatives:
        return False
    neg = sum(negatives)
    return 0 < neg < len(negatives) and min(neg, len(negatives) - neg) / len(negatives) >= 0.15


# ── per-file resolution ──────────────────────────────────────────────────────

@dataclass
class RowDirection:
    type: str | None          # what the row is booked as; None = held
    amount_cents: int | None  # magnitude; None = unreadable
    read: str | None = None   # what the file's columns said (kept when a file is held whole)
    balance: str | None = None  # what the balance column says, when it was checked
    note: str = ""
    mismatch: bool = False    # held on its own: its balance step does not reconcile


@dataclass
class FileDirection:
    rows: list[RowDirection]
    notes: list[str] = field(default_factory=list)
    # Set when the file as a whole cannot be placed: {reason, signature, identity, question}.
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


@dataclass
class Chain:
    matches: int
    inverted: int
    total: int
    newest_first: bool
    bad: list[int]            # rows whose own balance step does not equal their amount in their direction


def _chain(mags: list[int | None], dirs: list[str | None], bals: list[int | None]) -> Chain:
    """Compare balance movements with the amounts, in the row order that explains the file best."""
    best = Chain(0, 0, 0, False, [])
    for newest_first in (False, True):
        m = inv = total = 0
        bad: list[int] = []
        for i in range(1, len(mags)):
            later, earlier = (i, i - 1) if not newest_first else (i - 1, i)
            mag, now, before = mags[later], bals[later], bals[earlier]
            if now is None or before is None or mag is None or dirs[later] is None:
                continue
            delta = now - before
            expected = mag if dirs[later] == INCOME else -mag
            total += 1
            if delta == expected:
                m += 1
            else:
                bad.append(later)
                inv += delta == -expected
        if m + inv > best.matches + best.inverted or (m + inv == best.matches + best.inverted and m > best.matches):
            best = Chain(m, inv, total, newest_first, bad)
    return best


def verdict(mags: list[int | None], dirs: list[str | None], bals: list[int | None]) -> str:
    """confirmed | inverted | inconclusive | unverified: does the balance agree with the directions read?"""
    c = _chain(mags, dirs, bals)
    if c.total < 1:
        return "unverified"
    if c.matches / c.total >= 0.9:
        return "confirmed"
    if c.inverted / c.total >= 0.9 and c.matches / c.total < 0.5:
        return "inverted"
    return "inconclusive"


def reconciliation_rate(mags: list[int | None], dirs: list[str | None], bals: list[int | None]) -> int:
    c = _chain(mags, dirs, bals)
    return round(100 * c.matches / c.total) if c.total else 0


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
    mapping: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    labels = {v: k for k, v in roles.items()}
    columns = [{"name": h, "role": labels.get(h)} for h in headers if h and h.strip()]
    shown = [r for r in ("date", "description", "amount", "debit", "credit", "direction", "balance") if r in roles]
    samples = [{r: str(row.get(roles[r], "")).strip() for r in shown} for row in rows[:3]]
    return {"reason": reason, "columns": columns, "samples": samples, "note": note, "mapping": mapping or []}


def _convention_mapping(
    roles: dict[str, str], rows: list[dict[str, str]], direction_column: str | None, split: bool,
) -> list[dict[str, str]]:
    """What the detected reading says each debit/credit word means: [{label, means}]."""
    if split:
        return [{"label": roles[k], "means": m} for k, m in (("debit", EXPENSE), ("credit", INCOME)) if k in roles]
    seen: dict[str, str] = {}
    for row in rows:
        value = str(row.get(direction_column or "", "")).strip()
        if value and (d := value_direction(value)) and value_is_ambiguous(value):
            seen.setdefault(value, d)
    return [{"label": v, "means": d} for v, d in list(seen.items())[:4]]


def resolve_file(
    headers: list[str], rows: list[dict[str, str]], skip: frozenset[int] = frozenset(), identity: str = "",
) -> FileDirection:
    """Direction and amount of every row of one statement table, by the precedence in the module doc.

    `skip` are rows that are not movements (carried balance, totals): never booked, but their balance
    anchors the chain. A direction that rests on a debit/credit word and cannot be verified by a balance
    column is not booked: the file waits for ONE question (`convention_unverified`).
    """
    roles = _roles(headers)
    roles.pop("direction", None)
    direction_column, best = None, 0.0
    for h in (h for h in headers if norm_header(h) in _DIRECTION):
        cells = [c for c in (str(r.get(h, "")).strip() for r in rows) if c]
        ratio = sum(value_direction(c) is not None for c in cells) / len(cells) if cells else 0.0
        if ratio >= 0.5 and ratio > best:
            direction_column, best = h, ratio
    if direction_column:
        roles["direction"] = direction_column
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
    signature = header_signature(headers, identity)

    def hold_file(reason: str, note: str, out_reads: list[str | None], hints: list[str | None],
                  mapping: list[dict[str, str]] | None = None) -> FileDirection:
        hold = {"reason": reason, "signature": signature, "identity": bool(identity),
                "question": _question(headers, roles, rows, reason, note, mapping)}
        return FileDirection(
            [RowDirection(None, mags[i], out_reads[i], hints[i], notes_per_row[i]) for i in range(n)],
            [f"yön: dosya tek soruyla bekliyor ({reason})"], hold,
        )

    for i, row in enumerate(rows):
        if i in skip:
            continue
        amount = parse_money(str(row.get(roles["amount"], "")).strip()) if "amount" in roles else None
        if split:
            d, c = _filled(row.get(roles.get("debit", ""))), _filled(row.get(roles.get("credit", "")))
            if d and c:
                notes_per_row[i] = "borç ve alacak sütunlarının ikisi de dolu"
                continue
            if d or c:
                mag, read = (d or c)[0], EXPENSE if d else INCOME  # type: ignore[index]
                # A "Tutar" column beside the debit/credit columns is a second source: it must agree.
                if amount is not None and amount[0] and (amount[0] != mag or (amount[1] and read == INCOME)):
                    notes_per_row[i] = "tutar sütunu borç/alacak sütunlarıyla uyuşmuyor"
                    continue
                mags[i], reads[i] = mag, read
                continue
        if amount is not None:
            mags[i], negative[i], via_amount[i] = amount[0], amount[1], True
        if direction_column:
            column_values[i] = str(row.get(direction_column, "")).strip()

    bals: list[int | None] = [signed_money(r.get(roles["balance"])) if "balance" in roles else None for r in rows]

    # (c) the sign: informative if both signs are a real share, or the balance confirms the sign reading
    sign_rows = [i for i in range(n) if via_amount[i] and mags[i]]
    sign_informative = sign_is_informative([negative[i] for i in sign_rows])
    if not sign_informative and sign_rows and sum(negative[i] for i in sign_rows) > 0 and "balance" in roles:
        tentative: list[str | None] = [None] * n
        for i in sign_rows:
            tentative[i] = EXPENSE if negative[i] else INCOME
        sign_informative = verdict(mags, tentative, bals) == "confirmed"

    for i in range(n):
        if i in skip or reads[i] is not None or notes_per_row[i]:
            continue
        if mags[i] is None and not column_values[i]:
            continue
        cell = column_values[i]
        said = value_direction(cell) if direction_column and cell else None
        if direction_column and cell and said is None:
            notes_per_row[i] = f"yön değeri tanınmadı: {cell}"
            continue
        if said is not None:
            reads[i] = said
        elif sign_informative and via_amount[i]:
            reads[i] = EXPENSE if negative[i] else INCOME

    has_signal = split or direction_column is not None or sign_informative
    ambiguous = (split and any(norm_header(roles[k]) in _AMBIGUOUS_WORDS for k in ("debit", "credit") if k in roles)) or (
        direction_column is not None and any(value_is_ambiguous(v) for v in column_values if v)
    )
    notes: list[str] = []

    if not any(reads) and not has_signal:
        derived = _from_balance(mags, bals)
        if derived is None:
            return hold_file(NO_SIGNAL, "Tutarların yönünü gösteren bir sütun ya da işaret bulunamadı.",
                             [None] * n, [None] * n)
        reads = derived
        notes.append("yön, bakiye hareketinden okundu")
        live = [i for i in range(n) if i not in skip]
        ends = {live[0], live[-1]} if live else set()     # the end of the chain has no neighbour to be checked against
        mismatch = {i for i in live if mags[i] and reads[i] is None and i not in ends}
        for i in live:
            if mags[i] and reads[i] is None:
                notes_per_row[i] = "bakiye ile uyuşmuyor" if i in mismatch else "bakiye zincirinin ucu: yön okunamadı"
        return FileDirection(
            [RowDirection(reads[i], mags[i], reads[i], None, notes_per_row[i], i in mismatch) for i in range(n)], notes)

    state = verdict(mags, reads, bals)
    if state == "inverted":
        hints = [_flip(r) for r in reads]
        return hold_file(BALANCE_CONTRADICTS, "Bakiye hareketi, sütunlardan okunan yönün tersini gösteriyor.", reads, hints)
    if state == "inconclusive":
        rate = reconciliation_rate(mags, reads, bals)
        return hold_file(
            BALANCE_INCONCLUSIVE,
            f"Bakiye hareketi satırların yalnızca %{rate}'ini doğruluyor; dosya güvenle okunamadı.", reads, [None] * n)
    if state == "unverified" and ambiguous:
        mapping = _convention_mapping(roles, rows, direction_column, split)
        return hold_file(
            CONVENTION_UNVERIFIED,
            "Borç/Alacak sözcükleri bankaya göre değişir ve bakiye sütunu olmadığından doğrulanamadı.",
            reads, [_flip(r) for r in reads], mapping)

    mismatch = set()
    if state == "confirmed":
        mismatch = set(_chain(mags, reads, bals).bad)
        notes.append("yön bakiye hareketiyle doğrulandı")
        for i in mismatch:
            notes_per_row[i] = "bakiye ile uyuşmuyor"
    else:
        notes.append("yön doğrulanmadı (bakiye sütunu yok ya da yetersiz)")
    return FileDirection([
        RowDirection(None if i in mismatch else reads[i], mags[i], reads[i], None, notes_per_row[i], i in mismatch)
        for i in range(n)
    ], notes)


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
        return {"signature": signature, "reason": reason, "identity": False,
                "question": {"columns": [], "samples": samples, "reason": reason, "note": note, "mapping": []}}

    if rows and not any(reads):
        derived = _from_balance(mags, bals)
        if derived is None:
            return hold(NO_SIGNAL, "Tutarların yönünü gösteren bir sütun ya da işaret bulunamadı.")
        for r, d in zip(rows, derived, strict=True):
            r["type"] = d
        return None
    state = verdict(mags, reads, bals)
    if state == "inverted":
        for r, d in zip(rows, reads, strict=True):
            r["direction_read"], r["direction_balance"], r["type"] = d, _flip(d), None
        return hold(BALANCE_CONTRADICTS, "Bakiye hareketi, okunan yönün tersini gösteriyor.")
    if state == "inconclusive":
        rate = reconciliation_rate(mags, reads, bals)
        for r, d in zip(rows, reads, strict=True):
            r["direction_read"], r["type"] = d, None
        return hold(BALANCE_INCONCLUSIVE, f"Bakiye hareketi satırların yalnızca %{rate}'ini doğruluyor.")
    if state == "confirmed":
        for i in _chain(mags, reads, bals).bad:
            rows[i]["type"], rows[i]["balance_mismatch"] = None, True
    return None
