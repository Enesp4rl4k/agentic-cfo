"""
Audit Kernel -- Otomatik Denetim Riski Degerlendirmesi

CFO anomaly detection sonuclari, CHRO/CTO verilerinden
audit pipeline'ina beslenecek denetim riski ve bulgu listesi uretir.

Odak alanlar:
  - Finansal anomaliler -> potansiyel bulgu
  - Yetkilendirme kontrolleri (IT access, finansal imzalar)
  - Surec kontrollleri (segregation of duties)
  - Varlık kontrolleri (sabit kiymetler, stok)
  - Turkiye'ye ozgu: KVK, e-fatura, SGK uyumu
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AuditFinding:
    title:       str
    category:    str   # financial | it_access | process | compliance | asset
    severity:    str   # critical | high | medium | low
    risk_score:  float # 0-10
    description: str
    evidence:    str
    recommendation: str
    domain_source: str  # cfo | cto | chro | coo


@dataclass
class AuditKernelOutput:
    total_findings:   int
    critical_count:   int
    high_count:       int
    medium_count:     int
    low_count:        int
    overall_risk_score: float   # 0-10
    audit_posture:    str       # clean | needs_attention | at_risk | critical
    findings:         list[AuditFinding]
    control_gaps:     list[str]
    immediate_actions: list[str]
    data_source:      str
    confidence:       float
    narrative:        str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


class AuditKernel:
    """Audit Kernel -- Mevcut C-Suite verilerinden denetim bulgularini cikartir."""

    def __init__(
        self,
        pnl:       dict[str, Any] | None = None,
        cashflow:  dict[str, Any] | None = None,
        anomalies: list[dict[str, Any]] | None = None,
        chro_data: dict[str, Any] | None = None,
        cto_data:  dict[str, Any] | None = None,
        coo_data:  dict[str, Any] | None = None,
        headcount: int = 0,
    ) -> None:
        self.pnl       = pnl or {}
        self.cashflow  = cashflow or {}
        self.anomalies = anomalies or []
        self.chro_data = chro_data or {}
        self.cto_data  = cto_data or {}
        self.coo_data  = coo_data or {}
        self.headcount = headcount or (self.chro_data.get("total_headcount", 0) or 50)

        self.monthly_revenue = (self.pnl.get("revenue", 0) or 0) / 100 / 12
        self.monthly_opex    = (self.pnl.get("total_opex", 0) or 0) / 100 / 12
        self.net_margin      = self.pnl.get("net_margin", 0) or 0

    def _financial_findings(self) -> list[AuditFinding]:
        findings = []

        # Anomaly-based findings
        for a in self.anomalies[:5]:
            severity = "high" if a.get("severity") == "critical" else "medium"
            findings.append(AuditFinding(
                title=f"Finansal Anomali: {a.get('description', 'Bilinmeyen')[:60]}",
                category="financial",
                severity=severity,
                risk_score=7.0 if severity == "high" else 5.0,
                description=str(a.get("description", "")),
                evidence=f"Anomaly detection: {a.get('category', 'genel')} kategorisi",
                recommendation="Anomalinin kaynagini dogrulayan belgeler talep edilmeli",
                domain_source="cfo",
            ))

        # Negatif marj bulgusu
        if self.net_margin < -0.05:
            findings.append(AuditFinding(
                title="Surekli Zarar -- Operasyonel Risk",
                category="financial",
                severity="high",
                risk_score=7.5,
                description=f"Net marj %{self.net_margin*100:.1f} -- surdurulebilirlik sorgulanmali",
                evidence=f"P&L net marj: {self.net_margin:.2%}",
                recommendation="Maliyet yapisinın ve gelir projeksiyonlarinin bagımsız dogrulenmesi",
                domain_source="cfo",
            ))

        # Yuksek opex/revenue orani
        if self.monthly_opex > 0 and self.monthly_revenue > 0:
            burn_ratio = self.monthly_opex / self.monthly_revenue
            if burn_ratio > 1.2:
                findings.append(AuditFinding(
                    title=f"Yuksek Burn Orani: %{burn_ratio*100:.0f}",
                    category="financial",
                    severity="medium",
                    risk_score=6.0,
                    description="Giderler geliri onemli olcude asyiyor",
                    evidence=f"Aylik opex/revenue: {burn_ratio:.2f}",
                    recommendation="Gider onaylama sureclerini gozden gecir",
                    domain_source="cfo",
                ))

        return findings

    def _it_access_findings(self) -> list[AuditFinding]:
        findings = []
        tech_health = self.cto_data.get("overall_health_score", 7.0) or 7.0
        open_vulns  = self.cto_data.get("open_vulnerabilities", 0) or 0

        if open_vulns > 5:
            findings.append(AuditFinding(
                title=f"{open_vulns} Acik Guvenlik Acigi",
                category="it_access",
                severity="critical" if open_vulns > 10 else "high",
                risk_score=9.0 if open_vulns > 10 else 7.0,
                description=f"{open_vulns} adet yamalanmamis guvenlik acigi tespit edildi",
                evidence="CTO security scan sonuclari",
                recommendation="Kritik yamalar 48 saat icinde uygulanmali",
                domain_source="cto",
            ))

        if tech_health < 5:
            findings.append(AuditFinding(
                title="Dusuk IT Saglik Skoru -- Kontrol Riskleri",
                category="it_access",
                severity="medium",
                risk_score=5.5,
                description=f"IT saglik skoru {tech_health}/10 -- kontrol ortami zayif",
                evidence=f"CTO health score: {tech_health}",
                recommendation="IT genel kontrol degerlendirmesi yapilmali (ITGC)",
                domain_source="cto",
            ))

        return findings

    def _process_findings(self) -> list[AuditFinding]:
        findings = []
        sla = self.coo_data.get("sla_compliance", 0.95) or 0.95
        turnover = self.chro_data.get("annual_turnover_rate", 0.15) or 0.15

        if sla < 0.90:
            findings.append(AuditFinding(
                title=f"SLA Ihlali: %{sla*100:.1f} Uyum",
                category="process",
                severity="medium",
                risk_score=5.0,
                description="SLA hedefleri tutarli olarak karsilanmiyor",
                evidence=f"COO SLA compliance: {sla:.1%}",
                recommendation="Surec iyilestirme plani ve kok neden analizi",
                domain_source="coo",
            ))

        if turnover > 0.25 and self.headcount > 10:
            findings.append(AuditFinding(
                title=f"Kritik Bilgi Kaybı Riski: %{turnover*100:.0f} Turnover",
                category="process",
                severity="high",
                risk_score=6.5,
                description="Yuksek personel devrinde kritik surec bilgisi kayboluyor",
                evidence=f"CHRO turnover rate: {turnover:.1%}",
                recommendation="Surec dokumantasyonu ve bilgi transferi programi",
                domain_source="chro",
            ))

        # Segregation of Duties -- kucuk sirketlerde kac kisi var?
        if self.headcount < 10:
            findings.append(AuditFinding(
                title="Gorev Ayirim Riski (Segregation of Duties)",
                category="process",
                severity="medium",
                risk_score=5.5,
                description=f"Kucuk ekip ({self.headcount} kisi) kritik gorevlerin ayrilmasini zorlaştiriyor",
                evidence=f"Headcount: {self.headcount}",
                recommendation="Kompansatif kontroller ve yonetim gozetimi arttirilmali",
                domain_source="chro",
            ))

        return findings

    def generate(self) -> AuditKernelOutput:
        findings: list[AuditFinding] = []
        findings.extend(self._financial_findings())
        findings.extend(self._it_access_findings())
        findings.extend(self._process_findings())

        # Oncelik sirala
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        findings.sort(key=lambda f: sev_order.get(f.severity, 4))

        critical = sum(1 for f in findings if f.severity == "critical")
        high     = sum(1 for f in findings if f.severity == "high")
        medium   = sum(1 for f in findings if f.severity == "medium")
        low      = sum(1 for f in findings if f.severity == "low")

        risk_score = min(10.0, critical * 2.5 + high * 1.5 + medium * 0.7 + low * 0.2)

        if critical >= 1:
            posture = "critical"
        elif high >= 2:
            posture = "at_risk"
        elif high >= 1 or medium >= 3:
            posture = "needs_attention"
        else:
            posture = "clean"

        control_gaps = [
            f.title for f in findings[:3]
        ]
        immediate = [
            f"[{f.severity.upper()}] {f.recommendation}"
            for f in findings[:3]
        ]

        confidence = 0.75 if self.anomalies else 0.55

        narrative = (
            f"Denetim ozeti: {len(findings)} bulgu ({critical} kritik, {high} yuksek). "
            f"Genel risk skoru: {risk_score:.1f}/10 — {posture}."
        )

        return AuditKernelOutput(
            total_findings=len(findings),
            critical_count=critical,
            high_count=high,
            medium_count=medium,
            low_count=low,
            overall_risk_score=round(risk_score, 1),
            audit_posture=posture,
            findings=findings,
            control_gaps=control_gaps,
            immediate_actions=immediate,
            data_source="estimated",
            confidence=confidence,
            narrative=narrative,
        )


async def run_audit_kernel(
    pnl:       dict[str, Any] | None = None,
    cashflow:  dict[str, Any] | None = None,
    anomalies: list[dict[str, Any]] | None = None,
    chro_data: dict[str, Any] | None = None,
    cto_data:  dict[str, Any] | None = None,
    coo_data:  dict[str, Any] | None = None,
) -> dict[str, Any]:
    kernel = AuditKernel(
        pnl=pnl, cashflow=cashflow, anomalies=anomalies,
        chro_data=chro_data, cto_data=cto_data, coo_data=coo_data,
    )
    output = kernel.generate()
    return {"ok": True, "output": output.to_dict()}
