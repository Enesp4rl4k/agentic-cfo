"""GİB e-Defter — XBRL GL yevmiye ve kebir üretimi.

`gib_edefter.py` düz bir yevmiye dökümü üretir; o döküm SMMM'ye ve arşive
gider, GİB'e gitmez. Beyan edilecek defter budur.

Biçim, GİB'in yayımladığı e-Defter paketindeki `edefter.xsd` ile doğrulanır.
Kök eleman `edefter:defter`, içeriği XBRL GL'dir (`gl-cor`/`gl-bus`), ve şema
en sonda ya bir XAdES imza ya da düz bir `HashValue` bekler:

    <xs:element name="defter">
      <xs:sequence>
        <xs:element ref="xbrli:xbrl"/>
        <xs:element name="extensions" minOccurs="0"/>
        <xs:choice>
          <xs:element name="HashValue"/>
          <xs:element ref="ds:Signature"/>
        </xs:choice>

Bu modül `HashValue` dalını üretir. Sonuç **şema olarak geçerli e-Defter**tir;
**beyan edilebilir değildir** — beyan için mali mühür ya da nitelikli e-imza
ile XAdES imzalanması, ardından beratının alınması gerekir. O ikisi donanım ve
GİB oturumu ister; yapı değişmeden eklenebilir. `EDefterXBRL.filable` bunu
tek bir alanda söyler ki hiçbir çağıran bu ayrımı kaçırmasın.

Dosya adlandırma GİB kuralıdır: VKN-YYYYMM-Y-000000.xml (yevmiye),
-K- (kebir). Numaralandırma aynı dönemde parça başına artar.
"""
from __future__ import annotations

import hashlib
import logging
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

NS = {
    "edefter": "http://www.edefter.gov.tr",
    "xbrli": "http://www.xbrl.org/2003/instance",
    "link": "http://www.xbrl.org/2003/linkbase",
    "xlink": "http://www.w3.org/1999/xlink",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "gl-cor": "http://www.xbrl.org/int/gl/cor/2006-10-25",
    "gl-bus": "http://www.xbrl.org/int/gl/bus/2006-10-25",
    "gl-plt": "http://www.xbrl.org/int/gl/plt/2006-10-25",
    "iso4217": "http://www.xbrl.org/2003/iso4217",
    "iso639": "http://www.xbrl.org/2005/iso639",
}

CONTEXT_ID = "journal_context"
UNIT_TRY = "try"
UNIT_COUNT = "countable"
SCHEMA_REF = "../xsd/2006-10-25/plt/case-c-b/gl-plt-2006-10-25.xsd"

# GİB identifies the ledger owner by VKN under its own scheme.
GIB_SCHEME = "http://www.gib.gov.tr"


class EDefterError(ValueError):
    """The journal cannot be expressed as an e-Defter."""


@dataclass
class EDefterXBRL:
    """One ledger file, plus everything a caller needs to judge it."""

    kind: str            # "Y" (yevmiye) | "K" (kebir)
    file_name: str       # GİB naming: VKN-YYYYMM-Y-000000.xml
    xml: str
    period: str          # YYYY-MM
    vkn: str
    entry_count: int
    line_count: int
    total_debit_kurus: int
    total_credit_kurus: int
    sha256_hash: str = ""
    # Signed with a mali mühür / nitelikli e-imza and berat obtained? Never
    # true from this module. The document is structurally complete and legally
    # incomplete, and those are different things that a single "valid" flag
    # would blur.
    filable: bool = False
    unfilable_reason: str = (
        "mali mühürle XAdES imzalanmadı ve beratı alınmadı — GİB'e yüklenemez"
    )
    warnings: list[str] = field(default_factory=list)

    @property
    def is_balanced(self) -> bool:
        return self.total_debit_kurus == self.total_credit_kurus


@dataclass
class LedgerOwner:
    """Who the ledger belongs to. Blank fields are omitted, never invented."""

    vkn: str
    title: str
    creator: str = ""            # defteri oluşturan kişi
    fiscal_year_start: str = ""  # YYYY-MM-DD
    fiscal_year_end: str = ""
    software_name: str = ""


def _kurus_to_lira(kurus: int) -> str:
    """Kuruş integer to the decimal string the ledger carries.

    Amounts are stored as integer kuruş precisely so this is the only place a
    division happens, and it happens exactly.
    """
    return f"{Decimal(kurus) / 100:.2f}"


def _q(prefix: str, tag: str) -> str:
    return f"{{{NS[prefix]}}}{tag}"


def _el(parent: ET.Element, prefix: str, tag: str, text: str = "", **attrs: str) -> ET.Element:
    node = ET.SubElement(parent, _q(prefix, tag), attrs)
    if text:
        node.text = text
    return node


def _fact(
    parent: ET.Element, prefix: str, tag: str, text: str, *, unit: str = ""
) -> ET.Element:
    """An XBRL fact: always bound to a context, numerics also to a unit."""
    attrs = {"contextRef": CONTEXT_ID}
    if unit:
        attrs["decimals"] = "INF"
        attrs["unitRef"] = unit
    return _el(parent, prefix, tag, text, **attrs)


def _split_account(code: str) -> tuple[str, str]:
    """`120.01` -> (`120`, `120.01`). A code with no sub-account has no sub."""
    code = (code or "").strip()
    main = code.split(".")[0] if code else ""
    return main, code


class EDefterXBRLGenerator:
    """Yevmiye ve kebir defterlerini XBRL GL olarak üretir."""

    @classmethod
    def generate_journal(
        cls,
        entries: Sequence[Mapping[str, Any]],
        *,
        period: str,
        owner: LedgerOwner,
        sequence: int = 0,
    ) -> EDefterXBRL:
        """Yevmiye defteri (Y).

        `entries` are `YevmiyeKaydi.to_dict()` rows as persisted in the
        `tr_muhasebe_journal` report — the same rows the defensibility packet
        seals, so the filing and the audited record cannot diverge.
        """
        cls._require_period(period)
        vkn = cls._require_vkn(owner.vkn)

        root, entries_node = cls._skeleton(
            period=period, owner=owner, entries_type="journal", sequence=sequence
        )

        warnings: list[str] = []
        total_debit = total_credit = 0
        line_count = 0

        for idx, entry in enumerate(entries, start=1):
            lines = list(entry.get("satirlar") or [])
            if not lines:
                warnings.append(f"{idx}. kayıtta satır yok, atlandı")
                continue

            posting_date = str(entry.get("tarih") or "")[:10] or f"{period}-01"
            comment = str(entry.get("aciklama") or "")
            doc_ref = str(
                entry.get("kaynak_islem_id") or entry.get("kayit_id") or f"{idx:06d}"
            )
            entry_debit = sum(int(line.get("borc") or 0) for line in lines)
            entry_credit = sum(int(line.get("alacak") or 0) for line in lines)

            header = _el(entries_node, "gl-cor", "entryHeader")
            if owner.creator:
                _fact(header, "gl-cor", "enteredBy", owner.creator)
            _fact(header, "gl-cor", "enteredDate", posting_date)
            _fact(header, "gl-cor", "entryNumber", f"{idx:06d}")
            if comment:
                _fact(header, "gl-cor", "entryComment", comment)
            _fact(header, "gl-bus", "totalDebit", _kurus_to_lira(entry_debit), unit=UNIT_TRY)
            _fact(header, "gl-bus", "totalCredit", _kurus_to_lira(entry_credit), unit=UNIT_TRY)
            _fact(header, "gl-cor", "entryNumberCounter", str(idx), unit=UNIT_COUNT)

            for line_no, line in enumerate(lines, start=1):
                debit = int(line.get("borc") or 0)
                credit = int(line.get("alacak") or 0)
                if debit and credit:
                    # One detail is one side. A row carrying both is two rows
                    # that were merged somewhere upstream, and splitting it here
                    # would invent a structure the audited record does not have.
                    raise EDefterError(
                        f"{idx}. kaydın {line_no}. satırı hem borç hem alacak "
                        "taşıyor — tek satır tek tarafa yazılır"
                    )
                if not debit and not credit:
                    warnings.append(
                        f"{idx}. kaydın {line_no}. satırı sıfır tutarlı, atlandı"
                    )
                    continue

                cls._append_detail(
                    header,
                    line_no=line_no,
                    account_code=str(line.get("hesap_kodu") or ""),
                    account_name=str(line.get("hesap_adi") or ""),
                    amount_kurus=debit or credit,
                    debit_credit="D" if debit else "C",
                    posting_date=posting_date,
                    document_reference=doc_ref,
                    comment=str(line.get("aciklama") or comment),
                )
                line_count += 1

            total_debit += entry_debit
            total_credit += entry_credit

        return cls._finish(
            root,
            kind="Y",
            period=period,
            vkn=vkn,
            sequence=sequence,
            entry_count=len(entries),
            line_count=line_count,
            total_debit=total_debit,
            total_credit=total_credit,
            warnings=warnings,
        )

    @classmethod
    def generate_ledger(
        cls,
        entries: Sequence[Mapping[str, Any]],
        *,
        period: str,
        owner: LedgerOwner,
        sequence: int = 0,
    ) -> EDefterXBRL:
        """Defter-i kebir (K) — same movements, grouped by account.

        Kebir is not a second source of truth: it is the journal read down the
        account column. Deriving it from the same rows is the only way the two
        ledgers can agree, and GİB checks that they do.
        """
        cls._require_period(period)
        vkn = cls._require_vkn(owner.vkn)

        root, entries_node = cls._skeleton(
            period=period, owner=owner, entries_type="ledger", sequence=sequence
        )

        # account code -> the movements booked to it, in journal order
        by_account: dict[str, list[dict[str, Any]]] = {}
        for idx, entry in enumerate(entries, start=1):
            posting_date = str(entry.get("tarih") or "")[:10] or f"{period}-01"
            comment = str(entry.get("aciklama") or "")
            doc_ref = str(
                entry.get("kaynak_islem_id") or entry.get("kayit_id") or f"{idx:06d}"
            )
            for line in entry.get("satirlar") or []:
                debit = int(line.get("borc") or 0)
                credit = int(line.get("alacak") or 0)
                if not debit and not credit:
                    continue
                code = str(line.get("hesap_kodu") or "")
                by_account.setdefault(code, []).append({
                    "entry_no": idx,
                    "account_name": str(line.get("hesap_adi") or ""),
                    "amount_kurus": debit or credit,
                    "debit_credit": "D" if debit else "C",
                    "posting_date": posting_date,
                    "document_reference": doc_ref,
                    "comment": str(line.get("aciklama") or comment),
                })

        total_debit = total_credit = 0
        line_count = 0
        for header_no, code in enumerate(sorted(by_account), start=1):
            movements = by_account[code]
            debit = sum(m["amount_kurus"] for m in movements if m["debit_credit"] == "D")
            credit = sum(m["amount_kurus"] for m in movements if m["debit_credit"] == "C")

            header = _el(entries_node, "gl-cor", "entryHeader")
            if owner.creator:
                _fact(header, "gl-cor", "enteredBy", owner.creator)
            _fact(header, "gl-cor", "enteredDate", movements[0]["posting_date"])
            _fact(header, "gl-cor", "entryNumber", f"{header_no:06d}")
            _fact(header, "gl-bus", "totalDebit", _kurus_to_lira(debit), unit=UNIT_TRY)
            _fact(header, "gl-bus", "totalCredit", _kurus_to_lira(credit), unit=UNIT_TRY)
            _fact(header, "gl-cor", "entryNumberCounter", str(header_no), unit=UNIT_COUNT)

            for line_no, m in enumerate(movements, start=1):
                cls._append_detail(
                    header,
                    line_no=line_no,
                    account_code=code,
                    account_name=m["account_name"],
                    amount_kurus=m["amount_kurus"],
                    debit_credit=m["debit_credit"],
                    posting_date=m["posting_date"],
                    document_reference=m["document_reference"],
                    comment=m["comment"],
                )
                line_count += 1

            total_debit += debit
            total_credit += credit

        return cls._finish(
            root,
            kind="K",
            period=period,
            vkn=vkn,
            sequence=sequence,
            entry_count=len(by_account),
            line_count=line_count,
            total_debit=total_debit,
            total_credit=total_credit,
            warnings=[],
        )

    # ── building blocks ──────────────────────────────────────────────────────

    @staticmethod
    def _require_period(period: str) -> None:
        try:
            datetime.strptime(period, "%Y-%m")
        except ValueError as exc:
            raise EDefterError(f"dönem YYYY-MM olmalı: {period!r}") from exc

    @staticmethod
    def _require_vkn(vkn: str) -> str:
        digits = "".join(c for c in (vkn or "") if c.isdigit())
        if len(digits) not in (10, 11):
            raise EDefterError(
                f"VKN 10 (kurum) veya TCKN 11 hane olmalı: {vkn!r}"
            )
        return digits

    @classmethod
    def _skeleton(
        cls, *, period: str, owner: LedgerOwner, entries_type: str, sequence: int
    ) -> tuple[ET.Element, ET.Element]:
        for prefix, uri in NS.items():
            ET.register_namespace(prefix, uri)

        root = ET.Element(_q("edefter", "defter"), {
            _q("xsi", "schemaLocation"): "http://www.edefter.gov.tr ../xsd/edefter.xsd",
            # `iso4217:TRY` and `iso639:tr` are QNames carried in element *text*,
            # and a QName is only valid where its prefix is declared. ElementTree
            # emits xmlns declarations for namespaces used in tags and attribute
            # names, never for ones that appear only in content — so without
            # these two literal declarations the schema rejects the currency unit
            # and the language, which is exactly what it should do.
            "xmlns:iso4217": NS["iso4217"],
            "xmlns:iso639": NS["iso639"],
        })
        xbrl = _el(root, "xbrli", "xbrl", **{
            _q("xsi", "schemaLocation"): (
                "http://www.xbrl.org/int/gl/plt/2006-10-25 " + SCHEMA_REF
            ),
        })
        _el(xbrl, "link", "schemaRef", **{
            _q("xlink", "href"): SCHEMA_REF,
            _q("xlink", "type"): "simple",
        })

        context = _el(xbrl, "xbrli", "context", id=CONTEXT_ID)
        entity = _el(context, "xbrli", "entity")
        _el(entity, "xbrli", "identifier", cls._require_vkn(owner.vkn), scheme=GIB_SCHEME)
        period_node = _el(context, "xbrli", "period")
        _el(period_node, "xbrli", "instant", cls._period_end(period))

        unit_try = _el(xbrl, "xbrli", "unit", id=UNIT_TRY)
        _el(unit_try, "xbrli", "measure", "iso4217:TRY")
        unit_count = _el(xbrl, "xbrli", "unit", id=UNIT_COUNT)
        _el(unit_count, "xbrli", "measure", "xbrli:pure")

        entries_node = _el(xbrl, "gl-cor", "accountingEntries")
        doc_info = _el(entries_node, "gl-cor", "documentInfo")
        _fact(doc_info, "gl-cor", "entriesType", entries_type)
        _fact(
            doc_info, "gl-cor", "uniqueID",
            f"{'YEV' if entries_type == 'journal' else 'KEB'}"
            f"{period.replace('-', '')}{sequence:06d}",
        )
        _fact(doc_info, "gl-cor", "language", "iso639:tr")
        _fact(doc_info, "gl-cor", "creationDate", datetime.now(UTC).date().isoformat())
        if owner.creator:
            _fact(doc_info, "gl-bus", "creator", owner.creator)
        _fact(doc_info, "gl-cor", "periodCoveredStart", f"{period}-01")
        _fact(doc_info, "gl-cor", "periodCoveredEnd", cls._period_end(period))
        if owner.software_name:
            # GİB's format: VKN##üretici##yazılım##sürüm
            _fact(doc_info, "gl-bus", "sourceApplication", owner.software_name)

        entity_info = _el(entries_node, "gl-cor", "entityInformation")
        identifiers = _el(entity_info, "gl-bus", "organizationIdentifiers")
        _fact(identifiers, "gl-bus", "organizationIdentifier", owner.title)
        _fact(identifiers, "gl-bus", "organizationDescription", "Kurum Unvanı")
        # Address, phone and e-mail are omitted rather than invented. A ledger
        # carrying a plausible-looking address nobody entered is worse than one
        # that carries none.
        if owner.fiscal_year_start:
            _fact(entity_info, "gl-bus", "fiscalYearStart", owner.fiscal_year_start)
        if owner.fiscal_year_end:
            _fact(entity_info, "gl-bus", "fiscalYearEnd", owner.fiscal_year_end)

        return root, entries_node

    @staticmethod
    def _period_end(period: str) -> str:
        year, month = (int(p) for p in period.split("-"))
        if month == 12:
            return date(year, 12, 31).isoformat()
        return (date(year, month + 1, 1) - (date(1, 1, 2) - date(1, 1, 1))).isoformat()

    @classmethod
    def _append_detail(
        cls,
        header: ET.Element,
        *,
        line_no: int,
        account_code: str,
        account_name: str,
        amount_kurus: int,
        debit_credit: str,
        posting_date: str,
        document_reference: str,
        comment: str,
    ) -> None:
        detail = _el(header, "gl-cor", "entryDetail")
        _fact(detail, "gl-cor", "lineNumber", str(line_no))
        _fact(detail, "gl-cor", "lineNumberCounter", str(line_no), unit=UNIT_COUNT)

        main, sub = _split_account(account_code)
        account = _el(detail, "gl-cor", "account")
        _fact(account, "gl-cor", "accountMainID", main)
        _fact(account, "gl-cor", "accountMainDescription", account_name or main)
        if sub and sub != main:
            sub_node = _el(account, "gl-cor", "accountSub")
            _fact(sub_node, "gl-cor", "accountSubDescription", account_name or sub)
            _fact(sub_node, "gl-cor", "accountSubID", sub)

        _fact(detail, "gl-cor", "amount", _kurus_to_lira(amount_kurus), unit=UNIT_TRY)
        _fact(detail, "gl-cor", "debitCreditCode", debit_credit)
        _fact(detail, "gl-cor", "postingDate", posting_date)
        _fact(detail, "gl-cor", "documentReference", document_reference)
        if comment:
            _fact(detail, "gl-cor", "detailComment", comment)

    @classmethod
    def _finish(
        cls,
        root: ET.Element,
        *,
        kind: str,
        period: str,
        vkn: str,
        sequence: int,
        entry_count: int,
        line_count: int,
        total_debit: int,
        total_credit: int,
        warnings: list[str],
    ) -> EDefterXBRL:
        # The schema wants either a XAdES signature or a HashValue here. We can
        # produce the second honestly; the first needs a mali mühür.
        body = ET.tostring(root, encoding="utf-8")
        digest = hashlib.sha256(body).hexdigest()
        # edefter.xsd declares HashValue locally and sets no
        # elementFormDefault, so it is unqualified — in no namespace at all.
        hash_node = ET.SubElement(root, "HashValue")
        hash_node.text = digest

        xml = ET.tostring(root, encoding="unicode", xml_declaration=False)
        xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml

        return EDefterXBRL(
            kind=kind,
            file_name=f"{vkn}-{period.replace('-', '')}-{kind}-{sequence:06d}.xml",
            xml=xml,
            period=period,
            vkn=vkn,
            entry_count=entry_count,
            line_count=line_count,
            total_debit_kurus=total_debit,
            total_credit_kurus=total_credit,
            sha256_hash=digest,
            warnings=warnings,
        )
