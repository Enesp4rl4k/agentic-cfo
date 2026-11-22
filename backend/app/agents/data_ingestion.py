"""
Data Ingestion Agent — Skill 1 of 5.

Responsibility: Read the uploaded file (PDF/Excel/CSV), extract raw text
and structured transactions, persist them to the DB.

Parse strategy (fast → slow):
  1. Bank-specific parser (ParserRegistry.detect) — rule-based, free, fast
  2. LLM extraction (_extract_transactions_with_llm) — fallback only

Confidence signals:
- 1.0  → all transactions parsed with vendor + amount + date
- 0.85 → some fields missing but majority parseable
- 0.60 → low-quality OCR or too many unparseable rows → triggers review gate
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

from app.agents.state import AgentRunConfig, CFOState, SkillResult
from app.config import get_settings
from app.core import tdhp
from app.core.row_confidence import parse_confidence
from app.parsers.base import ParsedStatement
from app.parsers.invoice import TurkishInvoiceParser
from app.parsers.registry import ParserRegistry
from app.services.ingest.categories import (
    _CATEGORY_MAP,
    CATEGORY_KEYWORDS,
    KNOWN_CATEGORIES,
    _guess_category,
    tur_kategori_celiskisi,
)
from app.services.ingest.cells import (
    _detect_currency,
    _parse_amount,
    _parse_date,
)
from app.services.ingest.door import read_document, read_text_statement
from app.services.ingest.ebelge import (
    _try_parse_ubl_xml,
)
from app.services.ingest.hold import resolve_currency, split_uncertain
from app.services.ingest.okuma import ReadLedger, merge_counts, reconcile
from app.services.ingest.readers import (
    _pdf_embedded_xml,
    _read_csv,
    _read_excel,
    _read_pdf,
    _read_xml,
)
from app.services.ingest.rows import (
    _pdf_yonu,
    _statement_to_transactions,
    _tablo_ekstresi,
    _try_parse_csv,
)

logger = logging.getLogger(__name__)

# Callers (and tests) import these from here; the parsing itself lives in app/services/ingest.
__all__ = [
    "CATEGORY_KEYWORDS",
    "KNOWN_CATEGORIES",
    "_CATEGORY_MAP",
    "_detect_currency",
    "_guess_category",
    "_parse_amount",
    "_parse_date",
    "_pdf_embedded_xml",
    "_pdf_yonu",
    "_read_csv",
    "_read_excel",
    "_read_pdf",
    "_read_xml",
    "_statement_to_transactions",
    "_tablo_ekstresi",
    "_try_parse_csv",
    "_try_parse_ubl_xml",
    "run_data_ingestion",
    "tur_kategori_celiskisi",
]



async def _extract_transactions_with_llm(
    raw_text: str, settings
) -> list[dict[str, Any]]:
    """
    Use LLM (DeepSeek / OpenAI compatible) to extract structured transactions.
    Returns list of dicts: date, amount, type, description, vendor, confidence.
    """
    from app.platform.model_gateway import LLMUnavailable, complete_text

    system = (
        "You are a financial data extraction specialist. "
        "Extract all financial transactions from the provided document text as a JSON array.\n"
        "For each transaction include:\n"
        "- date: transaction date (DD.MM.YYYY or YYYY-MM-DD)\n"
        "- amount: numeric amount (no currency symbol)\n"
        "- type: 'income' or 'expense'\n"
        "- description: transaction description\n"
        "- vendor: supplier or customer name (null if unknown)\n"
        "- currency: ISO-4217 code only if the document states it, otherwise null\n"
        "- confidence: confidence score 0-1 for this extraction (null if you cannot tell)\n\n"
        "Respond with ONLY a valid JSON array. No explanation, no markdown.\n"
        'Example: [{"date": "15.03.2024", "amount": 1500.00, "type": "expense", '
        '"description": "Electricity bill", "vendor": "City Power Co.", "confidence": 0.95}]'
    )
    import json
    try:
        content = (await complete_text(
            task="simple_extraction",
            system_prompt=system,
            prompt=f"Document text:\n\n{raw_text[:8000]}",
            temperature=0.0,
            max_tokens=4096,
        )).strip()
    except LLMUnavailable:
        return []
    if content.startswith("```"):
        content = re.sub(r"^```[a-z]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
    return json.loads(content)


def _csv_sonucu(
    csv_txs: list[dict[str, Any]], raw_text: str, job_id: Any, atlanan: list[str] | None = None,
    ledger: ReadLedger | None = None,
) -> SkillResult:
    if not csv_txs:
        # A statement was read and every row of it was a summary or transfer line: said, not passed on silently.
        skipped = (ledger.summary_skipped + ledger.account_skipped) if ledger else 0
        return SkillResult(
            ok=False, needs_review=True, confidence=0.0,
            detail=f"{ledger.read if ledger else 0} satır okundu, {skipped} özet/geçiş satırı atlandı; işlenecek kayıt yok.",
        )
    # Confidence must reflect data quality: rows with an unparseable
    # date or a zero amount are only partially usable. A file where
    # most dates failed to parse should NOT sail through the gate.
    # (A correction posted to an account carries a negative amount.)
    well_formed = sum(
        1 for tx in csv_txs
        if tx.get("transaction_date") and (tx.get("amount_cents") or 0) != 0
    )
    ratio = well_formed / len(csv_txs)
    overall_confidence = 0.95 if ratio >= 0.9 else (0.78 if ratio >= 0.6 else 0.5)
    # What a person has to look at: income-statement accounts the map does not
    # know (read by their words), rows whose category contradicts their
    # direction, and transfer/closing postings that were left out.
    tanimsiz = sorted({
        str(t["account_code"]) for t in csv_txs
        if t.get("account_code") and tdhp.hesap(t["account_code"]) is None
    })
    celisen = tur_kategori_celiskisi(csv_txs)
    notlar = [f"{well_formed} well-formed, confidence={overall_confidence:.2f}"]
    if tanimsiz:
        notlar.append(f"unmapped accounts {', '.join(tanimsiz)}")
    if celisen:
        notlar.append(f"{len(celisen)} rows whose category contradicts their direction")
    if atlanan:
        notlar.append(f"{len(atlanan)} transfer/closing postings not read")
    logger.info(
        "job=%s — deterministic CSV parser: %d transactions (%s)",
        job_id, len(csv_txs), "; ".join(notlar),
    )
    return SkillResult(
        ok=True,
        patch={"raw_text": raw_text, "transactions": csv_txs},
        confidence=overall_confidence,
        needs_review=overall_confidence < 0.80 or bool(tanimsiz or celisen or atlanan),
        detail=f"Parsed {len(csv_txs)} transactions via CSV parser ({'; '.join(notlar)})",
    )


def _yevmiye_sonucu(raw_text: str) -> SkillResult:
    """An e-Defter journal read on the accrual basis (owner's choice, 2026-09-27).

    Only the income statement is taken: 6xx and, under 7/A, the 7x0 cost
    accounts; transfer and closing entries are skipped so nothing counts twice.
    An income-statement account the map does not know holds the run for a
    person instead of being guessed.
    """
    from app.parsers.edefter.yevmiye import NotAJournal, yevmiye_oku

    try:
        sonuc = yevmiye_oku(raw_text.encode("utf-8"))
    except NotAJournal as exc:
        return SkillResult(
            ok=False, needs_review=True, confidence=0.0,
            detail=f"e-Defter belgesi yevmiye değil ({exc.tur}); gelir tablosu için yevmiye defteri gerekir.",
        )
    ozet = (f"e-Defter yevmiye: {sonuc.kayit_sayisi} kayıt, {len(sonuc.islemler)} gelir tablosu "
            f"satırı (tahakkuk esası); {sonuc.atlanan_kayit} yansıtma/kapanış kaydı atlandı.")
    if not sonuc.islemler:
        return SkillResult(ok=False, needs_review=True, confidence=0.0,
                           detail=ozet + " Gelir ya da gider hesabına kayıt yok.")
    tanimsiz = sonuc.tanimsiz_hesaplar
    return SkillResult(
        ok=True,
        patch={"raw_text": raw_text[:_EN_FAZLA_METIN], "transactions": sonuc.islemler},
        confidence=0.95 if not tanimsiz else 0.6,
        needs_review=bool(tanimsiz),
        detail=ozet + (f" Tanınmayan gelir tablosu hesapları: {', '.join(tanimsiz)} — "
                       "bu kayıtlar okunmadı, lütfen kontrol edin." if tanimsiz else ""),
    )


async def run_data_ingestion(
    state: CFOState, config: AgentRunConfig
) -> SkillResult:
    """
    Data Ingestion Skill.
    done_when: state['transactions'] is a non-empty list.

    One analysis can hold several documents: a month of e-Fatura XMLs dropped
    together is one analysis, not one per file. Each is read by
    `_belgeyi_al` below and the transactions are put together; the confidence
    is the lowest of them and a review needed for one is a review for the run.
    """
    ledger = state.get("ledger_view")
    if ledger is not None:
        # Rows the company's ledger already holds: nothing to parse, so nothing
        # uncertain here. A row awaiting a person is not among them, and the
        # verifier and the gate still judge what is computed from these.
        return SkillResult(
            ok=True,
            patch={"raw_text": "", "transactions": ledger["profit"]},
            confidence=1.0,
            detail=f"Defterden {len(ledger['profit'])} satır okundu.",
        )

    sonuc = _uncertain_rows_wait(await _read_all_documents(state, config))
    if sonuc.patch:  # one document: its header may state its period; a feed's job carries its pull as metadata
        from app.services.stated_period import attach_periods

        sonuc.patch = await attach_periods(sonuc.patch, state)
    return sonuc


def _counts_reconcile(sonuc: SkillResult, accepted: int, held: int) -> SkillResult:
    """Every row the readers were handed is booked, held, or skipped and counted (app.services.ingest.okuma).

    The equation is computed here, by the ingest step itself, and stored with the counts (`ingest.summary`).
    If it does not hold the run is marked for review: "N satır hesaba katılamadı". Never silent.
    """
    counts, lost = reconcile(sonuc.patch.get("ingest_counts") if sonuc.patch else None, accepted, held)
    if counts is None:
        return sonuc
    patch = {**(sonuc.patch or {}), "ingest_counts": counts}
    if not lost:
        return SkillResult(sonuc.ok, patch, sonuc.confidence, sonuc.needs_review, sonuc.halt, sonuc.detail)
    return SkillResult(sonuc.ok, patch, sonuc.confidence, True, sonuc.halt, f"{lost} satır hesaba katılamadı. {sonuc.detail}")


def _uncertain_rows_wait(sonuc: SkillResult) -> SkillResult:
    """Rows a person must look at leave the run; the rest carry on.

    A row with no confidence (None, never a made-up number), a confidence under
    the bar, or no currency waits in `held_transactions`, together with the rest
    of its document (app.services.ingest.hold). The run is held as a whole only
    for what is wrong with the file itself (`needs_review` from the parsers) or
    when nothing is left to analyse.
    """
    rows = list((sonuc.patch or {}).get("transactions") or [])
    if not sonuc.ok or not rows:
        return sonuc
    accepted, held = split_uncertain(rows)
    sonuc = _counts_reconcile(sonuc, len(accepted), len(held))
    if not held:
        return sonuc
    # Which rows wait for a person does not change what the bank says the account holds:
    # the running balances are proven over the whole file, in file order, before it is split.
    from app.services.bank_balance import closing_balance, statement_extent

    closing = closing_balance(rows)
    whole = {"statement_closing_balance": closing} if closing is not None else {}
    if (extent := statement_extent(rows)) is not None:
        whole["statement_extent"] = extent
    waiting = f"{len(held)} kayıt incelemenizi bekliyor"
    if not accepted:
        return SkillResult(
            ok=False, needs_review=True, confidence=0.0,
            patch={**(sonuc.patch or {}), **whole, "transactions": [], "held_transactions": held},
            detail=f"0 kayıt işlendi, {waiting}. {sonuc.detail}",
        )
    known = [c for c in (parse_confidence(r.get("confidence")) for r in accepted) if c is not None]
    return SkillResult(
        ok=True,
        patch={**(sonuc.patch or {}), **whole, "transactions": accepted, "held_transactions": held},
        confidence=min([sonuc.confidence, *known]),
        needs_review=sonuc.needs_review,
        detail=f"{len(accepted)} kayıt işlendi, {waiting}. {sonuc.detail}",
    )


async def _read_all_documents(state: CFOState, config: AgentRunConfig) -> SkillResult:
    sonuc = await _belgeyi_al(
        state.get("file_path", ""), state.get("file_type", ""), state, config,
    )
    ekler = list(state.get("ek_belgeler") or [])
    if not ekler:
        return sonuc

    islemler: list[dict[str, Any]] = list((sonuc.patch or {}).get("transactions") or [])
    metinler: list[str] = [str((sonuc.patch or {}).get("raw_text") or "")]
    detaylar: list[str] = [f"1) {sonuc.detail}"]
    sayimlar = (sonuc.patch or {}).get("ingest_counts")
    guven = sonuc.confidence if sonuc.ok else 1.0
    inceleme = bool(sonuc.needs_review)

    for i, ek in enumerate(ekler, start=2):
        alt = await _belgeyi_al(ek.get("path", ""), ek.get("type", ""), state, config)
        ad = ek.get("ad") or ek.get("path", "")
        detaylar.append(f"{i}) {ad}: {alt.detail}")
        if alt.ok:
            islemler.extend((alt.patch or {}).get("transactions") or [])
            sayimlar = merge_counts(sayimlar, (alt.patch or {}).get("ingest_counts"))
            metinler.append(str((alt.patch or {}).get("raw_text") or ""))
            guven = min(guven, alt.confidence)
            inceleme = inceleme or bool(alt.needs_review)
        else:
            # A document that could not be read does not discard the others,
            # but the run is held so a person sees which one failed.
            inceleme = True
            guven = min(guven, 0.5)

    if not islemler:
        return SkillResult(ok=False, needs_review=True, confidence=0.0,
                           detail=f"{len(ekler) + 1} belgenin hiçbirinden işlem çıkarılamadı. "
                                  + " | ".join(detaylar))
    return SkillResult(
        ok=True,
        patch={"raw_text": _BELGE_ARASI.join(t for t in metinler if t)[:_EN_FAZLA_METIN],
               "transactions": islemler, **({"ingest_counts": sayimlar} if sayimlar else {})},
        confidence=guven,
        needs_review=inceleme,
        detail=f"{len(ekler) + 1} belge, {len(islemler)} işlem. " + " | ".join(detaylar),
    )


# Several documents' text is kept for the audit trail and RAG indexing, capped
# so a batch of invoices cannot grow the state without bound.
_EN_FAZLA_METIN = 400_000
_BELGE_ARASI = "\n\n"


async def _belgeyi_al(
    file_path: str, file_type: str, state: CFOState, config: AgentRunConfig
) -> SkillResult:
    """One document, with every row's currency settled (see app.services.ingest.hold)."""
    ledger = ReadLedger()
    sonuc = await _belgeyi_oku(file_path, file_type, state, config, ledger)
    if ledger.touched:
        # The counts travel in the result, never on a row: they survive a file whose rows were all skipped.
        sonuc.patch = {**(sonuc.patch or {}), "ingest_counts": ledger.as_dict()}
    rows = (sonuc.patch or {}).get("transactions") or []
    if any(r.get("direction_file") for r in rows):
        # A statement format this organisation already answered is not asked again.
        from app.database import session_factory
        from app.services.held_direction import apply_remembered

        async with session_factory()() as db:
            await apply_remembered(db, state.get("org_id"), rows)
    if sonuc.ok and any(not str(r.get("currency") or "").strip() for r in rows):
        from app.services.org_identity import own_base_currency

        resolve_currency(
            rows, str((sonuc.patch or {}).get("raw_text") or ""),
            await own_base_currency(state.get("org_id")),
        )
    return sonuc


async def _belgeyi_oku(
    file_path: str, file_type: str, state: CFOState, config: AgentRunConfig, ledger: ReadLedger | None = None,
) -> SkillResult:
    """One document: read it, then parse by the strategies below.

    Strategy:
      1. Read raw text from file (PDF / Excel / CSV / XML)
      2. Try ParserRegistry (bank-specific rule-based parsers) — fast, free
      3. If no bank match → fall back to LLM extraction
    """
    settings = get_settings()
    ledger = ledger if ledger is not None else ReadLedger()

    if not os.path.exists(file_path):
        return SkillResult(ok=False, detail=f"File not found: {file_path}", halt=True)

    # Reading and parsing are synchronous CPU and disk work over the whole
    # file. They run in a thread: on the event loop a large statement stopped
    # the API answering anyone else until it was read.
    readers = {"pdf": _read_pdf, "xlsx": _read_excel, "xls": _read_excel, "csv": _read_csv, "xml": _read_xml}
    try:
        if file_type not in readers:
            return SkillResult(ok=False, detail=f"Unsupported file type: {file_type}", halt=True)
        raw_text = await asyncio.to_thread(readers[file_type], file_path)

        if not raw_text.strip():
            return SkillResult(
                ok=False,
                detail="Could not extract any text from the file.",
                needs_review=True,
                confidence=0.0,
            )

        # ── Strategy 1.2: an e-Belge carried inside a PDF ────────────────────
        # GİB delivers e-SMM as a PAdES-signed PDF with the receipt data
        # attached as XML (e-Arşiv Kılavuzu §7), and integrators ship e-Fatura
        # and e-Arşiv the same way. The page text of such a PDF is a rendering;
        # the attachment is the document. Reading only the text meant the data
        # GİB made the payer's copy of record was never looked at.
        if file_type == "pdf":
            embedded = await asyncio.to_thread(_pdf_embedded_xml, file_path)
            if embedded:
                raw_text = embedded[0]

        # ── Strategy 1.2: e-Defter yevmiye — accrual income statement ─────
        # A substring only decides whether to look; the root element decides
        # what the document is (app.parsers.edefter.yevmiye).
        if file_type == "xml" and "edefter.gov.tr" in raw_text[:4000]:
            return _yevmiye_sonucu(raw_text)

        # ── Strategy 1.25: GİB UBL-TR 1.2 / 2.1 e-Fatura / e-Arşiv XML Parser ──
        if (
            file_type == "xml"
            or "<Invoice" in raw_text
            or ":Invoice" in raw_text
            or "CreditNote" in raw_text
            or "eArsivVeri" in raw_text
        ):
            from app.services.org_identity import own_vkn

            ubl_txs = await asyncio.to_thread(
                _try_parse_ubl_xml, raw_text, await own_vkn(state.get("org_id"))
            )
            if ubl_txs:
                # The rows carry their own confidence — an invoice whose
                # direction could not be settled by VKN is not a certainty, and
                # this branch used to assert 1.0 regardless, which is precisely
                # how a backwards posting would reach the ledger unreviewed.
                # (A row without one is unknown, not 0.8: `split_uncertain` holds it.)
                logger.info(
                    "job=%s — UBL-TR XML parser parsed %d invoice transactions",
                    state.get("job_id"), len(ubl_txs),
                )
                return SkillResult(
                    ok=True,
                    patch={"raw_text": raw_text, "transactions": ubl_txs},
                    confidence=0.95,
                    needs_review=False,
                    detail=f"Parsed {len(ubl_txs)} transactions via GİB UBL-TR XML parser",
                )

        # ── Strategy 1.1: a spreadsheet read by its columns ──────────────────
        # Before the bank parsers: they are patterns over PDF text, and matched
        # a bank's name anywhere in the file. A statement exported as a table
        # loses its empty cells when flattened to text, so "Borç" and "Alacak"
        # traded places — and one "AKBANK EFT" line in another bank's CSV sent
        # the whole file through Akbank's pattern. A table is read as a table.
        if file_type in ("csv", "xlsx"):
            atlanan: list[str] = []
            table_txs = await asyncio.to_thread(_tablo_ekstresi, file_path, atlanan, ledger)
            if table_txs is not None:
                return _csv_sonucu(table_txs, raw_text, state.get("job_id"), atlanan, ledger)
            ledger.reset()

        # ── Strategy 1: Bank-specific rule-based parser ────────────────────
        detected_bank = await asyncio.to_thread(ParserRegistry.detect, raw_text)
        if detected_bank is not None:
            logger.info(
                "job=%s — using bank parser: %s",
                state.get("job_id"), detected_bank.bank_display_name,
            )
            parser = detected_bank()
            if issubclass(detected_bank, TurkishInvoiceParser):
                # A PDF/OCR invoice is read against this organisation's own VKN, as the
                # UBL path is, not the deployment's one.
                from app.services.org_identity import own_vkn as org_vkn

                parser = detected_bank(own_vkn=await org_vkn(state.get("org_id")))
            # ONE door (app.services.ingest.door): every line accounted for, a held row for what no pattern took.
            ambiguous = bool(getattr(detected_bank, "debit_credit_layout", False))
            if issubclass(detected_bank, TurkishInvoiceParser):
                door = await asyncio.to_thread(read_document, parser, raw_text, file_path, ambiguous=ambiguous)
            else:
                door = await asyncio.to_thread(read_text_statement, parser, raw_text, file_path, ambiguous=ambiguous)
                ledger.add(door.ledger)
            statement: ParsedStatement = door.statement
            transactions = door.rows

            if transactions:
                parseable = sum(
                    1 for tx in transactions
                    if tx["amount_cents"] != 0 and tx["transaction_date"]
                )
                overall_confidence = 0.95 if parseable / len(transactions) >= 0.8 else 0.75
                # A well-formed row booked on the wrong side is still wrong: the
                # rows' own doubt holds those rows (`split_uncertain`), and a row
                # without a confidence is unknown, not 0.95.
                detail = (
                    f"[{detected_bank.bank_display_name}] Parsed {len(transactions)} transactions "
                    f"({parseable} fully parsed, confidence={overall_confidence:.2f})"
                )
                if statement.parse_warnings:
                    logger.warning(
                        "job=%s — parser warnings: %s",
                        state.get("job_id"), statement.parse_warnings,
                    )
                return SkillResult(
                    ok=True,
                    patch={"raw_text": raw_text, "transactions": transactions},
                    confidence=overall_confidence,
                    needs_review=overall_confidence < 0.80,
                    detail=detail,
                )
        # ── Strategy 1.5: Generic CSV parser (deterministic, fast, no LLM) ─
        if file_type in ("csv", "xlsx", "xls") or any(d in raw_text[:500] for d in (",", ";", "\t")):
            atlanan = []
            csv_txs = await asyncio.to_thread(_try_parse_csv, raw_text, atlanan, "", ledger)
            if csv_txs is not None:
                return _csv_sonucu(csv_txs, raw_text, state.get("job_id"), atlanan, ledger)
            ledger.reset()

        # ── Strategy 2: LLM fallback ───────────────────────────────────────
        logger.info("job=%s — no bank or CSV parser matched, using LLM extraction", state.get("job_id"))
        raw_transactions = await _extract_transactions_with_llm(raw_text, settings)

        if not raw_transactions:
            return SkillResult(
                ok=False,
                detail="LLM returned no transactions from the document.",
                needs_review=True,
                confidence=0.4,
            )

        # Detect currency once from the document header — avoids per-transaction guessing
        detected_currency = _detect_currency(raw_text)
        logger.info(
            "job=%s — detected currency: %s (LLM fallback path)",
            state.get("job_id"), detected_currency,
        )

        transactions = []

        for t in raw_transactions:
            amount_cents = _parse_amount(str(t.get("amount", "")))
            parsed_date = _parse_date(str(t.get("date", "")))
            # None = the model did not score this row (or gave a non-score).
            conf = parse_confidence(t.get("confidence"))
            if conf is not None and not (amount_cents and parsed_date):
                conf = min(conf, 0.55)  # an unreadable amount or date is a weak row

            # The row's own currency, else the document's; None when neither
            # says (the caller assumes the organisation's, marked, or holds it).
            tx_currency = t.get("currency") or detected_currency
            tx_type = t.get("type") if t.get("type") in ("income", "expense") else None

            transactions.append({
                "amount_cents": amount_cents,   # None = unreadable: held, never booked as 0
                "currency": tx_currency,
                # Direction is not defaulted: a row the model did not call income
                # or expense is held (app.services.ingest.hold), not booked as a cost.
                "type": tx_type,
                "category": _guess_category(t.get("description", ""), tx_type or "expense"),
                "description": t.get("description", ""),
                "vendor": t.get("vendor"),
                "transaction_date": parsed_date.isoformat() if parsed_date else None,
                "raw_text": str(t),
                "confidence": conf,
            })

        parseable = sum(
            1 for tx in transactions
            if (tx["amount_cents"] or 0) > 0 and tx["transaction_date"]
        )
        parse_ratio = parseable / len(transactions) if transactions else 0
        # The file's own quality. A weak row is held on its own; a file whose
        # rows are mostly unreadable is held as a whole.
        overall_confidence = 0.55 if parse_ratio < 0.5 else 0.95

        return SkillResult(
            ok=True,
            patch={"raw_text": raw_text, "transactions": transactions},
            confidence=overall_confidence,
            needs_review=overall_confidence < 0.80,
            detail=(
                f"[LLM] Extracted {len(transactions)} transactions "
                f"({parseable} fully parsed, confidence={overall_confidence:.2f})"
            ),
        )

    except Exception as exc:
        logger.exception("Data ingestion failed for job=%s", state.get("job_id"))
        return SkillResult(ok=False, detail=f"Ingestion error: {exc}", halt=True)
