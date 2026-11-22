"""Tabular rows to transactions: bank statements, account-coded ledgers and uploaded CSVs.

Moved out of app/agents/data_ingestion.py unchanged (plan v11 A0.3); that module
re-exports what its callers import from it.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from app.core import tdhp
from app.core.turkish import fold
from app.parsers.base import ParsedStatement
from app.parsers.direction import (
    AMOUNT_COLUMNS,
    CREDIT_ALIASES,
    DEBIT_ALIASES,
    FileDirection,
    RowDirection,
    header_signature,
    is_summary_phrase,
    norm_header,
    parse_money,
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
from app.services.ingest.currencies import is_currency_code
from app.services.ingest.okuma import ReadLedger

logger = logging.getLogger(__name__)


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
            # A matched row whose amount could not be read is held, never booked at 0.
            **({"zero_amount": True} if not tx.amount_cents else {}),
            # A line that looked like money and that no row pattern took: held with its raw text.
            **({"line_unreadable": True} if tx.unread else {}),
            **({"amount_uncertain": True} if tx.amount_uncertain else {}),
        })
    return transactions


def _pdf_yonu(
    transactions: list[dict[str, Any]], bank: str, raw_text: str, ambiguous: bool = False,
) -> str:
    """Text-parsed statements get the same checks as tables: the balance verifies the directions the
    parser read (and reads them when it could not), and a statement nothing can place is held whole.

    Returns whether the running balance chain verified the statement: "verified" (three or more steps, 90%
    reconcile) or "unverified". The upload summary says which; an unverified statement is never presented as
    reconciled.
    """
    from app.parsers.direction import settle_rows, verdict

    state = verdict(
        [r.get("amount_cents") for r in transactions],
        [r["type"] if r.get("type") in ("income", "expense") else None for r in transactions],
        [r.get("balance_cents") for r in transactions], min_steps=3,
    )
    identity = statement_identity(raw_text)
    hold = settle_rows(transactions, f"{bank}||{identity}", ambiguous=ambiguous, identity=bool(identity))
    if hold is not None:
        key = hashlib.sha1(raw_text.encode("utf-8", "ignore")).hexdigest()[:16]
        for n, tx in enumerate(transactions):
            tx["direction_file"] = {
                "key": key, "signature": hold["signature"], "reason": hold["reason"],
                "read": tx.pop("direction_read", None), "balance": tx.pop("direction_balance", None),
            }
            if n == 0:
                tx["direction_question"] = hold["question"]
    return "verified" if state == "confirmed" and hold is None else "unverified"


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
    return code if len(code) == 3 and code.isalpha() and is_currency_code(code) else None


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
    stated = _ilk(r_lower, "currency", "para birimi", "doviz", "doviz cinsi", "pb").strip()
    if stated and tx["currency"] is None:
        # The row STATES a currency that cannot be read ("XXX", "US$1"): it is held with what it said and the
        # organisation's base currency is never put in its place (only a currency nobody stated may follow that rule).
        tx["currency_unreadable"] = stated[:20]
    if hesap is not None:
        raw_amt = _ilk(r_lower, "amount", "tutar") or "0"
        borc, alacak = _kolon(r_lower, DEBIT_ALIASES), _kolon(r_lower, CREDIT_ALIASES)
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
    if yon.amount_cents == 0:
        tx["zero_amount"] = True           # a meaningless row is held, never booked at 0
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
    ledger: ReadLedger | None = None, count_read: bool = True,
) -> list[dict[str, Any]] | None:
    """Attempt deterministic CSV parsing if the text is structured CSV.

    Returns None when the text is not a statement table (the next reader may try), a list otherwise: an
    empty list means a statement was read and every row was skipped (and counted in `ledger`).

    A row naming a transfer or closing account (7x1, 690/692) is not read — it
    moves what is already counted — and is reported in `atlanan` instead.
    The direction of every other row comes from `app.parsers.direction`: one
    resolver for every upload path, and a file it cannot place is held whole,
    with one question for the file (`direction_file` / `direction_question`).

    Every row handed to this function leaves it by exactly one named bucket of `ledger`
    (app.services.ingest.okuma): emitted, blank, summary_skipped or account_skipped.
    """
    import csv
    import io

    ledger = ledger if ledger is not None else ReadLedger()
    headers: list[str] = []
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
        rows: list[dict[str, str]] = []
        malformed: dict[int, list[str]] = {}
        yielded = 0
        for row in reader:
            yielded += 1
            if not row or not any(row.values()):
                ledger.blank += 1
                continue
            # Cells beyond the header's width mean the row's columns are misaligned (an unquoted delimiter).
            if extra := [str(x).strip() for x in (row.get(None) or []) if str(x).strip()]:
                malformed[len(rows)] = extra
            rows.append({fold(k.strip()): (v.strip() if v else "") for k, v in row.items() if k})
        if count_read:
            ledger.read += yielded
        uncoded = [i for i, r in enumerate(rows) if not _kodlu_mu(r)]
        # A carried balance or a total line is not a movement: not booked, not held, but its balance anchors
        # the check of the rows around it.
        date_keys = ("date", "tarih", "islem tarihi")
        # A line is a summary line only if it is structurally one: its WHOLE description is a summary phrase
        # and it has no date or carries no amount. "Toplam fatura ödemesi" is a payment. A phrase line that
        # has a date AND an amount is a transaction; if it does not fit the balance chain it is held
        # ("özet satırı olabilir"), never skipped. Every skipped line is counted and listed.
        phrased = {i for i in uncoded if is_summary_phrase(_ozet_metni(rows[i]))}
        notmoves = {
            i for i in phrased
            # no amount: a summary line. An amount but NO date cell at all: a totals row. An amount and a date
            # cell that cannot be read ("31.02.2026") is money with a broken date: a transaction, held.
            if not _tutarli(rows[i]) or not any(ch.isdigit() for ch in _ilk(rows[i], *date_keys))
        }
        suspects = phrased - notmoves
        has_balance = bool(set(names) & {"bakiye", "balance"})
        settled = resolve_file(
            headers, [rows[i] for i in uncoded], frozenset(k for k, i in enumerate(uncoded) if i in notmoves),
            identity or statement_identity(raw_text.split(chr(10), 1)[0]),
            {fold(f.strip()): f.strip() for f in reader.fieldnames if f},
        )
        yonler = dict(zip(uncoded, settled.rows, strict=True))
        transactions: list[dict[str, Any]] = []
        asked = False
        for i, r in enumerate(rows):
            if i in notmoves:
                ledger.skip_summary(_ozet_metni(rows[i]), _ilk(rows[i], *date_keys))
                continue
            tx = _csv_satiri(r, atlanan, yonler.get(i))
            if tx is None:
                ledger.account_skipped += 1
                continue
            if i in suspects and (not has_balance or (yonler.get(i) and yonler[i].mismatch)):
                tx["summary_suspect"] = True
            if i in malformed:
                tx["malformed_row"] = True
                tx["raw_text"] += chr(10) + "[fazlalık hücreler] " + " | ".join(malformed[i])
            if mark := _dosya_isareti(settled, yonler.get(i), raw_text):
                tx["direction_file"] = mark
                if not asked and settled.hold is not None:
                    tx["direction_question"], asked = settled.hold["question"], True
            transactions.append(tx)
        ledger.emitted += len(transactions)
        return transactions
    except Exception as exc:
        # Never swallowed: the file's layout signature and the error type are logged (no cell contents), the
        # summary tells the person another reader took over, and the next reader is tried.
        import traceback

        where = traceback.extract_tb(exc.__traceback__)[-1]
        logger.error(
            "statement reader failed signature=%s error=%s at=%s:%s",
            header_signature(headers) if headers else "?", type(exc).__name__, where.name, where.lineno,
        )
        ledger.reader_failed = True
        return None


def _ozet_metni(row: dict[str, str]) -> str:
    """What names the line: its description, or when that is empty the first cell that says anything
    (exports put "TOPLAM" in the date column of a totals row)."""
    return _ilk(row, "description", "aciklama", "detay") or next((v for v in row.values() if v), "")


def _kolon(r_lower: dict[str, str], aliases: frozenset[str]) -> str:
    """The first non-empty cell of a column whose header is one of these (folded) aliases."""
    return next((v for k, v in r_lower.items() if v and norm_header(k) in aliases), "")


def _tutarli(row: dict[str, str]) -> bool:
    """Whether the row carries a debit, credit or amount that is not zero."""
    for key, cell in row.items():
        if norm_header(key) in AMOUNT_COLUMNS and (m := parse_money(cell)) is not None and m[0]:
            return True
    return False


def _tablo_ekstresi(
    file_path: str, atlanan: list[str] | None = None, ledger: ReadLedger | None = None,
) -> list[dict[str, Any]] | None:
    """The statement table inside a spreadsheet, found under any title rows, as transactions."""
    from app.services.ingest.recognize import standart_csv, tabloyu_sec
    from app.services.ingest.schemas import BANKA_EKSTRESI
    from app.services.ingest.table import OkunamayanDosya

    ledger = ledger if ledger is not None else ReadLedger()
    try:
        with open(file_path, "rb") as f:
            veri = f.read()
        tablo = tabloyu_sec(veri, file_path, BANKA_EKSTRESI)
    except (OSError, OkunamayanDosya):
        return None
    if tablo is None or not tablo.satirlar:
        return None
    from app.parsers.direction import statement_identity as _identity

    # The table reader drops only blank rows and repeated headers, and says how many.
    ledger.read += len(tablo.satirlar) + tablo.bos + tablo.baslik_tekrari
    ledger.blank += tablo.bos
    ledger.header_repeats += tablo.baslik_tekrari
    return _try_parse_csv(
        standart_csv(tablo, BANKA_EKSTRESI)[0], atlanan, _identity(tablo.ust_metin), ledger, count_read=False,
    )
