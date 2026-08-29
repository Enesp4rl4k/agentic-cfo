"""
GİB e-Defter XML & Beyanname Hazırlık Motoru (Phase 3).

Gelir İdaresi Başkanlığı (GİB) e-Defter standartlarına uygun:
- Aylık Yevmiye Defteri (Journal) XML
- Defter-i Kebir (General Ledger) XML
- KDV-1 ve Muhtasar Beyanname Özetleri
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime

from app.core.financial import cents_to_amount
from app.services.thp_classifier import SuggestedJournalEntry

logger = logging.getLogger(__name__)


@dataclass
class EDefterPackage:
    period: str  # YYYY-MM
    vkn: str
    company_title: str
    entry_count: int
    total_debit_cents: int
    total_credit_cents: int
    journal_xml: str
    is_valid: bool = True
    sha256_hash: str = ""


class EDefterGenerator:
    """GİB e-Defter ve beyanname XML paketi oluşturucu."""

    @staticmethod
    def generate_journal_xml(
        entries: list[SuggestedJournalEntry],
        period: str,
        vkn: str,
        company_title: str,
    ) -> EDefterPackage:
        """
        Build an e-Defter compliant Journal XML tree and package.
        """
        import hashlib

        total_debit = sum(e.total_debit_cents for e in entries)
        total_credit = sum(e.total_credit_cents for e in entries)

        root = ET.Element("edefter:journal", {
            "xmlns:edefter": "http://www.edefter.gov.tr",
            "period": period,
            "vkn": vkn,
            "company": company_title,
            "generated_at": datetime.now().isoformat(),
        })

        for idx, entry in enumerate(entries, start=1):
            entry_el = ET.SubElement(root, "edefter:entry", {
                "journal_number": str(idx),
                "date": entry.entry_date,
                "document_number": entry.document_number,
                "description": entry.description,
            })
            for line_idx, line in enumerate(entry.lines, start=1):
                ET.SubElement(entry_el, "edefter:line", {
                    "line_number": str(line_idx),
                    "account_code": line.account_code,
                    "account_name": line.account_name,
                    "debit": f"{cents_to_amount(line.debit_cents):.2f}",
                    "credit": f"{cents_to_amount(line.credit_cents):.2f}",
                    "description": line.description,
                })

        xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        xml_str = xml_bytes.decode("utf-8")
        sha256_hash = hashlib.sha256(xml_bytes).hexdigest()

        return EDefterPackage(
            period=period,
            vkn=vkn,
            company_title=company_title,
            entry_count=len(entries),
            total_debit_cents=total_debit,
            total_credit_cents=total_credit,
            journal_xml=xml_str,
            is_valid=(total_debit == total_credit),
            sha256_hash=sha256_hash,
        )
