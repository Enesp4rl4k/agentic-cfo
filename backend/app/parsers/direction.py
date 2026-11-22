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
  (c) the sign of ONE amount column, but only with corroboration: a balance chain
      that verifies "minus = out, plus = in" (`sign_corroborated`), or this
      organisation's remembered answer for this file format. A sign alone is not
      evidence: an expense list with a few reversals has the signs of a statement
      that is mostly deposits, and a file of all-positive or all-negative numbers
      says nothing either. Without corroboration the whole file waits for ONE
      question (`sign_unconfirmed`: "minus = out, plus = in?", with a preview and
      both readings' totals); one rule for mixed, all-positive and all-negative files.
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
from app.parsers.balance_chain import (
    EXPENSE,
    INCOME,
    _chain,
    _flip,
    _from_balance,
    outside_chain,
    reconciliation_rate,
    sign_preview,
    verdict,
)

OUTSIDE_NOTE = "bakiye zincirinin dışında kalan satır"

# Why a whole file waits (the reason codes of `direction_file`).
NO_SIGNAL = "no_signal"
BALANCE_CONTRADICTS = "balance_contradicts"
# The balance reconciles only part of the rows: neither confirmed nor contradicted.
BALANCE_INCONCLUSIVE = "balance_inconclusive"
# A direction from a debit/credit word (the bank's book or the customer's?) that no balance can verify.
CONVENTION_UNVERIFIED = "convention_unverified"
# One signed amount column with no balance chain (or remembered answer) to say that minus means out.
SIGN_UNCONFIRMED = "sign_unconfirmed"

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

DEBIT_ALIASES = _DEBIT
CREDIT_ALIASES = _CREDIT
AMOUNT_COLUMNS = _DEBIT | _CREDIT | _AMOUNT   # any of them makes a table a statement


def is_statement_header(headers: list[str]) -> bool:
    """A header row with a date and something that can carry an amount."""
    names = {norm_header(h) for h in headers if h}
    return bool(names & AMOUNT_COLUMNS) and bool(names & (_DATE | {"islem tarihi"}))


_OUT_VALUES = frozenset({
    "b", "borc", "borclu", "debit", "d", "dr", "cikis", "cikan", "gider", "expense", "withdrawal", "giden",
    "para cikisi", "para cekme", "havale giden", "giden odeme", "giden havale", "giden eft", "giden fast",
})
# A bare "Ödeme", "Havale", "EFT", "FAST" or "Virman" names the kind of transaction, not its direction.
_IN_VALUES = frozenset({
    "a", "alacak", "alacakli", "credit", "c", "cr", "giris", "giren", "tahsilat", "gelir", "income", "deposit",
    "gelen", "para girisi", "para yatirma", "havale gelen", "gelen odeme", "gelen havale", "gelen eft", "gelen fast",
})
_LEADING_WORDS = {"borc": EXPENSE, "alacak": INCOME, "debit": EXPENSE, "credit": INCOME,
                  "gelen": INCOME, "giden": EXPENSE}

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
    return v in _AMBIGUOUS_WORDS or (len(v.split()) > 1 and v.split()[0] in ("borc", "alacak", "debit", "credit"))


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


_SUMMARY_LINES = frozenset({
    "devreden bakiye", "devir bakiye", "devreden", "devir", "toplam", "ara toplam", "genel toplam",
    "donem sonu bakiye", "donem sonu bakiyesi", "acilis bakiyesi", "acilis bakiye", "kapanis bakiyesi", "kapanis bakiye",
    "opening balance", "closing balance", "balance forward", "brought forward", "total", "subtotal", "grand total",
})


def is_summary_phrase(description: str) -> bool:
    """The whole description is a summary phrase ("Devreden Bakiye", "Toplam"). Never a prefix: "Toplam fatura
    ödemesi", "Devreden KDV" and a vendor called "Total Wireless" are transactions."""
    return norm_header(description) in _SUMMARY_LINES


def is_non_transaction(description: str) -> bool:
    """Kept for callers that only have the description: the exact summary phrase. A row also needs the
    structural test in `app.services.ingest.rows` (no date, or no amount) before it is skipped."""
    return is_summary_phrase(description)


# ── per-file resolution ──────────────────────────────────────────────────────

@dataclass
class RowDirection:
    type: str | None          # what the row is booked as; None = held
    amount_cents: int | None  # magnitude; None = unreadable
    read: str | None = None   # what the file's columns said (kept when a file is held whole)
    balance: str | None = None  # what the balance column says, when it was checked
    note: str = ""
    mismatch: bool = False    # held on its own: its balance step does not reconcile
    outside: bool = False     # held on its own: no balance, in a statement whose other rows have one


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


def _question(
    headers: list[str], roles: dict[str, str], rows: list[dict[str, str]], reason: str, note: str,
    mapping: list[dict[str, str]] | None = None, display: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    shown_as = display or {}
    labels = {v: k for k, v in roles.items()}
    columns = [{"name": shown_as.get(h, h), "role": labels.get(h)} for h in headers if h and h.strip()]
    shown = [r for r in ("date", "description", "amount", "debit", "credit", "direction", "balance") if r in roles]
    picked = rows[:3] if extra is None else [rows[i] for i in extra.pop("sample_rows", range(min(3, len(rows))))]
    samples = [{r: str(row.get(roles[r], "")).strip() for r in shown} for row in picked]
    return {"reason": reason, "columns": columns, "samples": samples, "note": note, "mapping": mapping or [], **(extra or {})}


def _convention_mapping(
    roles: dict[str, str], rows: list[dict[str, str]], direction_column: str | None, split: bool,
    display: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """What the detected reading says each debit/credit word means: [{label, means}]."""
    if split:
        return [{"label": (display or {}).get(roles[k], roles[k]), "means": m}
                for k, m in (("debit", EXPENSE), ("credit", INCOME)) if k in roles]
    seen: dict[str, str] = {}
    for row in rows:
        value = str(row.get(direction_column or "", "")).strip()
        if value and (d := value_direction(value)) and value_is_ambiguous(value):
            seen.setdefault(value, d)
    return [{"label": v, "means": d} for v, d in list(seen.items())[:4]]


def resolve_file(
    headers: list[str], rows: list[dict[str, str]], skip: frozenset[int] = frozenset(), identity: str = "",
    labels: dict[str, str] | None = None,
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
                  mapping: list[dict[str, str]] | None = None, extra: dict[str, Any] | None = None) -> FileDirection:
        hold = {"reason": reason, "signature": signature, "identity": bool(identity),
                "uniform": bool((extra or {}).get("uniform")),
                "question": _question(headers, roles, rows, reason, note, mapping, labels, extra)}
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

    # (c) the sign of one amount column decides only with evidence: a balance chain that verifies it. Without that
    # (and without a remembered answer, applied later by held_direction) the file is asked once.
    sign_rows = [i for i in range(n) if via_amount[i] and mags[i]]
    sign_reads = False
    if sign_rows and not split and direction_column is None:
        tentative: list[str | None] = [None] * n
        for i in sign_rows:
            tentative[i] = EXPENSE if negative[i] else INCOME
        state = verdict(mags, tentative, bals) if "balance" in roles else "unverified"
        uniform = len({negative[i] for i in sign_rows}) == 1
        if state == "confirmed":
            sign_reads = True
        elif uniform and _from_balance(mags, bals) is not None:
            pass                                    # one sign says nothing; the balance reads the direction below
        elif state in ("inverted", "inconclusive"):
            sign_reads = True                       # the balance disagrees: the checks below hold the file with the reason
        else:
            note = ("Dosyada hem eksi hem artı tutar var, ama işaretin yönü gösterdiğini doğrulayan bir bakiye zinciri yok."
                    if not uniform else
                    "Dosyadaki tüm tutarlar aynı işaretli; yönü gösteren bir sütun ya da doğrulayan bir bakiye zinciri yok.")
            return hold_file(
                SIGN_UNCONFIRMED, note, tentative, [_flip(t) for t in tentative],
                [{"label": "-", "means": EXPENSE}, {"label": "+", "means": INCOME}],
                sign_preview(mags, negative, sign_rows))

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
        elif sign_reads and via_amount[i]:
            reads[i] = EXPENSE if negative[i] else INCOME

    has_signal = split or direction_column is not None or sign_reads
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
        outside = outside_chain(mags, bals, skip)
        mismatch: set[int] = {i for i in live if mags[i] and reads[i] is None and i not in ends and i not in outside}
        for i in live:
            if i in outside:
                notes_per_row[i] = OUTSIDE_NOTE
            elif mags[i] and reads[i] is None:
                notes_per_row[i] = "bakiye ile uyuşmuyor" if i in mismatch else "bakiye zincirinin ucu: yön okunamadı"
        return FileDirection(
            [RowDirection(None if i in outside else reads[i], mags[i], reads[i], None, notes_per_row[i], i in mismatch,
                          i in outside) for i in range(n)], notes)

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
        mapping = _convention_mapping(roles, rows, direction_column, split, labels)
        return hold_file(
            CONVENTION_UNVERIFIED,
            "Borç/Alacak sözcükleri bankaya göre değişir ve bakiye sütunu olmadığından doğrulanamadı.",
            reads, [_flip(r) for r in reads], mapping)

    mismatch = set()
    outside = outside_chain(mags, bals, skip)       # no balance among rows that have one: not a link of the chain
    if state == "confirmed":
        mismatch = set(_chain(mags, reads, bals).bad)
        notes.append("yön bakiye hareketiyle doğrulandı")
        for i in mismatch:
            notes_per_row[i] = "bakiye ile uyuşmuyor"
    else:
        notes.append("yön doğrulanmadı (bakiye sütunu yok ya da yetersiz)")
    for i in outside:
        notes_per_row[i] = OUTSIDE_NOTE
    if outside:
        notes.append(f"{len(outside)} satır bakiye zincirinin dışında kaldı")
    return FileDirection([
        RowDirection(None if i in mismatch or i in outside else reads[i], mags[i], reads[i], None, notes_per_row[i],
                     i in mismatch, i in outside)
        for i in range(n)
    ], notes)


def settle_rows(
    rows: list[dict[str, Any]], signature_material: str, *, ambiguous: bool = False, identity: bool = False,
) -> dict[str, Any] | None:
    """The same checks for rows a text parser already read (type, amount_cents, balance_cents).

    A text statement counts as verified only with at least three reconciling balance steps (>= 90%): two
    rows prove nothing. Unverified and read from a Borç/Alacak layout (`ambiguous`): held, asked once.
    A direction a parser took from the sign alone (`direction_basis == "sign"`) is the same as in a table:
    only a verifying chain (or a remembered answer, applied later) lets it book; otherwise the file is asked.
    A row with no balance among rows that have one is outside the chain: held on its own (`outside_chain`).

    Mutates `rows` when the file is held whole (every `type` cleared, `direction_file` set by the
    caller) and returns the hold; returns None otherwise. A row a parser could not place has
    type None/"" and stays held on its own; a statement where none was placed is held whole.
    """
    mags = [r.get("amount_cents") for r in rows]
    reads: list[str | None] = [r["type"] if r.get("type") in (INCOME, EXPENSE) else None for r in rows]
    bals = [r.get("balance_cents") for r in rows]
    signature = hashlib.sha256(signature_material.encode()).hexdigest()[:24]
    samples = [{"description": str(r.get("description", "")), "amount": str(r.get("amount_cents"))} for r in rows[:3]]

    def hold(reason: str, note: str, extra: dict[str, Any] | None = None, mapping: list[dict[str, str]] | None = None,
             shown: list[dict[str, str]] | None = None) -> dict[str, Any]:
        return {"signature": signature, "reason": reason, "identity": identity, "uniform": bool((extra or {}).get("uniform")),
                "question": {"columns": [], "samples": shown or samples, "reason": reason, "note": note,
                             "mapping": mapping or [], **(extra or {})}}

    typed = [r for r in rows if r.get("type") in (INCOME, EXPENSE)]
    if typed and all(r.get("direction_basis") == "sign" for r in typed):
        # The parser read every direction off the sign of one column. That is a reading, not evidence.
        negative = [r.get("type") == EXPENSE for r in rows]
        sign_rows = [i for i, r in enumerate(rows) if r.get("type") in (INCOME, EXPENSE) and mags[i]]
        state = verdict(mags, reads, bals, min_steps=3)
        uniform = len({negative[i] for i in sign_rows}) <= 1
        if state == "unverified" and uniform and (derived := _from_balance(mags, bals)) is not None:
            for r, d in zip(rows, derived, strict=True):
                r["type"] = d
            return None
        if state == "unverified" and sign_rows:
            preview = sign_preview(mags, negative, sign_rows)
            shown = [{"description": str(rows[i].get("description", "")),
                      "amount": ("-" if negative[i] else "") + f"{(mags[i] or 0) / 100:.2f}"} for i in preview.pop("sample_rows")]
            for r, d in zip(rows, reads, strict=True):
                r["direction_read"], r["direction_balance"], r["type"] = d, _flip(d), None
            return hold(SIGN_UNCONFIRMED, "Eksi/artı işaretin yönü gösterdiğini doğrulayan bir bakiye zinciri yok.", preview,
                        [{"label": "-", "means": EXPENSE}, {"label": "+", "means": INCOME}], shown)

    if rows and not any(reads):
        derived = _from_balance(mags, bals)
        if derived is None:
            return hold(NO_SIGNAL, "Tutarların yönünü gösteren bir sütun ya da işaret bulunamadı.")
        for r, d in zip(rows, derived, strict=True):
            r["type"] = d
            if d is not None:
                r["direction_from_balance"] = True   # read off the balance itself: not independent evidence of it
        return None
    state = verdict(mags, reads, bals, min_steps=3)
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
        for i in outside_chain(mags, bals):
            rows[i]["type"], rows[i]["outside_chain"] = None, True
    elif state == "unverified" and ambiguous:
        for r, d in zip(rows, reads, strict=True):
            r["direction_read"], r["direction_balance"], r["type"] = d, _flip(d), None
        return hold(CONVENTION_UNVERIFIED,
                    "Borç/Alacak sözcükleri bankaya göre değişir; yeterli bakiye adımı olmadığından doğrulanamadı.")
    return None
