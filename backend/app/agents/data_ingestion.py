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
from app.parsers.base import ParsedStatement
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
from app.services.ingest.ebelge import (
    _try_parse_ubl_xml,
)
from app.services.ingest.readers import (
    _pdf_embedded_xml,
    _read_csv,
    _read_excel,
    _read_pdf,
    _read_xml,
)
from app.services.ingest.rows import (
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
        "- confidence: confidence score 0-1 for this extraction\n\n"
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
) -> SkillResult:
    # Confidence must reflect data quality: rows with an unparseable
    # date or a zero amount are only partially usable. A file where
    # most dates failed to parse should NOT sail through the gate.
    # (A correction posted to an account carries a negative amount.)
    well_formed = sum(
        1 for tx in csv_txs
        if tx.get("transaction_date") and tx.get("amount_cents", 0) != 0
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

    sonuc = await _belgeyi_al(
        state.get("file_path", ""), state.get("file_type", ""), state, config,
    )
    ekler = list(state.get("ek_belgeler") or [])
    if not ekler:
        return sonuc

    islemler: list[dict[str, Any]] = list((sonuc.patch or {}).get("transactions") or [])
    metinler: list[str] = [str((sonuc.patch or {}).get("raw_text") or "")]
    detaylar: list[str] = [f"1) {sonuc.detail}"]
    guven = sonuc.confidence if sonuc.ok else 1.0
    inceleme = bool(sonuc.needs_review)

    for i, ek in enumerate(ekler, start=2):
        alt = await _belgeyi_al(ek.get("path", ""), ek.get("type", ""), state, config)
        ad = ek.get("ad") or ek.get("path", "")
        detaylar.append(f"{i}) {ad}: {alt.detail}")
        if alt.ok:
            islemler.extend((alt.patch or {}).get("transactions") or [])
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
               "transactions": islemler},
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
    """One document: read it, then parse by the strategies below.

    Strategy:
      1. Read raw text from file (PDF / Excel / CSV / XML)
      2. Try ParserRegistry (bank-specific rule-based parsers) — fast, free
      3. If no bank match → fall back to LLM extraction
    """
    settings = get_settings()

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
                ubl_confidence = min(float(t.get("confidence", 0.8)) for t in ubl_txs)
                logger.info(
                    "job=%s — UBL-TR XML parser parsed %d invoice transactions (conf=%.2f)",
                    state.get("job_id"), len(ubl_txs), ubl_confidence,
                )
                return SkillResult(
                    ok=True,
                    patch={"raw_text": raw_text, "transactions": ubl_txs},
                    confidence=ubl_confidence,
                    needs_review=ubl_confidence < 0.80,
                    detail=(
                        f"Parsed {len(ubl_txs)} transactions via GİB UBL-TR XML "
                        f"parser (confidence={ubl_confidence:.2f})"
                    ),
                )

        # ── Strategy 1.1: a spreadsheet read by its columns ──────────────────
        # Before the bank parsers: they are patterns over PDF text, and matched
        # a bank's name anywhere in the file. A statement exported as a table
        # loses its empty cells when flattened to text, so "Borç" and "Alacak"
        # traded places — and one "AKBANK EFT" line in another bank's CSV sent
        # the whole file through Akbank's pattern. A table is read as a table.
        if file_type in ("csv", "xlsx"):
            atlanan: list[str] = []
            table_txs = await asyncio.to_thread(_tablo_ekstresi, file_path, atlanan)
            if table_txs:
                return _csv_sonucu(table_txs, raw_text, state.get("job_id"), atlanan)

        # ── Strategy 1: Bank-specific rule-based parser ────────────────────
        detected_bank = await asyncio.to_thread(ParserRegistry.detect, raw_text)
        if detected_bank is not None:
            logger.info(
                "job=%s — using bank parser: %s",
                state.get("job_id"), detected_bank.bank_display_name,
            )
            statement: ParsedStatement = await asyncio.to_thread(detected_bank().parse, raw_text, file_path)
            transactions = _statement_to_transactions(statement)

            if transactions:
                parseable = sum(
                    1 for tx in transactions
                    if tx["amount_cents"] != 0 and tx["transaction_date"]
                )
                overall_confidence = 0.95 if parseable / len(transactions) >= 0.8 else 0.75
                # A well-formed row booked on the wrong side is still wrong, so
                # the rows' own doubt caps the file's confidence.
                overall_confidence = min(
                    overall_confidence,
                    min(float(tx.get("confidence", 0.95)) for tx in transactions),
                )
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
            csv_txs = await asyncio.to_thread(_try_parse_csv, raw_text, atlanan)
            if csv_txs:
                return _csv_sonucu(csv_txs, raw_text, state.get("job_id"), atlanan)

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
        confidences: list[float] = []

        for t in raw_transactions:
            amount_cents = _parse_amount(str(t.get("amount", "")))
            parsed_date = _parse_date(str(t.get("date", "")))
            conf = float(t.get("confidence", 0.8))
            confidences.append(conf)

            # Use per-transaction currency if LLM provided one, else fall back to detected
            tx_currency = t.get("currency") or detected_currency

            transactions.append({
                "amount_cents": amount_cents or 0,
                "currency": tx_currency,
                "type": t.get("type", "expense"),
                "category": _guess_category(t.get("description", ""), t.get("type", "expense")),
                "description": t.get("description", ""),
                "vendor": t.get("vendor"),
                "transaction_date": parsed_date.isoformat() if parsed_date else None,
                "raw_text": str(t),
                "confidence": conf,
            })

        overall_confidence = min(confidences) if confidences else 0.5
        parseable = sum(
            1 for tx in transactions
            if tx["amount_cents"] > 0 and tx["transaction_date"]
        )
        parse_ratio = parseable / len(transactions) if transactions else 0

        if parse_ratio < 0.5:
            overall_confidence = min(overall_confidence, 0.55)
        elif parse_ratio < 0.8:
            overall_confidence = min(overall_confidence, 0.75)

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
