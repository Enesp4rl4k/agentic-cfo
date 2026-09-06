"""
Aylık yevmiye dökümü — SMMM'ye giden, GİB'e gitmeyen.

Bu modül **e-Defter üretmez.** GİB'in e-Defteri XBRL GL'dir: kök elemanı
`defter`, gl-cor/gl-bus altında 78 ayrı eleman kullanır ve `edefter.xsd`
tarafından doğrulanır. Burada üretilen düz bir yevmiye dökümüdür ve o şemadan
kök elemanda, içeriğe hiç bakılmadan reddedilir. Bir süre GİB'in namespace'ini
taşıdı; taşımaması gerekiyordu.

Ne için var: mühürlü savunulabilirlik paketindeki yevmiye satırlarının makine
okunur dökümü. Mali müşavire, denetime ve arşive gider.

Beyan için gereken (`app/services/edefter_xbrl.py` bunu üretir): XBRL GL
yevmiye + kebir, GİB dosya adlandırması, berat ve mali mühürle XAdES imza.

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
    # Debit equals credit. This used to be called `is_valid`, which reads as a
    # statement about the document and is not one: it says nothing about whether
    # GİB would accept the file.
    is_balanced: bool = True
    # Whether the XML validates against GİB's published edefter.xsd. None until
    # something actually checks.
    schema_valid: bool | None = None
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
        """Build the monthly journal listing.

        Not an e-Defter: see the module docstring. `EDefterXBRLGenerator`
        produces the XBRL GL document GİB's schema accepts.

        `entries` are `YevmiyeKaydi.to_dict()` rows exactly as persisted in the
        `tr_muhasebe_journal` report — the same list the defensibility packet
        itemises.
        """
        import hashlib

        total_debit = sum(int(e.get("toplam_borc") or 0) for e in entries)
        total_credit = sum(int(e.get("toplam_alacak") or 0) for e in entries)

        # NOT the GİB namespace. This document is a flat journal listing of
        # our own design; GİB's e-Defter is XBRL GL, whose root element is
        # `defter` and which uses 78 distinct gl-cor/gl-bus elements. Putting
        # http://www.edefter.gov.tr on this made a claim the file cannot meet —
        # it is rejected by edefter.xsd at the root element, before any content
        # is examined.
        root = ET.Element("yevmiye:dokum", {
            "xmlns:yevmiye": "urn:c-suite:yevmiye-dokum:1",
            "period": period,
            "vkn": vkn,
            "company": company_title,
            "generated_at": datetime.now().isoformat(),
        })

        for idx, entry in enumerate(entries, start=1):
            entry_el = ET.SubElement(root, "yevmiye:kayit", {
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
                ET.SubElement(entry_el, "yevmiye:satir", {
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
            is_balanced=(total_debit == total_credit),
            sha256_hash=sha256_hash,
        )
