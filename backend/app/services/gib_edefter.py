"""
GİB e-Defter XML & Beyanname Hazırlık Motoru (Phase 3).

Gelir İdaresi Başkanlığı (GİB) e-Defter standartlarına uygun:
- Aylık Yevmiye Defteri (Journal) XML
- Defter-i Kebir (General Ledger) XML
- KDV-1 ve Muhtasar Beyanname Özetleri

Girdi, `tr_muhasebe_journal` Report'unda saklanan yevmiye kayıtlarıdır —
SMMM'nin onayladığı, savunulabilirlik paketinin mühürlediği satırların ta
kendisi. Ajanın bellek içi dataclass'ı yerine kalıcı kaydı tüketmesi hem katman
kuralına uyar (services, agents'ı import edemez) hem de tek gerçeği kalıcı
artefakt üzerinden zorunlu kılar: paket neyi mühürlediyse defter onu beyan eder.

Daha önce `app/services/thp_classifier.py` içindeki ikinci bir sınıflandırıcının
`SuggestedJournalEntry`'sini tüketiyordu. O motoru üretimde hiçbir şey
çalıştırmıyordu, yani GİB'e gidecek yasal defter, denetlenen yevmiyeden *farklı*
bir mantıkla üretilecekti. Bir savunulabilirlik paketinin bütün anlamı, mühürlü
kaydın beyan edilenle aynı olmasıdır; o sapma paketin kendisini çürütüyordu.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.financial import cents_to_amount

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
        entries: Sequence[Mapping[str, Any]],
        period: str,
        vkn: str,
        company_title: str,
    ) -> EDefterPackage:
        """Build an e-Defter compliant Journal XML tree and package.

        `entries` are `YevmiyeKaydi.to_dict()` rows exactly as persisted in the
        `tr_muhasebe_journal` report — the same list the defensibility packet
        itemises.
        """
        import hashlib

        total_debit = sum(int(e.get("toplam_borc") or 0) for e in entries)
        total_credit = sum(int(e.get("toplam_alacak") or 0) for e in entries)

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
                # `tarih` is stored as an ISO timestamp; the defter wants a date.
                "date": str(entry.get("tarih") or "")[:10],
                # The source transaction is the belge referansı; falling back to
                # the entry id keeps the attribute present for manual entries.
                "document_number": str(
                    entry.get("kaynak_islem_id") or entry.get("kayit_id") or ""
                ),
                "description": str(entry.get("aciklama") or ""),
            })
            for line_idx, line in enumerate(entry.get("satirlar") or [], start=1):
                ET.SubElement(entry_el, "edefter:line", {
                    "line_number": str(line_idx),
                    "account_code": str(line.get("hesap_kodu") or ""),
                    "account_name": str(line.get("hesap_adi") or ""),
                    "debit": f"{cents_to_amount(int(line.get('borc') or 0)):.2f}",
                    "credit": f"{cents_to_amount(int(line.get('alacak') or 0)):.2f}",
                    "description": str(line.get("aciklama") or ""),
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
