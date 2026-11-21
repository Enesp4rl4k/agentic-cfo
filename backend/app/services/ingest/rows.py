"""Tabular rows to transactions: bank statements, account-coded ledgers and uploaded CSVs.

Moved out of app/agents/data_ingestion.py unchanged (plan v11 A0.3); that module
re-exports what its callers import from it.
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.core import tdhp
from app.core.turkish import fold
from app.parsers.base import ParsedStatement
from app.parsers.direction import (
    AMOUNT_COLUMNS,
    FileDirection,
    RowDirection,
    is_non_transaction,
    norm_header,
    resolve_file,
    signed_money,
    statement_identity,
)
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
            # "" = the document did not say; resolved or held by app.services.ingest.hold.
            "currency": tx.currency or None,
            # "" = the parser could not place the direction: held, never defaulted.
            "type": tx.tx_type or None,
            "category": (
                _kodlu_kategori(hesap, tx.description) if hesap is not None
                else _guess_category(tx.description, tx.tx_type) if tx.tx_type
                else None   # chosen once a person gives the direction
            ),
            "account_code": tx.account_code,
            "description": tx.description,
            "vendor": tx.vendor,
            "transaction_date": (
                tx.date.isoformat() if tx.date and not tx.date_estimated else None
            ),
            "raw_text": (
                f"{tx.raw_row}\n[yön] {tx.confidence_note}"
                if tx.confidence_note else tx.raw_row
            ),
            # Structured parsers are high-confidence about the *rows*; they are
            # not automatically right about which way the money went. A parser
            # that knows better says so, and only then does this cap apply.
            # None stays None: a row nobody scored is unknown, not 0.95.
            "confidence": None if tx.confidence is None else min(0.95, tx.confidence),
            # Not money moved: the bank's own running total, which proves the
            # balance the statement closes on (app.services.bank_balance).
            "balance_cents": tx.balance_cents,
        })
    return transactions


def _pdf_yonu(transactions: list[dict[str, Any]], bank: str, raw_text: str) -> None:
    """Text-parsed statements get the same checks as tables: the balance verifies the directions the
    parser read (and reads them when it could not), and a statement nothing can place is held whole."""
    from app.parsers.direction import settle_rows

    hold = settle_rows(transactions, bank)
    if hold is None:
        return
    key = hashlib.sha1(raw_text.encode("utf-8", "ignore")).hexdigest()[:16]
    for n, tx in enumerate(transactions):
        tx["direction_file"] = {
            "key": key, "signature": hold["signature"], "reason": hold["reason"],
            "read": tx.pop("direction_read", None), "balance": tx.pop("direction_balance", None),
        }
        if n == 0:
            tx["direction_question"] = hold["question"]


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


_PARA_BIRIMI_TAKMA_ADLARI = {"TL": "TRY", "TRL": "TRY", "₺": "TRY", "$": "USD", "€": "EUR", "£": "GBP"}


def _para_birimi(raw: str) -> str | None:
    """An ISO-4217 code from a currency cell; None for an empty or unreadable one."""
    code = raw.strip().upper()
    code = _PARA_BIRIMI_TAKMA_ADLARI.get(code, code)
    return code if len(code) == 3 and code.isalpha() else None


def _kodlu_mu(r_lower: dict[str, str]) -> bool:
    """A row whose account the map knows: the account decides its direction (`_hesap_kodlu_satir`)."""
    code = tdhp.ana_hesap(_ilk(r_lower, *_HESAP_KODU_KOLONLARI))
    return bool(code) and tdhp.hesap(code) is not None


def _csv_satiri(
    r_lower: dict[str, str], atlanan: list[str] | None, yon: RowDirection | None = None,
) -> dict[str, Any] | None:
    """One statement row (headers folded) as a pipeline transaction; None for a skipped row.

    `yon` is what `app.parsers.direction` settled for a row without a known account: its
    direction (None = held), its amount (None = unreadable), and why.
    """
    raw_desc = _ilk(r_lower, "description", "aciklama", "detay")
    raw_cat = _ilk(r_lower, "category", "kategori")
    account_code = tdhp.ana_hesap(_ilk(r_lower, *_HESAP_KODU_KOLONLARI))
    hesap = tdhp.hesap(account_code) if account_code else None
    parsed_dt = _parse_date(_ilk(r_lower, "date", "tarih", "islem tarihi"))
    tx: dict[str, Any] = {
        # What the row's own column says; None when it says nothing, and the
        # document's header or the organisation's base currency (marked as
        # assumed) is applied by the caller (app.services.ingest.hold). It used
        # to be "TRY" whatever the file held.
        "currency": _para_birimi(_ilk(r_lower, "currency", "para birimi", "doviz", "doviz cinsi", "pb")),
        "description": raw_desc,
        "vendor": _ilk(r_lower, "vendor", "tedarikci") or raw_desc,
        "transaction_date": parsed_dt.isoformat() if parsed_dt else None,
        "raw_text": str(r_lower),
        "account_code": account_code,
        # A code this map does not know is an income-statement account nobody
        # has classified: the row is read by its words and its sign, and says so.
        "confidence": 0.6 if account_code and hesap is None else 0.95,
    }
    if hesap is not None:
        raw_amt = _ilk(r_lower, "amount", "tutar") or "0"
        borc, alacak = r_lower.get("borc", ""), r_lower.get("alacak", "")
        satir = _hesap_kodlu_satir(hesap, borc, alacak, raw_amt, raw_desc, raw_cat)
        if satir is None:
            if atlanan is not None:
                atlanan.append(f"{account_code} {raw_desc}".strip())
            return None
        tx["type"], tx["amount_cents"], tx["category"] = satir
        return tx

    if yon is None:
        raise ValueError("a row without a known account needs its settled direction")
    tx["type"] = yon.type
    tx["amount_cents"] = yon.amount_cents
    if yon.mismatch:
        tx["balance_mismatch"] = True      # its balance step does not reconcile: held on its own
    if yon.note:
        tx["raw_text"] += f"\n[yön] {yon.note}"
    if yon.type is None:
        # The category depends on the direction a person is yet to give: it is chosen when they do.
        tx["category"], tx["category_hint"] = None, raw_cat
    else:
        tx["category"] = _yukleyenin_kategorisi(raw_cat, raw_desc, yon.type)
    _fatura_alanlari(tx, r_lower)
    bakiye = signed_money(_ilk(r_lower, "bakiye", "balance"))
    if bakiye is not None:
        tx["balance_cents"] = bakiye
    return tx


def _dosya_isareti(settled: FileDirection, yon: RowDirection | None, raw_text: str) -> dict[str, Any] | None:
    """What a row of a file held whole carries: which file, why, and what the columns / the balance said."""
    if settled.hold is None or yon is None:
        return None
    return {
        "key": hashlib.sha1(raw_text.encode("utf-8", "ignore")).hexdigest()[:16],
        "signature": settled.hold["signature"], "reason": settled.hold["reason"],
        "identity": settled.hold.get("identity", False),
        "read": yon.read, "balance": yon.balance,
    }


def _try_parse_csv(
    raw_text: str, atlanan: list[str] | None = None, identity: str = "",
) -> list[dict[str, Any]] | None:
    """Attempt deterministic CSV parsing if the text is structured CSV.

    A row naming a transfer or closing account (7x1, 690/692) is not read — it
    moves what is already counted — and is reported in `atlanan` instead.
    The direction of every other row comes from `app.parsers.direction`: one
    resolver for every upload path, and a file it cannot place is held whole,
    with one question for the file (`direction_file` / `direction_question`).
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
        headers = [fold(f.strip()) for f in reader.fieldnames if f]
        names = {norm_header(h) for h in headers}
        if not ((set(headers) & set(_TUTAR_KOLONLARI) or names & AMOUNT_COLUMNS)
                and set(headers) & set(_TARIH_KOLONLARI)):
            return None
        rows = [
            {fold(k.strip()): (v.strip() if v else "") for k, v in row.items() if k}
            for row in reader if row and any(row.values())
        ]
        uncoded = [i for i, r in enumerate(rows) if not _kodlu_mu(r)]
        # A carried balance or a total line is not a movement: not booked, not held, but its balance anchors
        # the check of the rows around it.
        desc = ("description", "aciklama", "detay")
        notmoves = {i for i in uncoded if is_non_transaction(_ilk(rows[i], *desc))}
        settled = resolve_file(
            headers, [rows[i] for i in uncoded], frozenset(k for k, i in enumerate(uncoded) if i in notmoves),
            identity or statement_identity(raw_text.split(chr(10), 1)[0]),
        )
        yonler = dict(zip(uncoded, settled.rows, strict=True))
        transactions: list[dict[str, Any]] = []
        asked = False
        for i, r in enumerate(rows):
            if i in notmoves:
                continue
            tx = _csv_satiri(r, atlanan, yonler.get(i))
            if tx is None:
                continue
            if mark := _dosya_isareti(settled, yonler.get(i), raw_text):
                tx["direction_file"] = mark
                if not asked and settled.hold is not None:
                    tx["direction_question"], asked = settled.hold["question"], True
            transactions.append(tx)
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
    from app.parsers.direction import statement_identity as _identity

    return _try_parse_csv(standart_csv(tablo, BANKA_EKSTRESI)[0], atlanan, _identity(tablo.ust_metin))
