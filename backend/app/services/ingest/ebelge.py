"""GİB e-belgeler to transactions: e-Fatura / e-Arşiv (UBL-TR) and e-Müstahsil / e-SMM receipts.

Moved out of app/agents/data_ingestion.py unchanged (plan v11 A0.3); that module
re-exports what its callers import from it.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("app.agents.data_ingestion")


def _try_parse_ubl_xml(
    raw_text: str, own_vkn: str | None = None
) -> list[dict[str, Any]] | None:
    """Parse Turkish e-Fatura / e-Arşiv UBL-TR 1.2 XML into CFO transactions.

    Whether an invoice is income or expense is read from the direction the
    parser establishes by VKN, not from `InvoiceTypeCode`. The old mapping
    (`invoice_type in ("SATIS", "IHRACAT", "KOMISYON")`) treated one of GİB's
    fourteen real codes as income and thirteen as expense, and two of the three
    codes it listed are not codes GİB issues.

    When the direction cannot be established the rows are still returned — a
    withheld invoice is not a discarded one — but at a confidence that keeps
    them the other side of the review gate.
    """
    # A substring decides only whether to look; the root element decides what
    # the document is. An earlier version sent anything containing the word
    # "CreditNote" to the receipt parser — which GİB's own e-Arşiv sale does,
    # in a reference — and the invoice was dropped as "not a receipt".
    if not any(m in raw_text for m in ("<Invoice", ":Invoice", "CreditNote", "eArsivVeri")):
        return None
    try:
        from app.config import get_settings
        from app.core.financial import amount_to_cents
        from app.parsers.invoice.ubl_tr import NotAnInvoiceError, UBLTRInvoiceParser

        # The organisation's own VKN decides the direction. None means the
        # caller has no organisation in hand (tests, scripts): the global one.
        vkn = get_settings().gib_vkn if own_vkn is None else own_vkn
        try:
            inv = UBLTRInvoiceParser.parse_xml(raw_text, own_vkn=vkn)
        except NotAnInvoiceError as exc:
            # e-Müstahsil is a UBL CreditNote and e-SMM is e-Arşiv data; both
            # used to stop here as "not an invoice, skipped". e-İrsaliye,
            # uygulama yanıtı and the like are neither and are still skipped —
            # they carry no monetary total and once parsed into a 0,00 TL sale.
            logger.info("UBL belgesi fatura değil, makbuz olarak deneniyor: %s", exc)
            return _try_parse_makbuz(raw_text, own_vkn)

        is_income = inv.direction == "sale"
        tx_type = "income" if is_income else "expense"
        # "sales" is not in _CATEGORY_MAP; the vocabulary's income term is
        # "revenue". Every other producer uses _guess_category, which can
        # only return a known category — this line was the one that could
        # not, so nothing downstream recognised what it emitted.
        category = "revenue" if is_income else "cogs"
        counterparty = (
            inv.customer.title if is_income else (inv.supplier.title or "Tedarikçi")
        )

        amount_cents = amount_to_cents(
            inv.payable_amount or inv.tax_inclusive_total or inv.line_extension_total
        )

        # Direction settled by VKN is as certain as a structured parser gets.
        # `needs_review` covers more than direction: a foreign currency with no
        # rate, or tax components that do not reach the invoice's own total,
        # also mean we did not understand the document well enough to book it.
        confidence = 0.4 if inv.needs_review else 0.95
        note = f" | Yön: {inv.direction} ({inv.direction_basis})"
        if inv.posting_note:
            note += f" | Kayıt üretilmedi: {inv.posting_note}"

        # The invoice states its KDV; carry it so the journal splits it rather
        # than holding the entry as "no rate in the source". Only when nothing
        # else is in play: withheld KDV and other taxes (ÖTV…) change which
        # part of the payable the KDV is, and the engine does not model them.
        from decimal import Decimal

        from app.parsers.invoice.ubl_tr import KDV_TAX_CODE

        only_kdv = all(
            t.tax_category_code == KDV_TAX_CODE for t in inv.tax_subtotals if t.tax_amount
        )
        kdv_cents = (
            abs(amount_to_cents(sum(
                (t.tax_amount for t in inv.tax_subtotals if t.tax_category_code == KDV_TAX_CODE),
                Decimal("0"),
            )))
            if not inv.needs_review and only_kdv and not inv.withholding_tax_amount
            else None
        )

        return [{
            "amount_cents": abs(amount_cents),
            "kdv_cents": kdv_cents,
            "currency": inv.currency_code or "TRY",
            "type": tx_type,
            "category": category,
            "description": f"e-Fatura {inv.invoice_number}: {counterparty}",
            "vendor": counterparty if not is_income else None,
            "transaction_date": inv.issue_date.isoformat() if inv.issue_date else None,
            "raw_text": (
                f"UUID: {inv.invoice_uuid} | No: {inv.invoice_number} "
                f"| Type: {inv.invoice_type}{note}"
            ),
            "confidence": confidence,
            # A cash plan's raw material. Only when we know which side we are
            # on: without that nobody can be said to owe anybody.
            "document_id": None if inv.invoice_uuid == "N/A" else inv.invoice_uuid,
            "due_date": inv.payment_due_date.isoformat() if inv.payment_due_date else None,
            "payment_note": inv.payment_note or None,
            "counterparty": counterparty if inv.direction in ("sale", "purchase") else None,
        }]
    except Exception as exc:
        # Was logged at debug. A NameError in this function turned every
        # uploaded e-Fatura into "no transactions" with nothing in the log at
        # the default level — the test for it is the only reason it was seen.
        logger.warning("UBL-TR ayrıştırılamadı, fatura atlandı: %s", exc, exc_info=True)
        return None


def _try_parse_makbuz(
    raw_text: str, own_vkn: str | None = None
) -> list[dict[str, Any]] | None:
    """e-Müstahsil / e-SMM into one CFO transaction, held when not understood.

    Same contract as the invoice path: the side we are on is settled by VKN,
    and a receipt the parser could not post still comes back as a row — at a
    confidence that keeps it behind the review gate, with the reason attached.
    """
    try:
        from app.config import get_settings
        from app.core.financial import amount_to_cents
        from app.parsers.invoice.makbuz import NotAMakbuzError, parse_makbuz

        try:
            m = parse_makbuz(
                raw_text, own_vkn=get_settings().gib_vkn if own_vkn is None else own_vkn
            )
        except NotAMakbuzError as exc:
            logger.info("e-Arşiv belgesi müstahsil/SMM değil, atlandı: %s", exc)
            return None

        is_income = m.direction == "sale"
        label = "e-Müstahsil" if m.kind == "mustahsil" else "e-SMM"
        if is_income:
            category = "revenue"
        else:
            category = "cogs" if m.kind == "mustahsil" else "other_expense"
        other = m.payer if is_income else m.payee
        note = f" | Yön: {m.direction} ({m.direction_basis})"
        if m.stopaj:
            note += f" | Stopaj: {m.stopaj}"
        if m.posting_note:
            note += f" | Kayıt üretilmedi: {m.posting_note}"

        who = other.title or other.vkn_tckn or "karşı taraf"
        what = f" — {m.items[0]}" if m.items else ""
        understood = bool(m.suggested_tdhp_entries)
        return [{
            # What changes hands. Stopaj is paid to the tax office by the payer,
            # so it is not part of this movement.
            "amount_cents": abs(amount_to_cents(m.payable or m.gross)),
            # The document states both; the journal needs both to book the fee
            # at its gross and the tax where it belongs. Carried only when the
            # receipt was understood — otherwise the entry is held, not split.
            "kdv_cents": abs(amount_to_cents(m.kdv)) if understood else None,
            "stopaj_cents": abs(amount_to_cents(m.stopaj)) if understood else None,
            "currency": m.currency or "TRY",
            "type": "income" if is_income else "expense",
            "category": category,
            "description": f"{label} {m.number}: {who}{what}",
            # e-SMM data carries the professional's VKN but not their name.
            "vendor": None if is_income else who,
            "transaction_date": m.issue_date.isoformat() if m.issue_date else None,
            "raw_text": f"UUID: {m.uuid} | No: {m.number} | Tür: {label}{note}",
            "confidence": 0.4 if m.needs_review else 0.95,
        }]
    except Exception as exc:
        logger.warning("e-Müstahsil/e-SMM ayrıştırılamadı: %s", exc)
        return None
