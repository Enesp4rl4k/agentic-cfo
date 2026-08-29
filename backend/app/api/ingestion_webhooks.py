"""
Ingestion Webhooks API

Dış entegratörlerden (e-Fatura portalları, banka web servisleri, muhasebe yazılımları)
gelen canlı veri akışlarını yakalayan ve ilgili parser/hesaplama motorlarını
otomatik olarak tetikleyen webhook katmanı.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from app.parsers.invoice.ubl_tr import UBLTRInvoiceParser
from app.parsers.registry import get_parser_registry

router = APIRouter(prefix="/webhooks", tags=["ingestion-webhooks"])
logger = logging.getLogger(__name__)


class WebhookBankPayload(BaseModel):
    bank_name: str
    raw_statement_text: str
    account_iban: str | None = None


@router.post("/efatura")
async def receive_efatura_webhook(
    request: Request,
    x_integrator_token: str | None = Header(None),
) -> dict[str, Any]:
    """
    GİB e-Fatura entegratöründen (Uyumsoft, Paraşüt, EDM vb.) gelen UBL-TR XML'i yakalar.
    Otomatik olarak TDHP muhasebe kaydı önerisini ve vergi etkisini hesaplar.
    """
    try:
        body_bytes = await request.body()
        xml_content = body_bytes.decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to read e-fatura webhook body: {e}")
        raise HTTPException(status_code=400, detail="Geçersiz XML içeriği.")

    if not xml_content.strip():
        raise HTTPException(status_code=400, detail="Boş içerik.")

    # 1. UBL-TR Parser'ı çalıştır
    try:
        invoice = UBLTRInvoiceParser.parse_xml(xml_content)
    except Exception as e:
        logger.error(f"UBL parse error: {e}")
        raise HTTPException(status_code=422, detail=f"UBL-TR XML formatı ayrıştırılamadı: {e}")

    logger.info(
        f"Webhook: Yeni e-Fatura yakalandı! No: {invoice.invoice_number}, Tutar: {invoice.payable_amount} {invoice.currency_code}"
    )

    # 2. Vergi ve Muhasebe Kaydı Özeti
    return {
        "status": "ingested",
        "invoice_number": invoice.invoice_number,
        "issue_date": str(invoice.issue_date),
        "supplier": invoice.supplier.title or invoice.supplier.vkn_tckn,
        "customer": invoice.customer.title or invoice.customer.vkn_tckn,
        "payable_amount": float(invoice.payable_amount),
        "tax_inclusive_total": float(invoice.tax_inclusive_total),
        "accounting_recommendation": [
            {
                "code": entry.account_code,
                "name": entry.account_name,
                "debit": float(entry.debit_amount),
                "credit": float(entry.credit_amount),
                "description": entry.description,
            }
            for entry in invoice.suggested_tdhp_entries
        ],
    }


@router.post("/bank-statement")
async def receive_bank_webhook(
    payload: WebhookBankPayload,
    x_bank_signature: str | None = Header(None),
) -> dict[str, Any]:
    """
    Açık Bankacılık veya banka webhook servisinden gelen ekstre metnini anında ayrıştırır.
    """
    registry = get_parser_registry()
    parser = registry.find_parser_by_name(payload.bank_name)

    if not parser:
        # Uygun banka parser'ını otomatik bul
        candidates = registry.get_all_parsers()
        for p in candidates:
            if p.can_parse(payload.raw_statement_text):
                parser = p
                break

    if not parser:
        raise HTTPException(
            status_code=422,
            detail=f"Metin için uygun bir banka ayrıştırıcısı bulunamadı (Banka: {payload.bank_name}).",
        )

    statement = parser.parse(payload.raw_statement_text)
    logger.info(
        f"Webhook: Banka ekstresi ayrıştırıldı! Banka: {statement.bank_name}, İşlem Sayısı: {len(statement.transactions)}"
    )

    return {
        "status": "ingested",
        "bank_name": statement.bank_name,
        "account_number": statement.account_number,
        "period": statement.period,
        "total_transactions": len(statement.transactions),
        "transactions": [
            {
                "date": tx.date,
                "description": tx.description,
                "amount_cents": tx.amount_cents,
                "tx_type": tx.tx_type,
            }
            for tx in statement.transactions
        ],
    }
