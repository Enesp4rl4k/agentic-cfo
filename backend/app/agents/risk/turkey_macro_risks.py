"""
Türkiye Makro Risk Faktörleri — S4-3

Türkiye'ye özgü makro ekonomik ve jeopolitik risk faktörleri.
Risk agentı bu verileri KRI analizine overlay olarak kullanır.

Faktörler:
  - Döviz riski (TRY/USD, TRY/EUR volatilitesi)
  - Enflasyon riski (TÜFE, ÜFE)
  - Faiz riski (TCMB politika faizi)
  - Jeopolitik (bölgesel riskler, ticaret ilişkileri)
  - Düzenleyici (BDDK, SPK, KVKK, GİB değişiklikleri)
  - Sektörel (ihracat/ithalat dengesizliği)

Usage:
    from app.agents.risk.turkey_macro_risks import (
        get_macro_risk_context,
        build_macro_risk_prompt_block,
    )
    # Inject into risk agent's LLM prompt
    macro_block = build_macro_risk_prompt_block()
"""
from __future__ import annotations

from typing import Any

# ── Statik makro risk veri tabanı ────────────────────────────────────────────
# Not: Gerçek zamanlı veriler için TCMB EVDS API entegrasyonu gerekir.
# Bu modül sabit referans değerler sağlar; gerçek değerler CompanyContext
# veya harici API ile override edilebilir.

TURKEY_MACRO_RISKS: list[dict[str, Any]] = [
    # ── Döviz Riski ───────────────────────────────────────────────────────────
    {
        "id":        "TR-FX-001",
        "category":  "currency",
        "name":      "TRY Döviz Kuru Volatilitesi",
        "description": "TRY/USD ve TRY/EUR kurlarındaki dalgalanma şirket maliyetlerini etkiler.",
        "severity":  "high",
        "applies_to": ["manufacturing", "import", "tech", "all"],
        "kri_thresholds": {
            "amber": "Aylık TRY değer kaybı > %5",
            "red":   "Aylık TRY değer kaybı > %15 veya 3 ay üst üste değer kaybı",
        },
        "mitigation": [
            "Döviz pozisyonu hedge edilmeli (forward kontrat)",
            "TRY cinsinden sözleşme oranı artırılmalı",
            "Döviz rezervi 3 aylık ithalat giderini karşılamalı",
        ],
        "impact_on_pnl": "İthalat maliyetleri artar, dövizli kredi geri ödemeleri ağırlaşır",
    },
    {
        "id":        "TR-FX-002",
        "category":  "currency",
        "name":      "Dövizli Borç Riski",
        "description": "Döviz cinsinden alınan kredilerin kur riskinden etkilenmesi.",
        "severity":  "critical",
        "applies_to": ["sme", "all"],
        "kri_thresholds": {
            "amber": "Dövizli borç / toplam borç > %30",
            "red":   "Dövizli borç / toplam borç > %50",
        },
        "mitigation": [
            "TRY cinsinden refinansman araştırılmalı",
            "Kur riski sigortası değerlendirilmeli",
        ],
        "impact_on_pnl": "Kur değer kaybında finansman giderleri artar",
    },

    # ── Enflasyon Riski ───────────────────────────────────────────────────────
    {
        "id":        "TR-INF-001",
        "category":  "inflation",
        "name":      "Yüksek Enflasyon Ortamı",
        "description": "Yüksek TÜFE/ÜFE ortamında maliyet baskısı ve talep daralması.",
        "severity":  "high",
        "applies_to": ["all"],
        "kri_thresholds": {
            "amber": "Aylık TÜFE > %3",
            "red":   "Yıllık TÜFE > %50 (enflasyon raporlama eşiği)",
        },
        "mitigation": [
            "Fiyat revizyonu sözleşmelere enflasyon endeksi klozu eklenmeli",
            "Stok yönetimi optimize edilmeli (erken alım vs. just-in-time)",
            "Maaş artışlarında TÜFE + verimlilik formülü uygulanmalı",
        ],
        "impact_on_pnl": "OpEx artar, gerçek satın alma gücü düşer, marj baskısı",
    },
    {
        "id":        "TR-INF-002",
        "category":  "inflation",
        "name":      "Enflasyon Muhasebesi (TMS 29)",
        "description": "Yüksek enflasyon dönemlerinde Türkiye Muhasebe Standartları enflasyon muhasebesi zorunlu kılar.",
        "severity":  "medium",
        "applies_to": ["all"],
        "kri_thresholds": {
            "amber": "3 yıllık kümülatif enflasyon > %100 (TMS 29 eşiği yaklaşımı)",
            "red":   "TMS 29 yükümlülüğü başladı",
        },
        "mitigation": [
            "SMMM/YMM ile enflasyon muhasebesi uygulaması gözden geçirilmeli",
            "Mali tabloların TMS 29 uyumluluğu kontrol edilmeli",
        ],
        "impact_on_pnl": "Varlık değerlemelerini ve özkaynak tutarlarını etkiler",
    },

    # ── Faiz Riski ────────────────────────────────────────────────────────────
    {
        "id":        "TR-INT-001",
        "category":  "interest_rate",
        "name":      "TCMB Politika Faizi Değişimi",
        "description": "TCMB faiz kararları şirketlerin kredi maliyetini doğrudan etkiler.",
        "severity":  "high",
        "applies_to": ["all"],
        "kri_thresholds": {
            "amber": "Politika faizi > %25",
            "red":   "Politika faizi > %40 veya 6 ayda 2+ artış",
        },
        "mitigation": [
            "Sabit faizli kredi tercih edilmeli",
            "Kısa vadeli borç uzun vadeye dönüştürülmeli",
            "Nakit akışı tahminleri faiz senaryoları ile güncellenmeli",
        ],
        "impact_on_pnl": "Finansman giderleri artar, yatırım kararları ertelenebilir",
    },

    # ── Jeopolitik Risk ────────────────────────────────────────────────────────
    {
        "id":        "TR-GEO-001",
        "category":  "geopolitical",
        "name":      "Bölgesel Jeopolitik Gerilim",
        "description": "Türkiye'nin bölgesel konumu tedarik zinciri ve ihracat pazarlarını etkiler.",
        "severity":  "medium",
        "applies_to": ["manufacturing", "export", "logistics"],
        "kri_thresholds": {
            "amber": "Tedarik zincirinde 1+ kritik tedarikçi kayıplandı",
            "red":   "Tedarik zinciri 30+ gün kesintiye uğradı",
        },
        "mitigation": [
            "Tedarikçi çeşitlendirmesi (tek ülke bağımlılığı azaltılmalı)",
            "Kritik hammadde stoku artırılmalı",
            "Alternatif ihracat pazarları geliştirilmeli",
        ],
        "impact_on_pnl": "Lojistik maliyetleri artar, üretim kesintisi olabilir",
    },

    # ── Düzenleyici Risk ──────────────────────────────────────────────────────
    {
        "id":        "TR-REG-001",
        "category":  "regulatory",
        "name":      "Vergi Mevzuatı Değişiklikleri",
        "description": "Sık vergi mevzuatı değişiklikleri uyum maliyeti yaratır.",
        "severity":  "medium",
        "applies_to": ["all"],
        "kri_thresholds": {
            "amber": "Son 12 ayda 3+ vergi düzenlemesi değişti",
            "red":   "Uyumsuzluk cezası veya vergi incelemesi başladı",
        },
        "mitigation": [
            "Güncel SMMM/YMM ile düzenli uyum kontrolü",
            "GİB duyurularını takip eden otomatik bildirim sistemi",
            "Vergi uyum bütçesi yıllık planlamaya dahil edilmeli",
        ],
        "impact_on_pnl": "Uyum maliyeti ve olası ceza riskleri",
    },
    {
        "id":        "TR-REG-002",
        "category":  "regulatory",
        "name":      "KVKK ve Veri Koruma Uyumsuzluk Riski",
        "description": "KVKK uyumsuzluğu ciddi idari para cezası riski taşır.",
        "severity":  "high",
        "applies_to": ["all"],
        "kri_thresholds": {
            "amber": "KVKK aydınlatma metni 12 aydan eski",
            "red":   "KVKVK şikayeti alındı veya inceleme başladı",
        },
        "mitigation": [
            "Yıllık KVKK uyum denetimi yapılmalı",
            "VERBİS kaydı güncel tutulmalı",
            "Çalışan eğitimleri yıllık güncellenmeli",
        ],
        "impact_on_pnl": "50.000 - 1.000.000 TL ceza + itibar hasarı",
    },
]


# ── Yardımcı fonksiyonlar ─────────────────────────────────────────────────────

def get_macro_risk_context(
    categories: list[str] | None = None,
    min_severity: str = "medium",
) -> list[dict[str, Any]]:
    """
    Filtreli Türkiye makro risk listesi döndür.
    Risk agentı LLM prompt'una inject etmek için kullanılır.
    """
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    min_num = severity_order.get(min_severity, 2)

    filtered = [
        r for r in TURKEY_MACRO_RISKS
        if severity_order.get(r.get("severity", "medium"), 2) <= min_num
        and (not categories or r.get("category") in categories)
    ]
    return sorted(filtered, key=lambda r: severity_order.get(r.get("severity", "medium"), 2))


def build_macro_risk_prompt_block(
    categories: list[str] | None = None,
    max_items: int = 5,
) -> str:
    """
    Risk agentı LLM prompt'una eklenecek Türkiye makro risk bloğu.
    """
    risks = get_macro_risk_context(categories=categories)[:max_items]
    if not risks:
        return ""

    lines = ["\n\n## Türkiye Makro Risk Faktörleri\n"]
    for r in risks:
        lines.append(
            f"**[{r['severity'].upper()}] {r['name']}** ({r['category']})\n"
            f"{r['description']}\n"
            f"KRI Eşiği (Kırmızı): {r['kri_thresholds']['red']}\n"
            f"Etki: {r['impact_on_pnl']}\n"
        )
    return "\n".join(lines)


def get_currency_risk_kris() -> list[dict[str, str]]:
    """Pre-built KRI CSV satırları — döviz riski için hazır KRI seti."""
    return [
        {"kri": "TRY/USD Aylık Değişim",   "category": "currency",  "threshold_amber": "5",  "threshold_red": "15", "unit": "%"},
        {"kri": "Dövizli Borç Oranı",       "category": "currency",  "threshold_amber": "30", "threshold_red": "50", "unit": "%"},
        {"kri": "Döviz Rezervi (ay)",       "category": "liquidity", "threshold_amber": "3",  "threshold_red": "1",  "unit": "ay"},
        {"kri": "TÜFE Yıllık",              "category": "inflation", "threshold_amber": "30", "threshold_red": "50", "unit": "%"},
        {"kri": "TCMB Politika Faizi",      "category": "interest",  "threshold_amber": "25", "threshold_red": "40", "unit": "%"},
    ]
