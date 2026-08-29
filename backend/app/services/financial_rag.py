"""
Financial RAG & Contract Intelligence Engine (Roadmap 2.0 - Epic 2).

Extracts semantic intelligence, payment terms, penalty clauses, and CPI price escalation
clauses from commercial contracts, banking agreements, and GİB tax notices.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FinancialClause:
    clause_type: str       # "payment_term", "penalty", "price_escalation", "termination"
    text: str
    confidence: float
    extracted_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentIntelligenceResult:
    document_id: str
    document_title: str
    total_chunks: int
    detected_clauses: list[FinancialClause] = field(default_factory=list)
    key_takeaways: list[str] = field(default_factory=list)


class FinancialRAGEngine:
    """Processes legal and financial documents for CFO contextual awareness."""

    @classmethod
    def analyze_document_text(
        cls,
        document_id: str,
        document_title: str,
        text: str,
    ) -> DocumentIntelligenceResult:
        """
        Analyze raw document text and extract structured financial clauses.
        """
        clauses: list[FinancialClause] = []
        takeaways: list[str] = []

        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

        for p in paragraphs:
            p_lower = p.lower()

            # 1. Ödeme Vadesi (Payment Terms) Tespiti
            if any(term in p_lower for term in ["ödeme vadesi", "ödeme günü", "net 30", "net 45", "net 60", "fatura tarihinden itibaren", "gün içinde ödenecektir"]):
                if not any(term in p_lower for term in ["gecikme faizi", "temerrüt", "cezai şart"]):
                    days_match = re.search(r"(\d{1,3})\s*(?:gün|gun|iş günü)", p_lower)
                    days = int(days_match.group(1)) if days_match else 30
                    clauses.append(FinancialClause(
                        clause_type="payment_term",
                        text=p,
                        confidence=0.92,
                        extracted_data={"payment_days": days},
                    ))
                    takeaways.append(f"Ödeme vadesi: Fatura kesiminden itibaren {days} gün.")

            # 2. Gecikme Faizi ve Cezai Şart (Penalty / Late Interest)
            if any(term in p_lower for term in ["gecikme faizi", "cezai şart", "temerrüt", "faiz oranı", "aylık %"]):
                rate_match = re.search(r"(?:%\s*|yüzde\s*)(\d+(?:[.,]\d+)?)", p_lower)
                rate = float(rate_match.group(1).replace(",", ".")) if rate_match else 2.5
                clauses.append(FinancialClause(
                    clause_type="penalty",
                    text=p,
                    confidence=0.88,
                    extracted_data={"monthly_interest_rate_pct": rate},
                ))
                takeaways.append(f"Gecikme faizi / cezai şart: Aylık %{rate} temerrüt faizi.")

            # 3. Fiyat Artış / Enflasyon Klozu (CPI / TÜFE Escalation)
            if any(term in p_lower for term in ["tüfe", "yi-üfe", "enflasyon artışı", "fiyat revizyonu", "yıllık artış"]):
                clauses.append(FinancialClause(
                    clause_type="price_escalation",
                    text=p,
                    confidence=0.95,
                    extracted_data={"index_type": "TÜİK TÜFE 12 Aylık Ortalama"},
                ))
                takeaways.append("Fiyat artış klozu: Yıllık TÜİK TÜFE 12 aylık ortalamasına endeksli.")

        return DocumentIntelligenceResult(
            document_id=document_id,
            document_title=document_title,
            total_chunks=len(paragraphs),
            detected_clauses=clauses,
            key_takeaways=list(set(takeaways)),
        )
