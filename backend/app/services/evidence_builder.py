"""
Evidence Builder — S3: Explainability Layer

Her agent çıktısına kanıt zinciri ekler.
Kullanıcılar "AI böyle dedi" yerine "işte kanıtı" görebilir.

Her analiz sonucuna şu alanlar eklenir:
  - transaction_ids: Bu sonucu üreten işlemlerin ID'leri
  - formula: Hesaplama formülü (deterministik)
  - method: "deterministic" | "llm" | "hybrid"
  - confidence: 0.0–1.0
  - data_points: Kullanılan veri noktası sayısı
  - audit_trail: Adım adım hesaplama izi

Kullanım:
    from app.services.evidence_builder import EvidenceBuilder

    eb = EvidenceBuilder()
    pnl_with_evidence = eb.attach_pnl_evidence(pnl, transactions)
    anomaly_with_evidence = eb.attach_anomaly_evidence(anomaly, transactions)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Kanıt yapısı ──────────────────────────────────────────────────────────────

@dataclass
class Evidence:
    """Tek bir analiz sonucu için kanıt zinciri."""
    method: str                         # "deterministic" | "llm" | "hybrid"
    confidence: float                   # 0.0 – 1.0
    formula: str = ""                   # Hesaplama formülü (örn. "Gelir - COGS = Brüt Kâr")
    transaction_ids: list[str] = field(default_factory=list)  # Kaynak işlem ID'leri
    data_points: int = 0                # Kullanılan veri noktası sayısı
    audit_trail: list[str] = field(default_factory=list)      # Adım adım iz
    assumptions: list[str] = field(default_factory=list)      # Varsayımlar

    def to_dict(self) -> dict[str, Any]:
        return {
            "method":          self.method,
            "confidence":      round(self.confidence, 3),
            "formula":         self.formula,
            "transaction_ids": self.transaction_ids[:20],  # max 20 ID frontend'de
            "data_points":     self.data_points,
            "audit_trail":     self.audit_trail,
            "assumptions":     self.assumptions,
        }


def _tx_ids(transactions: list[dict[str, Any]], filter_fn=None) -> list[str]:
    """Filter transactions and return their IDs."""
    if filter_fn:
        return [t.get("id", "") for t in transactions if filter_fn(t) and t.get("id")]
    return [t.get("id", "") for t in transactions if t.get("id")]


# ── EvidenceBuilder ───────────────────────────────────────────────────────────

class EvidenceBuilder:
    """
    Attach evidence metadata to agent outputs.

    Each method takes the computed result dict and the source transactions,
    returns the result dict enriched with an '_evidence' key.
    """

    def attach_pnl_evidence(
        self,
        pnl: dict[str, Any],
        transactions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        S3-2: Attach evidence to P&L result.
        Shows which transactions contributed to revenue, COGS, each opex category.
        """
        income_txs  = [t for t in transactions if t.get("type") == "income"]
        expense_txs = [t for t in transactions if t.get("type") == "expense"]
        cogs_txs    = [t for t in expense_txs if t.get("category") == "cogs"]
        salary_txs  = [t for t in expense_txs if t.get("category") == "salary"]

        revenue = pnl.get("revenue", 0)
        cogs    = pnl.get("cogs", 0)
        gp      = pnl.get("gross_profit", 0)
        ebitda  = pnl.get("ebitda", 0)
        net     = pnl.get("net_income", 0)

        audit_trail = [
            f"Gelir: {len(income_txs)} işlem toplandı → ₺{revenue/100:,.0f}",
            f"SMM: {len(cogs_txs)} işlem → ₺{cogs/100:,.0f}",
            f"Brüt Kâr: ₺{revenue/100:,.0f} - ₺{cogs/100:,.0f} = ₺{gp/100:,.0f}",
            f"EBITDA: Brüt Kâr - OpEx toplamı = ₺{ebitda/100:,.0f}",
            f"Net Gelir: EBITDA - Vergi - Kredi = ₺{net/100:,.0f}",
        ]

        mom = pnl.get("revenue_mom_pct")
        yoy = pnl.get("revenue_yoy_pct")
        if mom is not None:
            audit_trail.append(f"Gelir MoM: {mom:+.1f}%")
        if yoy is not None:
            audit_trail.append(f"Gelir YoY: {yoy:+.1f}%")

        evidence = Evidence(
            method="deterministic",
            confidence=pnl.get("_confidence", 0.95 if revenue > 0 else 0.5),
            formula="Gelir - SMM = Brüt Kâr; Brüt Kâr - OpEx = EBITDA; EBITDA - Vergi - Kredi = Net Gelir",
            transaction_ids=_tx_ids(income_txs) + _tx_ids(cogs_txs) + _tx_ids(salary_txs[:10]),
            data_points=len(transactions),
            audit_trail=audit_trail,
            assumptions=[
                "KDV hariç tutarlar kullanıldı",
                "Kategorisiz işlemler 'other_expense' olarak sınıflandırıldı",
                "Amortisman EBITDA'ya dahil edilmedi (veri yok)",
            ],
        )

        return {**pnl, "_evidence": evidence.to_dict()}

    def attach_cashflow_evidence(
        self,
        cashflow: dict[str, Any],
        transactions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Attach evidence to cash flow result."""
        operating_txs = [t for t in transactions
                         if t.get("category") not in ("loan",) and t.get("type") in ("income", "expense")]
        financing_txs = [t for t in transactions if t.get("category") == "loan"]

        ccc = cashflow.get("ccc_days")
        ccc_trail = f"CCC: DSO({cashflow.get('dso_days', '?')}) - DPO({cashflow.get('dpo_days', '?')}) = {ccc} gün" if ccc is not None else ""

        evidence = Evidence(
            method="deterministic",
            confidence=0.90,
            formula="Faaliyet CF = Faaliyet Geliri - Faaliyet Giderleri; Net CF = Faaliyet + Yatırım + Finansman",
            transaction_ids=_tx_ids(operating_txs[:20]) + _tx_ids(financing_txs),
            data_points=len(transactions),
            audit_trail=[
                f"Faaliyet işlemleri: {len(operating_txs)} adet",
                f"Finansman işlemleri: {len(financing_txs)} adet",
                f"Net CF: ₺{cashflow.get('net_change', 0)/100:,.0f}",
            ] + ([ccc_trail] if ccc_trail else []),
            assumptions=["Yatırım işlemleri (demirbaş) ayrıca tanımlanmamıştır"],
        )

        return {**cashflow, "_evidence": evidence.to_dict()}

    def attach_anomaly_evidence(
        self,
        anomaly: dict[str, Any],
        transactions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Attach evidence to a single anomaly detection result.
        Shows exactly which transactions triggered the anomaly.
        """
        tx_ids = anomaly.get("transaction_ids") or []
        related = [t for t in transactions if t.get("id") in set(tx_ids)]

        evidence_details = []
        for t in related[:5]:
            evidence_details.append(
                f"İşlem {t.get('id', '?')[:8]}: "
                f"₺{t.get('amount_cents', 0)/100:,.0f} "
                f"({t.get('category', '?')}, {str(t.get('transaction_date', ''))[:10]})"
            )

        anomaly_type = anomaly.get("anomaly_type", "unknown")
        anomaly.get("severity", "medium")
        confidence = anomaly.get("confidence", 0.7)

        evidence = Evidence(
            method="deterministic",
            confidence=float(confidence) if confidence else 0.7,
            formula=_anomaly_formula(anomaly_type),
            transaction_ids=tx_ids[:20],
            data_points=len(transactions),
            audit_trail=evidence_details or ["İlgili işlem detayları mevcut değil"],
            assumptions=["Sektör ortalaması verileri kullanılmadı — sadece bu şirkete özgü pattern"],
        )

        return {**anomaly, "_evidence": evidence.to_dict()}

    def attach_forecast_evidence(
        self,
        forecast: dict[str, Any],
        monthly_series: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Attach evidence to forecast result."""
        n_months = len(monthly_series)
        monte_carlo = forecast.get("monte_carlo") or {}
        n_simulations = monte_carlo.get("n_simulations", 0)

        audit_trail = [
            f"Geçmiş veri: {n_months} aylık seri kullanıldı",
            f"Monte Carlo: {n_simulations} simülasyon çalıştırıldı" if n_simulations else "Monte Carlo çalıştırılmadı (yetersiz veri)",
        ]

        if forecast.get("seasonality_applied"):
            audit_trail.append("Mevsimsellik düzeltmesi uygulandı")

        for name, explanation in (forecast.get("scenario_explanation") or {}).items():
            if name != "monte_carlo_summary":
                audit_trail.append(explanation)

        evidence = Evidence(
            method="deterministic" if not forecast.get("narrative") else "hybrid",
            confidence=0.85 if n_months >= 6 else 0.65,
            formula="Üstel ağırlıklı hareketli ortalama + mevsimsel düzeltme + Monte Carlo simülasyonu",
            transaction_ids=[],
            data_points=n_months,
            audit_trail=audit_trail,
            assumptions=[
                "Geçmiş trendlerin devam ettiği varsayıldı",
                "Döviz kuru, enflasyon etkileri modele dahil edilmedi",
                "Olağanüstü olaylar (pandemi, kriz) hariç tutuldu",
            ],
        )

        return {**forecast, "_evidence": evidence.to_dict()}

    def attach_budget_evidence(
        self,
        budget: dict[str, Any],
        transactions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Attach evidence to budget variance result."""
        over_budget = [item for item in budget.get("items", []) if item.get("status") == "over"]

        audit_trail = [
            f"Toplam bütçe kalemi: {len(budget.get('items', []))} kategori",
            f"Bütçe aşımı: {len(over_budget)} kategori",
            f"Toplam sapma: {budget.get('total_variance_pct', 0):+.1f}%",
            f"Bütçe sağlık skoru: {budget.get('health_score', 0):.0%}",
        ]

        for item in over_budget[:3]:
            audit_trail.append(
                f"⚠️ {item['category']}: %{item['variance_pct']:+.1f} aşım "
                f"(₺{item['actual']/100:,.0f} / ₺{item['budgeted']/100:,.0f})"
            )

        expense_txs = [t for t in transactions if t.get("type") == "expense"]

        evidence = Evidence(
            method="deterministic",
            confidence=0.95,
            formula="Sapma = Gerçekleşen - Bütçe; Sapma% = (Sapma / Bütçe) × 100",
            transaction_ids=_tx_ids(expense_txs[:20]),
            data_points=len(expense_txs),
            audit_trail=audit_trail,
            assumptions=["Bütçe verisi kullanıcı tarafından sağlandı"],
        )

        return {**budget, "_evidence": evidence.to_dict()}


def _anomaly_formula(anomaly_type: str) -> str:
    """Return the detection formula for each anomaly type."""
    formulas = {
        "duplicate":              "Hash karşılaştırması: (tarih, tutar, tedarikçi) üçlüsü eşleşmesi",
        "unusual_amount":         "Z-score: |x - μ| / σ > 3.0 → olağandışı tutar",
        "vendor_concentration":   "Herfindahl-Hirschman Index > 0.5 → tedarikçi yoğunlaşması",
        "expense_spike":          "MoM değişim: %30+ artış → gider artışı",
        "round_number":           "Tutar tam yüz veya bin: kural tabanlı pattern",
        "negative_cashflow_streak": "Art arda 2+ ay negatif nakit akışı",
    }
    return formulas.get(anomaly_type, "İstatistiksel anomali tespiti")


# ── Modül düzeyinde singleton ─────────────────────────────────────────────────

_builder = EvidenceBuilder()


def get_evidence_builder() -> EvidenceBuilder:
    return _builder
