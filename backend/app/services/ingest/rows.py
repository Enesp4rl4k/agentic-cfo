"""Tabular rows to transactions: bank statements, account-coded ledgers and uploaded CSVs.

Moved out of app/agents/data_ingestion.py unchanged (plan v11 A0.3); that module
re-exports what its callers import from it.
"""

from __future__ import annotations

from typing import Any

from app.core import tdhp
from app.core.turkish import fold
from app.parsers.base import ParsedStatement
from app.services.ingest.categories import (
    INCOME_CATEGORIES,
    KNOWN_CATEGORIES,
    _guess_category,
)
from app.services.ingest.cells import (
    _is_negative,
    _parse_amount,
    _parse_date,
)


def _statement_to_transactions(statement: ParsedStatement) -> list[dict[str, Any]]:
    """Convert ParsedStatement (bank parser output) to the CFO pipeline's transaction format."""
    transactions = []
    for tx in statement.transactions:
        hesap = tdhp.hesap(tx.account_code)
        transactions.append({
            "amount_cents": tx.amount_cents,
            "currency": tx.currency,
            "type": tx.tx_type,
            "category": (
                _kodlu_kategori(hesap, tx.description) if hesap is not None
                else _guess_category(tx.description, tx.tx_type)
            ),
            "account_code": tx.account_code,
            "description": tx.description,
            "vendor": tx.vendor,
            "transaction_date": tx.date.isoformat() if tx.date else None,
            "raw_text": (
                f"{tx.raw_row}\n[yön] {tx.confidence_note}"
                if tx.confidence_note else tx.raw_row
            ),
            # Structured parsers are high-confidence about the *rows*; they are
            # not automatically right about which way the money went. A parser
            # that knows better says so, and only then does this cap apply.
            "confidence": min(0.95, tx.confidence),
            # Not money moved: the bank's own running total, which proves the
            # balance the statement closes on (app.services.bank_balance).
            "balance_cents": tx.balance_cents,
        })
    return transactions


_HESAP_KODU_KOLONLARI = ("hesap kodu", "hesap no", "hesap", "account_code", "account code")


def _hesap_kodlu_satir(
    hesap: tdhp.Hesap, borc: str, alacak: str, raw_amt: str, raw_desc: str, raw_cat: str,
) -> tuple[str, int, str] | None:
    """(type, signed kuruş, category) of a row whose account the map knows; None to skip it.

    The account decides direction and whether the row is a P&L event. Within an
    expense account the nature (salary, rent, …) still comes from the row's own
    words, since 7/A accounts group by function — but never an income category.
    """
    borc_k = abs(_parse_amount(borc) or 0)
    alacak_k = abs(_parse_amount(alacak) or 0)
    if not (borc_k or alacak_k):  # one signed "Tutar" column instead of Borç/Alacak
        tutar = abs(_parse_amount(raw_amt) or 0)
        borc_k, alacak_k = (tutar, 0) if _is_negative(raw_amt) else (0, tutar)
    hareket = tdhp.hareket(hesap, borc_k, alacak_k)
    if hareket is None:
        return None
    tx_type, kurus = hareket
    return tx_type, kurus, _kodlu_kategori(hesap, raw_desc, raw_cat)


def _kodlu_kategori(hesap: tdhp.Hesap, description: str, raw_cat: str = "") -> str:
    """Category of a row the account map knows: the account's own, except that
    an expense account's nature comes from the row's words when they say it."""
    if hesap.rol != "gider":
        return hesap.kategori
    cat = raw_cat.strip().lower()
    if cat in KNOWN_CATEGORIES and cat not in INCOME_CATEGORIES:
        return cat
    tahmin = _guess_category(description, "expense")
    return tahmin if tahmin != "other_expense" else hesap.kategori


_TUTAR_KOLONLARI = ("amount", "tutar", "borc", "alacak", "amount_cents")


_TARIH_KOLONLARI = ("date", "tarih", "islem tarihi", "transaction_date")


def _ilk(r_lower: dict[str, str], *anahtarlar: str) -> str:
    """The first non-empty value among these folded column names."""
    return next((r_lower[k] for k in anahtarlar if r_lower.get(k)), "")


def _isaretli_kurus(raw_amt: str) -> int:
    """Kuruş of an amount cell, negative when the cell says so."""
    amount_cents = _parse_amount(raw_amt)
    if amount_cents is None:
        try:
            amount_cents = round(float(raw_amt) * 100)
        except ValueError:
            amount_cents = 0
    return -abs(amount_cents) if _is_negative(raw_amt) else amount_cents


def _yukleyenin_kategorisi(raw_cat: str, raw_desc: str, tx_type: str) -> str:
    """Category of a row without an account code.

    A category column is the uploader's word, not ours. "Gıda", "payroll",
    "sales" — all reasonable to write and none of them something this pipeline
    groups by, so an unrecognised value is worse than a guessed one: it
    disappears from every report silently. Keep it only when it is a category
    we know. "tax" on a KDV payment is the uploader saying a tax was paid, not
    that it was an expense: KDV is not on a KDV payer's P&L.
    """
    cat_lower = raw_cat.strip().lower()
    category = (
        cat_lower if cat_lower in KNOWN_CATEGORIES
        else _guess_category(raw_desc or raw_cat, tx_type)
    )
    if category == "tax" and _guess_category(raw_desc, tx_type) == "tax_payment":
        return "tax_payment"
    return category


def _tutar_hucresi(r_lower: dict[str, str]) -> str:
    """The row's signed amount as text. Bank statements split it: "Borç" is
    money leaving the account, "Alacak" money arriving."""
    raw_amt = _ilk(r_lower, "amount", "tutar")
    borc, alacak = r_lower.get("borc", ""), r_lower.get("alacak", "")
    if not raw_amt and (borc or alacak):
        raw_amt = f"-{borc.lstrip('-')}" if (_parse_amount(borc) or 0) > 0 else alacak
    return raw_amt or "0"


def _kodsuz_yon(r_lower: dict[str, str], amount_cents: int) -> str:
    """Direction of a row without an account: its type column, else its sign."""
    raw_type = _ilk(r_lower, "type", "tip")
    if raw_type in ("income", "expense"):
        return raw_type
    return "expense" if amount_cents < 0 else "income"


_FATURA_NO_KOLONLARI = ("fatura no", "invoice_no", "invoice no", "document_id")


_CARI_KOLONLARI = ("cari", "counterparty", "musteri tedarikci", "karsi taraf adi")


_VADE_KOLONLARI = ("vade", "vade tarihi", "due_date", "due date")


def _fatura_alanlari(tx: dict[str, Any], r_lower: dict[str, str]) -> None:
    """An invoice list's number, counterparty and due date, when the row has them.

    The number alone is an identity; the counterparty makes it an open item. A bank
    statement has neither column, so this never changes how one is read.
    """
    no = _ilk(r_lower, *_FATURA_NO_KOLONLARI)
    if not no:
        return
    from app.core.invoice_identity import canonical_invoice_id

    tx["document_id"] = canonical_invoice_id(None, no)
    cari = _ilk(r_lower, *_CARI_KOLONLARI)
    if cari:
        tx["counterparty"] = cari
        tx["vendor"] = cari
    vade = _parse_date(_ilk(r_lower, *_VADE_KOLONLARI))
    if vade:
        tx["due_date"] = vade.date().isoformat()


def _csv_satiri(row: dict[str, Any], atlanan: list[str] | None) -> dict[str, Any] | None:
    """One CSV row as a pipeline transaction; None for an empty or skipped row."""
    if not row or not any(row.values()):
        return None
    r_lower = {fold(k.strip()): (v.strip() if v else "") for k, v in row.items() if k}
    raw_amt = _tutar_hucresi(r_lower)
    raw_desc = _ilk(r_lower, "description", "aciklama", "detay")
    raw_cat = _ilk(r_lower, "category", "kategori")
    account_code = tdhp.ana_hesap(_ilk(r_lower, *_HESAP_KODU_KOLONLARI))
    hesap = tdhp.hesap(account_code) if account_code else None
    parsed_dt = _parse_date(_ilk(r_lower, "date", "tarih", "islem tarihi"))
    tx: dict[str, Any] = {
        "currency": "TRY",
        "description": raw_desc,
        "vendor": _ilk(r_lower, "vendor", "tedarikci") or raw_desc,
        "transaction_date": parsed_dt.isoformat() if parsed_dt else None,
        "raw_text": str(row),
        "account_code": account_code,
        # A code this map does not know is an income-statement account nobody
        # has classified: the row is read by its words and its sign, and says so.
        "confidence": 0.6 if account_code and hesap is None else 0.95,
    }
    if hesap is not None:
        borc, alacak = r_lower.get("borc", ""), r_lower.get("alacak", "")
        satir = _hesap_kodlu_satir(hesap, borc, alacak, raw_amt, raw_desc, raw_cat)
        if satir is None:
            if atlanan is not None:
                atlanan.append(f"{account_code} {raw_desc}".strip())
            return None
        tx["type"], tx["amount_cents"], tx["category"] = satir
        return tx

    amount_cents = _isaretli_kurus(raw_amt)
    tx["type"] = _kodsuz_yon(r_lower, amount_cents)
    tx["amount_cents"] = abs(amount_cents)
    tx["category"] = _yukleyenin_kategorisi(raw_cat, raw_desc, tx["type"])
    _fatura_alanlari(tx, r_lower)
    bakiye = _ilk(r_lower, "bakiye", "balance")
    if bakiye:
        tx["balance_cents"] = _isaretli_kurus(bakiye)
    return tx


def _try_parse_csv(raw_text: str, atlanan: list[str] | None = None) -> list[dict[str, Any]] | None:
    """Attempt deterministic CSV parsing if the text is structured CSV.

    A row naming a transfer or closing account (7x1, 690/692) is not read — it
    moves what is already counted — and is reported in `atlanan` instead.
    """
    import csv
    import io
    try:
        # Excel sheets are read as tab-separated and Turkish exports often use
        # ";" — the header line says which one this file uses.
        header = raw_text.lstrip("﻿").split("\n", 1)[0]
        delimiter = max((",", ";", "\t"), key=header.count)
        reader = csv.DictReader(io.StringIO(raw_text), delimiter=delimiter)
        if not reader.fieldnames:
            return None
        # Headers are folded (app.core.turkish): "İşlem Tarihi", "AÇIKLAMA" and
        # "Borç" match "islem tarihi", "aciklama", "borc". A running balance
        # ("bakiye") is not a transaction amount; it is kept beside the row.
        field_lower = {fold(f.strip()) for f in reader.fieldnames if f}
        if not (field_lower & set(_TUTAR_KOLONLARI) and field_lower & set(_TARIH_KOLONLARI)):
            return None
        transactions = [tx for row in reader if (tx := _csv_satiri(row, atlanan)) is not None]
        return transactions or None
    except Exception:
        return None


def _tablo_ekstresi(file_path: str, atlanan: list[str] | None = None) -> list[dict[str, Any]] | None:
    """The statement table inside a spreadsheet, found under any title rows, as transactions."""
    from app.services.ingest.recognize import standart_csv, tabloyu_sec
    from app.services.ingest.schemas import BANKA_EKSTRESI
    from app.services.ingest.table import OkunamayanDosya

    try:
        with open(file_path, "rb") as f:
            veri = f.read()
        tablo = tabloyu_sec(veri, file_path, BANKA_EKSTRESI)
    except (OSError, OkunamayanDosya):
        return None
    if tablo is None or not tablo.satirlar:
        return None
    return _try_parse_csv(standart_csv(tablo, BANKA_EKSTRESI)[0], atlanan)
