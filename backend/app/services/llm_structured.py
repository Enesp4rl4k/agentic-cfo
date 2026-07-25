"""
LLM Structured Output Service
==============================

Merkezi Pydantic schema'lar ve LangChain `.with_structured_output()` wrapper'ı.

Neden structured output?
  - LLM bazen JSON döner, bazen markdown, bazen düz metin → tutarsız
  - Pydantic validation → yanlış format anında hata verir
  - Frontend her zaman tutarlı alan adları alır
  - LLM key yoksa template-based fallback devreye girer

Kullanım:
    from app.services.llm_structured import get_pnl_narrative, PnLNarrative

    narrative = await get_pnl_narrative(pnl_data, settings)
    # narrative.summary, narrative.risks, narrative.actions guaranteed

Desteklenen agent'lar:
  - PnL (P&L commentary)
  - CashFlow (nakit akışı yorumu)
  - Forecast (tahmin yorumu)
  - Budget (bütçe sapma yorumu)
  - Tax (vergi takvimi özeti)
  - Anomaly (anormal işlem özeti)
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ── Structured Output Schemas ─────────────────────────────────────────────────


class ActionItem(BaseModel):
    """Single actionable item for executive."""
    action: str = Field(description="Yapılması gereken eylem (fiil ile başlar)")
    urgency: str = Field(
        default="normal",
        description="Aciliyet: 'immediate' | 'this_week' | 'this_month' | 'normal'"
    )
    impact: str = Field(
        default="medium",
        description="Etki: 'high' | 'medium' | 'low'"
    )


class RiskItem(BaseModel):
    """Single identified risk."""
    risk: str = Field(description="Risk açıklaması (1-2 cümle)")
    severity: str = Field(
        default="medium",
        description="Seviye: 'critical' | 'high' | 'medium' | 'low'"
    )


class PnLNarrative(BaseModel):
    """Structured P&L narrative from CFO perspective."""
    summary: str = Field(
        description="Finansal durumun genel değerlendirmesi (2-3 cümle, sektör kıyaslamasıyla)"
    )
    highlights: list[str] = Field(
        default_factory=list,
        description="Öne çıkan olumlu noktalar (en fazla 3)",
        max_length=3,
    )
    risks: list[RiskItem] = Field(
        default_factory=list,
        description="Tespit edilen riskler (en fazla 3)",
        max_length=3,
    )
    actions: list[ActionItem] = Field(
        default_factory=list,
        description="Yöneticinin yapması gereken somut adımlar (2-4 eylem)",
        min_length=1,
        max_length=4,
    )
    benchmark_note: str | None = Field(
        default=None,
        description="Sektör karşılaştırması notu (varsa)"
    )

    def to_text(self) -> str:
        """Convert structured narrative to plain text for backward compatibility."""
        parts = [self.summary]
        if self.risks:
            parts.append("\n**Riskler:**")
            for r in self.risks:
                parts.append(f"• [{r.severity.upper()}] {r.risk}")
        if self.actions:
            parts.append("\n**Önerilen Eylemler:**")
            for i, a in enumerate(self.actions, 1):
                parts.append(f"{i}. {a.action}")
        if self.benchmark_note:
            parts.append(f"\n*{self.benchmark_note}*")
        return "\n".join(parts)


class CashFlowNarrative(BaseModel):
    """Structured Cash Flow narrative."""
    summary: str = Field(
        description="Nakit akışının 2-3 cümlelik özeti"
    )
    liquidity_assessment: str = Field(
        description="Likidite durumu değerlendirmesi (güvenli/dikkatli/riskli)"
    )
    risks: list[RiskItem] = Field(
        default_factory=list,
        description="Nakit riski uyarıları (en fazla 3)",
        max_length=3,
    )
    actions: list[ActionItem] = Field(
        default_factory=list,
        description="Nakit yönetimi önerileri (1-3 eylem)",
        max_length=3,
    )
    runway_comment: str | None = Field(
        default=None,
        description="Nakit pisti yorumu (varsa)"
    )

    def to_text(self) -> str:
        parts = [self.summary, self.liquidity_assessment]
        if self.runway_comment:
            parts.append(self.runway_comment)
        if self.risks:
            parts.append("\n**Likidite Riskleri:**")
            for r in self.risks:
                parts.append(f"• {r.risk}")
        if self.actions:
            parts.append("\n**Öneriler:**")
            for a in self.actions:
                parts.append(f"• {a.action}")
        return "\n".join(parts)


class ForecastNarrative(BaseModel):
    """Structured Forecast narrative."""
    summary: str = Field(
        description="12 aylık tahmin özeti (2-3 cümle)"
    )
    base_scenario_comment: str = Field(
        description="Baz senaryonun yorumu"
    )
    key_assumptions: list[str] = Field(
        default_factory=list,
        description="Kritik varsayımlar (en fazla 3)",
        max_length=3,
    )
    risks: list[RiskItem] = Field(
        default_factory=list,
        description="Tahmin riskleri",
        max_length=3,
    )
    actions: list[ActionItem] = Field(
        default_factory=list,
        description="Gelecek dönem için öneriler",
        max_length=3,
    )

    def to_text(self) -> str:
        parts = [self.summary, self.base_scenario_comment]
        if self.key_assumptions:
            parts.append("\n**Temel Varsayımlar:**")
            for a in self.key_assumptions:
                parts.append(f"• {a}")
        if self.risks:
            parts.append("\n**Tahmin Riskleri:**")
            for r in self.risks:
                parts.append(f"• {r.risk}")
        if self.actions:
            parts.append("\n**Öneriler:**")
            for a in self.actions:
                parts.append(f"• {a.action}")
        return "\n".join(parts)


# ── Template-based fallback (no LLM key needed) ───────────────────────────────

def _pnl_narrative_template(pnl: dict[str, Any]) -> PnLNarrative:
    """
    Deterministic narrative based on P&L data.
    Used when LLM key is not configured.
    All thresholds are based on common Turkish KOBİ benchmarks.
    """
    revenue = pnl.get("revenue", 0) / 100
    gross_margin = pnl.get("gross_margin", 0)
    net_margin = pnl.get("net_margin", 0)
    ebitda_margin = pnl.get("ebitda_margin", 0)
    net_income = pnl.get("net_income", 0) / 100

    # Summary
    if net_income > 0 and net_margin > 0.10:
        summary = (
            f"Gelir tablosu güçlü görünüm sergilemektedir. "
            f"₺{revenue:,.0f} gelir üzerinden %{net_margin*100:.1f} net marj elde edilmiştir. "
            f"EBITDA marjı %{ebitda_margin*100:.1f} ile sektör ortalamasının yakınındadır."
        )
    elif net_income > 0:
        summary = (
            f"₺{revenue:,.0f} gelirle kârlı bir dönem geçirilmiştir. "
            f"Net marj %{net_margin*100:.1f} ile kabul edilebilir aralıktadır. "
            f"Brüt kâr marjının %{gross_margin*100:.1f} ile iyileştirme potansiyeli taşıdığı değerlendirilmektedir."
        )
    else:
        summary = (
            f"₺{revenue:,.0f} gelire karşın zarar edilmiştir (net marj: %{net_margin*100:.1f}). "
            f"Gider yapısının acil olarak gözden geçirilmesi önerilmektedir."
        )

    # Risks
    risks = []
    if gross_margin < 0.20:
        risks.append(RiskItem(
            risk=f"Brüt marj %{gross_margin*100:.1f} ile kritik düzeyde düşük — satış fiyatlaması veya tedarik maliyetleri gözden geçirilmeli.",
            severity="critical"
        ))
    elif gross_margin < 0.35:
        risks.append(RiskItem(
            risk=f"Brüt marj %{gross_margin*100:.1f} ile ortalamanın altında — rekabetçi fiyatlandırma baskısı olabilir.",
            severity="high"
        ))

    if net_margin < 0:
        risks.append(RiskItem(
            risk=f"İşletme zararla kapanmaktadır (%{net_margin*100:.1f}) — acil maliyet optimizasyonu gereklidir.",
            severity="critical"
        ))
    elif net_margin < 0.05:
        risks.append(RiskItem(
            risk=f"Net marj %{net_margin*100:.1f} ile çok düşük — herhangi bir negatif şok zarara neden olabilir.",
            severity="high"
        ))

    opex = pnl.get("opex", {})
    salary_ratio = (opex.get("salary", 0) / pnl["revenue"]) if pnl.get("revenue") else 0
    if salary_ratio > 0.50:
        risks.append(RiskItem(
            risk=f"Personel giderleri gelirin %{salary_ratio*100:.0f}'ini oluşturuyor — verimlilik artışı veya otomasyonu değerlendirin.",
            severity="medium"
        ))

    # Actions
    actions = []
    if net_margin < 0.05:
        actions.append(ActionItem(
            action="Operasyonel giderlerin kategori bazında detaylı analizini yapın ve en büyük 3 kalem için tasarruf hedefi belirleyin.",
            urgency="immediate",
            impact="high"
        ))
    if gross_margin < 0.30:
        actions.append(ActionItem(
            action="Tedarikçi fiyatlarını yeniden müzakere edin veya yüksek maliyetli ürün/hizmetlerin fiyatını gözden geçirin.",
            urgency="this_week",
            impact="high"
        ))
    actions.append(ActionItem(
        action="Aylık P&L takibini otomatikleştirin ve kritik marj eşiklerine uyarı kuralları tanımlayın.",
        urgency="this_month",
        impact="medium"
    ))

    return PnLNarrative(
        summary=summary,
        highlights=[
            f"Toplam gelir: ₺{revenue:,.0f}",
            f"Brüt kâr marjı: %{gross_margin*100:.1f}",
        ] if net_income > 0 else [],
        risks=risks[:3],
        actions=actions[:4],
        benchmark_note="Türk KOBİ sektörü median brüt marjı ~%35-40, net marjı ~%5-10 aralığındadır."
    )


def _cashflow_narrative_template(cashflow: dict[str, Any]) -> CashFlowNarrative:
    """Deterministic cash flow narrative."""
    operating = cashflow.get("operating", 0) / 100
    net_change = cashflow.get("net_change", 0) / 100
    alerts = cashflow.get("alerts", [])

    if operating > 0 and net_change > 0:
        liquidity = "güvenli"
        summary = (
            f"Nakit akışı sağlıklı görünümdedir. "
            f"Faaliyet nakit akışı ₺{operating:,.0f} ile pozitiftir. "
            f"Net nakit değişimi ₺{net_change:,.0f} olarak gerçekleşmiştir."
        )
    elif operating > 0:
        liquidity = "dikkatli"
        summary = (
            f"Faaliyet nakit akışı pozitif (₺{operating:,.0f}) olmasına rağmen, "
            f"genel net nakit değişimi ₺{net_change:,.0f} ile negatiftir. "
            f"Yatırım veya finansman faaliyetleri incelenmelidir."
        )
    else:
        liquidity = "riskli"
        summary = (
            f"Faaliyet nakit akışı ₺{operating:,.0f} ile negatiftir. "
            f"İşletme kendi operasyonlarını finanse edememektedir. "
            f"Acil nakit yönetimi müdahalesi gereklidir."
        )

    risks = [
        RiskItem(risk=a.get("message", ""), severity=a.get("level", "medium"))
        for a in alerts[:3]
        if a.get("message")
    ]

    actions = []
    if operating < 0:
        actions.append(ActionItem(
            action="Gecikmiş alacakların tahsili için acil aksiyon planı oluşturun.",
            urgency="immediate",
            impact="high"
        ))
    actions.append(ActionItem(
        action="Haftalık nakit akış tahmini yaparak 4 haftalık likidite pozisyonunu izleyin.",
        urgency="this_week",
        impact="medium"
    ))

    return CashFlowNarrative(
        summary=summary,
        liquidity_assessment=f"Likidite durumu: {liquidity.upper()}",
        risks=risks,
        actions=actions[:3],
    )


def _forecast_narrative_template(forecast: dict[str, Any]) -> ForecastNarrative:
    """Deterministic forecast narrative."""
    scenarios = forecast.get("scenarios", {})
    base = scenarios.get("base", {})
    pessimistic = scenarios.get("pessimistic", {})

    base_net = base.get("twelve_month_net", 0) / 100
    base_runway = base.get("runway_months")
    pess_runway = pessimistic.get("runway_months")

    if base_net > 0:
        summary = (
            f"Baz senaryoda 12 aylık net nakit akışı ₺{base_net:,.0f} olarak öngörülmektedir. "
            f"Mevcut trendler devam ederse şirket sağlıklı büyüme sergileyecektir."
        )
        base_comment = "Baz senaryo mevcut operasyonel parametrelerin korunmasını varsayar."
    else:
        summary = (
            f"Baz senaryoda 12 aylık net nakit akışı ₺{base_net:,.0f} ile negatif öngörülmektedir. "
            f"Mevcut gider yapısında köklü değişiklikler yapılmazsa zorluklar beklenmektedir."
        )
        base_comment = "Baz senaryoda yapısal iyileştirmeler yapılmazsa sürdürülebilirlik riski mevcuttur."

    risks = []
    if pess_runway and pess_runway <= 6:
        risks.append(RiskItem(
            risk=f"Kötümser senaryoda nakit pisti {pess_runway} ay — acil finansman veya maliyet azaltımı planı hazırlayın.",
            severity="critical" if pess_runway <= 3 else "high"
        ))
    if base_runway and base_runway <= 12:
        risks.append(RiskItem(
            risk=f"Baz senaryoda nakit pisti {base_runway} ay — büyüme yatırımları için dış finansman araştırın.",
            severity="medium"
        ))

    actions = [
        ActionItem(
            action="Aylık gerçekleşmeleri tahminle karşılaştırarak sapma analizi yapın.",
            urgency="this_month",
            impact="medium"
        ),
        ActionItem(
            action="Kötümser senaryo için acil eylem planı hazırlayın (hangi giderler kesilecek, hangi gelirler öne alınacak).",
            urgency="this_week",
            impact="high"
        ),
    ]

    return ForecastNarrative(
        summary=summary,
        base_scenario_comment=base_comment,
        key_assumptions=[
            "Mevcut müşteri tabanının korunması",
            "Kur ve enflasyon şoklarının tahmin aralığında kalması",
            "Tedarikçi fiyatlarının öngörülen seviyelerde seyretmesi",
        ],
        risks=risks[:3],
        actions=actions,
    )


# ── LLM-powered structured output ─────────────────────────────────────────────

async def get_pnl_narrative(
    pnl: dict[str, Any],
    settings: Any,
) -> PnLNarrative:
    """
    Generate structured P&L narrative.
    Falls back to template if LLM key is not configured.
    """
    if _is_placeholder_key(settings.openai_api_key):
        logger.debug("LLM key not configured — using template-based P&L narrative")
        return _pnl_narrative_template(pnl)

    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = ChatOpenAI(
            model=settings.llm_model,
            temperature=0.1,
            max_tokens=1024,
            api_key=settings.openai_api_key,
            base_url=settings.llm_base_url or None,
        ).with_structured_output(PnLNarrative)

        revenue = pnl.get("revenue", 0) / 100
        gross_margin = pnl.get("gross_margin", 0)
        net_margin = pnl.get("net_margin", 0)
        ebitda_margin = pnl.get("ebitda_margin", 0)
        net_income = pnl.get("net_income", 0) / 100

        summary_text = (
            f"Gelir: ₺{revenue:,.0f}\n"
            f"Brüt Marj: %{gross_margin*100:.1f}\n"
            f"EBITDA Marjı: %{ebitda_margin*100:.1f}\n"
            f"Net Kâr: ₺{net_income:,.0f} (%{net_margin*100:.1f})\n"
        )

        opex = pnl.get("opex", {})
        if opex:
            opex_lines = "\n".join(
                f"  - {k.replace('_', ' ').title()}: ₺{v/100:,.0f}"
                for k, v in opex.items()
                if v and v > 0
            )
            summary_text += f"\nGider Kalemleri:\n{opex_lines}"

        messages = [
            SystemMessage(content=(
                "Sen deneyimli bir Türk KOBİ CFO'sunun yapay zeka asistanısın. "
                "Verilen gelir tablosu verilerini analiz et ve Türkçe yapılandırılmış bir yönetici özeti oluştur. "
                "Tüm metin alanlarını Türkçe yaz. "
                "Somut, sayısal, eyleme dönüştürülebilir öneriler ver. "
                "Sektör medyanı: brüt marj ~%35-40, net marj ~%5-10."
            )),
            HumanMessage(content=f"Gelir Tablosu:\n{summary_text}"),
        ]

        result = await llm.ainvoke(messages)
        return result  # type: ignore[return-value]

    except Exception as exc:
        logger.warning("LLM structured P&L narrative failed (%s) — using template", exc)
        return _pnl_narrative_template(pnl)


async def get_cashflow_narrative(
    cashflow: dict[str, Any],
    settings: Any,
) -> CashFlowNarrative:
    """Generate structured Cash Flow narrative."""
    if _is_placeholder_key(settings.openai_api_key):
        return _cashflow_narrative_template(cashflow)

    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = ChatOpenAI(
            model=settings.llm_model,
            temperature=0.1,
            max_tokens=800,
            api_key=settings.openai_api_key,
            base_url=settings.llm_base_url or None,
        ).with_structured_output(CashFlowNarrative)

        operating = cashflow.get("operating", 0) / 100
        investing = cashflow.get("investing", 0) / 100
        financing = cashflow.get("financing", 0) / 100
        net_change = cashflow.get("net_change", 0) / 100
        alerts = cashflow.get("alerts", [])

        summary_text = (
            f"Faaliyet Nakit Akışı: ₺{operating:,.0f}\n"
            f"Yatırım Nakit Akışı: ₺{investing:,.0f}\n"
            f"Finansman Nakit Akışı: ₺{financing:,.0f}\n"
            f"Net Nakit Değişimi: ₺{net_change:,.0f}\n"
        )
        if alerts:
            alert_text = "\n".join(f"  - {a.get('message', '')}" for a in alerts[:3])
            summary_text += f"\nMevcut Uyarılar:\n{alert_text}"

        messages = [
            SystemMessage(content=(
                "Sen bir CFO asistanısın. Nakit akışı verilerini analiz et ve "
                "Türkçe yapılandırılmış likidite değerlendirmesi oluştur."
            )),
            HumanMessage(content=f"Nakit Akışı:\n{summary_text}"),
        ]

        result = await llm.ainvoke(messages)
        return result  # type: ignore[return-value]

    except Exception as exc:
        logger.warning("LLM structured cashflow narrative failed (%s) — using template", exc)
        return _cashflow_narrative_template(cashflow)


async def get_forecast_narrative(
    forecast: dict[str, Any],
    settings: Any,
) -> ForecastNarrative:
    """Generate structured Forecast narrative."""
    if _is_placeholder_key(settings.openai_api_key):
        return _forecast_narrative_template(forecast)

    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = ChatOpenAI(
            model=settings.llm_model,
            temperature=0.1,
            max_tokens=800,
            api_key=settings.openai_api_key,
            base_url=settings.llm_base_url or None,
        ).with_structured_output(ForecastNarrative)

        scenarios = forecast.get("scenarios", {})
        lines = []
        for name, s in scenarios.items():
            net = s.get("twelve_month_net", 0) / 100
            runway = s.get("runway_months")
            lines.append(
                f"  {name}: 12 aylık net ₺{net:,.0f}"
                + (f", nakit pisti {runway} ay" if runway else "")
            )

        messages = [
            SystemMessage(content=(
                "Sen bir CFO asistanısın. 12 aylık finansal tahmin verilerini analiz et ve "
                "Türkçe yapılandırılmış tahmin yorumu oluştur."
            )),
            HumanMessage(content="Tahmin Senaryoları:\n" + "\n".join(lines)),
        ]

        result = await llm.ainvoke(messages)
        return result  # type: ignore[return-value]

    except Exception as exc:
        logger.warning("LLM structured forecast narrative failed (%s) — using template", exc)
        return _forecast_narrative_template(forecast)


# ── Helper ────────────────────────────────────────────────────────────────────

def _is_placeholder_key(api_key: str) -> bool:
    """Return True if the API key is a placeholder (dev mode)."""
    if not api_key:
        return True
    placeholders = {"sk-dev-placeholder", "sk-demo-placeholder-replace-with-real-key", ""}
    return api_key in placeholders or api_key.startswith("sk-dev-") or api_key.startswith("sk-demo-")
