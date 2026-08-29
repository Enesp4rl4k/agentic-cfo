"""
Compliance Kernel -- Turkiye Mevzuati Uyum Degerlendirmesi

Sirket profili ve mevcut C-Suite verilerinden Turkiye'ye ozgu
yasal uyum risklerini otomatik degerlendirir.

Kapsanan mevzuat:
  - KVK (Kisisel Verilerin Korunmasi Kanunu)
  - e-Fatura / e-Arsiv (GIB)
  - SGK yukumlulukler (personel)
  - KVKK Aydinlatma / Veri Isleme Sozlesmesi
  - Ticaret Kanunu (TTK) -- yillik rapor, denetim
  - Vergi Usul Kanunu (VUK) -- muhasebe standartlari
  - BDDK / SPK (fintech sirketler icin)
  - GDPR uyumu (AB musteri varsa)
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ComplianceItem:
    regulation:   str   # "KVK" | "e-Fatura" | "SGK" | ...
    requirement:  str
    status:       str   # "compliant" | "partial" | "non_compliant" | "unknown"
    risk_level:   str   # "critical" | "high" | "medium" | "low"
    risk_score:   float
    description:  str
    evidence:     str
    action:       str
    deadline:     str   # "Acil (7 gun)" | "30 gun" | "90 gun" | "Surekli"


@dataclass
class ComplianceKernelOutput:
    overall_compliance_score: float   # 0-100 (yuksek = iyi)
    compliance_posture:       str     # compliant | partial | at_risk | non_compliant
    total_requirements:       int
    compliant_count:          int
    partial_count:            int
    non_compliant_count:      int
    unknown_count:            int
    critical_violations:      int
    items:                    list[ComplianceItem]
    priority_actions:         list[str]
    regulatory_exposure_try:  float   # tahmini ceza riski (TRY)
    data_source:              str
    confidence:               float
    narrative:                str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ComplianceKernel:
    """
    Compliance Kernel -- Turkiye mevzuatina gore uyum degerlendirmesi.
    Sirket profili ve mevcut verilere gore otomatik degerlendirir.
    """

    def __init__(
        self,
        pnl:           dict[str, Any] | None = None,
        chro_data:     dict[str, Any] | None = None,
        cto_data:      dict[str, Any] | None = None,
        company_size:  str = "smb",   # startup | smb | enterprise
        sector:        str = "saas",  # saas | ecommerce | fintech | services | retail
        has_eu_customers: bool = False,
        is_fintech:    bool = False,
        monthly_invoice_count: int = 0,
    ) -> None:
        self.pnl           = pnl or {}
        self.chro_data     = chro_data or {}
        self.cto_data      = cto_data or {}
        self.size          = company_size
        self.sector        = sector
        self.eu_customers  = has_eu_customers
        self.is_fintech    = is_fintech
        self.invoice_count = monthly_invoice_count

        self.headcount     = self.chro_data.get("total_headcount", 0) or 0
        self.monthly_rev   = (self.pnl.get("revenue", 0) or 0) / 100 / 12
        self.net_margin    = self.pnl.get("net_margin", 0) or 0
        self.tech_security = self.cto_data.get("security_score", 7.0) or 7.0

    def _kvk_items(self) -> list[ComplianceItem]:
        """KVKK -- Kisisel Verilerin Korunmasi Kanunu."""
        items = []
        # VERBİS kaydı (50+ calisan veya yillik 1M+ TRY)
        verbis_required = (self.headcount >= 50 or self.monthly_rev * 12 >= 1_000_000)
        items.append(ComplianceItem(
            regulation="KVK / VERBİS",
            requirement="Veri Sorumlusu Sicil Bilgi Sistemi Kaydı",
            status="unknown" if verbis_required else "compliant",
            risk_level="high" if verbis_required else "low",
            risk_score=7.0 if verbis_required else 1.0,
            description="50+ calisan veya 1M+ TRY ciro sirketleri VERBİS'e kayit olmak zorunda",
            evidence=f"Headcount: {self.headcount}, Yillik gelir tahmini: ₺{self.monthly_rev*12:,.0f}",
            action="VERBİS kaydini dogrula veya tamamla",
            deadline="Acil (7 gun)" if verbis_required else "Surekli",
        ))

        # Aydinlatma metni
        items.append(ComplianceItem(
            regulation="KVK",
            requirement="Acik Riza / Aydinlatma Metni",
            status="unknown",
            risk_level="medium",
            risk_score=5.0,
            description="Web sitesi ve urun uzerindeki kisisel veri islemeler icin aydinlatma metni zorunlu",
            evidence="Yasal zorunluluk -- tum sirketler",
            action="Gizlilik politikasi ve aydinlatma metnini guncelle",
            deadline="30 gun",
        ))

        # Guvenlik onlemleri (CTO sagligi ile korelasyon)
        if self.tech_security < 6:
            items.append(ComplianceItem(
                regulation="KVK Madde 12",
                requirement="Teknik ve Idari Guvenlik Tedbirleri",
                status="non_compliant",
                risk_level="high",
                risk_score=7.5,
                description=f"IT guvenlik skoru {self.tech_security}/10 -- KVK gereksinimlerin altinda",
                evidence=f"CTO security score: {self.tech_security}",
                action="Sifreleme, erisim kontrolleri ve penetrasyon testi uygula",
                deadline="30 gun",
            ))

        return items

    def _efatura_items(self) -> list[ComplianceItem]:
        """e-Fatura / e-Arsiv -- GIB."""
        items = []
        # 5M TRY ciro esigi (2024 duzeltilmis)
        efatura_required = self.monthly_rev * 12 >= 5_000_000
        items.append(ComplianceItem(
            regulation="e-Fatura (GIB)",
            requirement="e-Fatura Kullanimi",
            status="compliant" if not efatura_required else "unknown",
            risk_level="critical" if efatura_required else "low",
            risk_score=9.0 if efatura_required else 0.5,
            description="Yillik 5M+ TRY ciro sirketleri e-fatura kullanmak zorunda",
            evidence=f"Tahmini yillik ciro: ₺{self.monthly_rev*12:,.0f}",
            action="e-Fatura entegrasyonunu dogrula" if efatura_required else "Izle",
            deadline="Acil (7 gun)" if efatura_required else "Surekli",
        ))

        # e-Arsiv (tum e-ticaret)
        if self.sector in ("ecommerce", "saas"):
            items.append(ComplianceItem(
                regulation="e-Arsiv (GIB)",
                requirement="e-Arsiv Fatura",
                status="unknown",
                risk_level="medium",
                risk_score=5.0,
                description="Son tuketicide yapilan satis faturalari e-arsiv ile duzenlenmelidir",
                evidence=f"Sektor: {self.sector}",
                action="e-Arsiv basvurusunu tamamla",
                deadline="30 gun",
            ))

        return items

    def _sgk_items(self) -> list[ComplianceItem]:
        """SGK -- Sosyal Guvenlik Kurumu."""
        if not self.headcount:
            return []
        items = []
        items.append(ComplianceItem(
            regulation="SGK",
            requirement="Aylik SGK Bildirgeleri ve Prim Odemesi",
            status="unknown",
            risk_level="high",
            risk_score=6.0,
            description=f"{self.headcount} calisan icin aylik SGK bildirgeleri zamaninda verilmeli",
            evidence=f"Headcount: {self.headcount}",
            action="Muhasebe/bordro sisteminin zamaninda bildirim yaptigini dogrula",
            deadline="Surekli (aylik)",
        ))

        # Staj / part-time calisanlar
        items.append(ComplianceItem(
            regulation="SGK / Is Kanunu",
            requirement="Kayit Disi Istihdam Kontrolu",
            status="unknown",
            risk_level="medium",
            risk_score=4.5,
            description="Tum calisanlarin SGK'ya kayitli olmasi zorunlu",
            evidence="Is Kanunu zorunlulugu",
            action="Calisan listesini SGK kayitlariyla kiyasla",
            deadline="30 gun",
        ))

        return items

    def _vuk_items(self) -> list[ComplianceItem]:
        """VUK -- Vergi Usul Kanunu."""
        items = []
        items.append(ComplianceItem(
            regulation="VUK",
            requirement="Muhasebe Kayitlari ve Beyanname",
            status="unknown",
            risk_level="medium",
            risk_score=5.0,
            description="Duzgun muhasebe kaydi ve zamaninda vergi beyannamesi",
            evidence="VUK zorunlulugu -- tum sirketler",
            action="Muhasebecinin (SMMM) beyanname takvimini dogrula",
            deadline="Surekli",
        ))

        # Yuksek gelir = yuksek vergi riski
        if self.monthly_rev > 100_000:
            items.append(ComplianceItem(
                regulation="VUK / KDV",
                requirement="KDV Beyannamesi (Aylik/3 Aylik)",
                status="unknown",
                risk_level="high",
                risk_score=6.5,
                description=f"Aylik ₺{self.monthly_rev:,.0f} ciro KDV beyannamesi zorunlulugu",
                evidence=f"Aylik gelir: ₺{self.monthly_rev:,.0f}",
                action="KDV beyanname takvimini dogrula, eksik odeme varsa duzelticik beyan ver",
                deadline="30 gun",
            ))

        return items

    def _gdpr_items(self) -> list[ComplianceItem]:
        """GDPR -- AB musterisi olan sirketler icin."""
        if not self.eu_customers:
            return []
        return [
            ComplianceItem(
                regulation="GDPR (AB)",
                requirement="Veri Isleme Sozlesmesi (DPA)",
                status="unknown",
                risk_level="high",
                risk_score=7.0,
                description="AB vatandaslarinin verilerini isleyen Turkiye sirketleri GDPR'a tabidir",
                evidence="AB musterisi mevcut",
                action="GDPR uyum degerlendirmesi ve DPA sozlesmesi hazirla",
                deadline="30 gun",
            )
        ]

    def _fintech_items(self) -> list[ComplianceItem]:
        """BDDK / SPK -- Fintech sirketler icin."""
        if not self.is_fintech:
            return []
        return [
            ComplianceItem(
                regulation="BDDK",
                requirement="Odeme Hizmetleri Lisansi",
                status="unknown",
                risk_level="critical",
                risk_score=9.5,
                description="Odeme araciligi yapan sirketler BDDK lisansi almak zorunda",
                evidence="Fintech sirket profili",
                action="BDDK lisans basvurusunu dogrula veya baslat",
                deadline="Acil (7 gun)",
            )
        ]

    def generate(self) -> ComplianceKernelOutput:
        items: list[ComplianceItem] = []
        items.extend(self._kvk_items())
        items.extend(self._efatura_items())
        items.extend(self._sgk_items())
        items.extend(self._vuk_items())
        items.extend(self._gdpr_items())
        items.extend(self._fintech_items())

        # Sayimlar
        compliant    = sum(1 for i in items if i.status == "compliant")
        partial      = sum(1 for i in items if i.status == "partial")
        non_compliant = sum(1 for i in items if i.status == "non_compliant")
        unknown      = sum(1 for i in items if i.status == "unknown")
        critical_v   = sum(1 for i in items if i.risk_level == "critical")

        # Uyum skoru (0-100)
        total = max(1, len(items))
        score = max(0.0, min(100.0, (compliant * 100 + partial * 50) / total))

        # Posture
        if critical_v >= 1 or non_compliant >= 2:
            posture = "non_compliant"
        elif non_compliant >= 1 or unknown >= total * 0.5:
            posture = "at_risk"
        elif partial >= 2:
            posture = "partial"
        else:
            posture = "compliant"

        # Ceza riski tahmini
        risk_map = {"critical": 500_000, "high": 100_000, "medium": 25_000, "low": 5_000}
        exposure = sum(risk_map.get(i.risk_level, 0) for i in items if i.status != "compliant")

        priority = [
            f"[{i.risk_level.upper()}] {i.action} ({i.regulation})"
            for i in sorted(items, key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}[x.risk_level])
            if i.status != "compliant"
        ][:5]

        narrative = (
            f"Uyum degerlendirmesi: {len(items)} gereksinim incelendi. "
            f"Puan: {score:.0f}/100 -- {posture}. "
            f"{critical_v} kritik ihlal. "
            f"Tahmini ceza riski: ₺{exposure:,.0f}."
        )

        return ComplianceKernelOutput(
            overall_compliance_score=round(score, 1),
            compliance_posture=posture,
            total_requirements=total,
            compliant_count=compliant,
            partial_count=partial,
            non_compliant_count=non_compliant,
            unknown_count=unknown,
            critical_violations=critical_v,
            items=items,
            priority_actions=priority,
            regulatory_exposure_try=float(exposure),
            data_source="rule_based",
            confidence=0.75,
            narrative=narrative,
        )


async def run_compliance_kernel(
    pnl:           dict[str, Any] | None = None,
    chro_data:     dict[str, Any] | None = None,
    cto_data:      dict[str, Any] | None = None,
    company_size:  str = "smb",
    sector:        str = "saas",
    has_eu_customers: bool = False,
    is_fintech:    bool = False,
    monthly_invoice_count: int = 0,
) -> dict[str, Any]:
    kernel = ComplianceKernel(
        pnl=pnl, chro_data=chro_data, cto_data=cto_data,
        company_size=company_size, sector=sector,
        has_eu_customers=has_eu_customers, is_fintech=is_fintech,
        monthly_invoice_count=monthly_invoice_count,
    )
    output = kernel.generate()
    from app.platform.provenance import attach_provenance

    return attach_provenance({"ok": True, "output": output.to_dict()})
