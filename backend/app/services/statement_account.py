"""Which bank account a statement is from, read ONLY where a statement says so about itself.

An account identifier is a fact about the whole file, so it is read from:

- the HEADER: the lines before the table's column-header line, as `app.parsers.lines` finds it (the same
  boundary `app.services.stated_period` uses), or
- a COLUMN whose header names it ("IBAN", "Hesap No") when every row of the file carries the same value.

Never from a transaction row. A counterparty's IBAN in "FAST TR33... Ali", an account number in a
description ("Hesap No: 12345678 aidat"), another bank's name in "Gelen havale Akbank EFT" say nothing about
which account the statement is: reading them made two statements of one account look like two accounts,
and two accounts are added together. With no detectable table header, no identity is read at all.

An account number needs its label ("Hesap No", "Hesap Numarası", "Müşteri Hesap No", or the IBAN's own
shape). A bank name counts only from the header. The result is "iban:TR..", "acct:123..", "bank:akbank", or
None; `mask` is how it is shown to a person (last four characters).
"""
from __future__ import annotations

import re

from app.core.turkish import fold
from app.parsers.lines import _is_header, read_lines

_IBAN = re.compile(r"\bTR\d{2}(?:\s?\d{4}){5}\s?\d{2}\b", re.IGNORECASE)
_ACCOUNT_NO = re.compile(r"hesap\s*(?:no|numaras[ıi])\s*[:\-]?\s*(\d[\d\s\-]{5,})", re.IGNORECASE)
_COLUMN = re.compile(r"^\s*(?:iban|hesap\s*no|hesap\s*numaras[ıi]|müşteri\s*hesap\s*no)\s*$", re.IGNORECASE)
_BANKS = ("akbank", "garanti", "is bankasi", "ziraat", "yapi kredi", "qnb", "enpara", "halkbank", "vakifbank",
          "denizbank", "teb", "ing", "kuveyt turk", "albaraka", "fibabanka", "odeabank", "sekerbank", "papara")
_DELIMITERS = re.compile(r"[;\t|]")


def _norm_iban(text: str) -> str:
    return "iban:" + re.sub(r"\s", "", text).upper()


def _from_header(header: list[str]) -> str | None:
    text = "\n".join(header)
    ibans = {_norm_iban(m.group(0)) for m in _IBAN.finditer(text)}
    if len(ibans) == 1:
        return next(iter(ibans))
    if len(ibans) > 1:
        return None  # a header naming two accounts says which one only to a person
    numbers = {"acct:" + re.sub(r"\D", "", m.group(1)) for m in _ACCOUNT_NO.finditer(text)}
    if len(numbers) == 1:
        return next(iter(numbers))
    if numbers:
        return None
    folded = " " + fold(text) + " "
    banks = [b for b in _BANKS if f" {b} " in folded or f" {b}," in folded]
    return f"bank:{banks[0]}" if len(banks) == 1 else None


def _from_column(lines: list[str], header_at: int) -> str | None:
    """A column named IBAN or Hesap No, when every row of the file carries the same value in it."""
    cells = _DELIMITERS.split(lines[header_at])
    index = next((i for i, c in enumerate(cells) if _COLUMN.match(c)), None)
    if index is None:
        return None
    values: set[str] = set()
    for line in lines[header_at + 1:]:
        parts = _DELIMITERS.split(line)
        if len(parts) <= index or not parts[index].strip():
            continue
        values.add(parts[index].strip())
    if len(values) != 1:
        return None
    value = next(iter(values))
    if m := _IBAN.fullmatch(value.strip()):
        return _norm_iban(m.group(0))
    digits = re.sub(r"\D", "", value)
    return f"acct:{digits}" if len(digits) >= 6 and re.fullmatch(r"[\d\s\-]+", value) else None


def account_identity(text: str) -> str | None:
    """"iban:..", "acct:..", "bank:.." read from the header or a named column; None when the file states none."""
    lines = read_lines(text or "")
    header_at = next((i for i, line in enumerate(lines) if _is_header(line)), None)
    if header_at is None:
        return None
    return _from_column(lines, header_at) or _from_header(lines[:header_at])


def kind(identity: str | None) -> str | None:
    return str(identity).split(":", 1)[0] if identity else None


def mask(identity: str | None) -> str | None:
    """How an identifier is shown: its kind and last four characters ("IBAN ****1326"); a bank by name."""
    if not identity:
        return None
    label, _, value = str(identity).partition(":")
    if label == "bank":
        return value
    return f"{'IBAN' if label == 'iban' else 'Hesap'} ****{value[-4:]}"
