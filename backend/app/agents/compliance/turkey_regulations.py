"""
Türkiye Regulatory Knowledge Base

Structured database of key Turkish regulations relevant to SMBs and enterprises.
Used by the Compliance agent to assess company compliance posture against
actual legal requirements.

Regulations covered:
  KVKK  — Kişisel Verilerin Korunması Kanunu (6698 sayılı)
  TTK   — Türk Ticaret Kanunu (6102 sayılı)
  SGK   — Sosyal Güvenlik mevzuatı
  GİB   — Vergi mevzuatı (Gelir Vergisi, KDV, Kurumlar Vergisi)
  İŞKUR — İş ve Sosyal Güvenlik mevzuatı
  SPK   — Sermaye Piyasası Kanunu (halka açık şirketler için)
  BDDK  — Bankacılık mevzuatı (fintech/ödeme hizmeti sağlayıcıları)

Each requirement has:
  - id:          Unique identifier
  - regulation:  Regulation name (KVKK, TTK, etc.)
  - article:     Article number/reference
  - requirement: What the company must do
  - category:    data_privacy | corporate | labor | tax | finance | reporting
  - severity:    critical | high | medium
  - applies_to:  all | sme | large | public | fintech | etc.
  - penalty:     Potential penalty for non-compliance
  - checklist:   List of verifiable controls

This module is designed to be easily extended — add new requirements as dicts.
"""
from __future__ import annotations

from typing import Any

# ── KVKK Requirements ─────────────────────────────────────────────────────────

KVKK_REQUIREMENTS: list[dict[str, Any]] = [
    {
        "id":          "KVKK-001",
        "regulation":  "KVKK",
        "article":     "Madde 10",
        "requirement": "Kişisel veri işleme faaliyetleri için açık aydınlatma yükümlülüğü",
        "category":    "data_privacy",
        "severity":    "critical",
        "applies_to":  "all",
        "penalty":     "50.000 - 1.000.000 TL idari para cezası",
        "checklist": [
            "Aydınlatma metni hazırlanmış ve web sitesine eklenmiş",
            "Çalışanlar için KVKK aydınlatma formu imzalatılmış",
            "Müşteri aydınlatma metni güncel ve erişilebilir",
        ],
    },
    {
        "id":          "KVKK-002",
        "regulation":  "KVKK",
        "article":     "Madde 11",
        "requirement": "İlgili kişinin haklarını kullanabilmesi için başvuru mekanizması kurulması",
        "category":    "data_privacy",
        "severity":    "critical",
        "applies_to":  "all",
        "penalty":     "50.000 - 1.000.000 TL idari para cezası",
        "checklist": [
            "KVKK başvuru formu mevcut ve erişilebilir",
            "Başvurulara 30 gün içinde yanıt verilmesi için süreç tanımlanmış",
            "Başvuru kaydı tutulmakta",
        ],
    },
    {
        "id":          "KVKK-003",
        "regulation":  "KVKK",
        "article":     "Madde 12",
        "requirement": "Kişisel verilerin güvenliği için teknik ve idari tedbirler alınması",
        "category":    "data_privacy",
        "severity":    "critical",
        "applies_to":  "all",
        "penalty":     "100.000 - 1.000.000 TL + hapis cezası (ihmal durumunda)",
        "checklist": [
            "Veri güvenliği politikası yazılı olarak mevcuttur",
            "Kişisel veri erişimleri loglanmaktadır",
            "Çalışan KVKK eğitimleri yapılmaktadır",
            "Veri ihlali bildirim prosedürü tanımlanmıştır (72 saat kuralı)",
        ],
    },
    {
        "id":          "KVKK-004",
        "regulation":  "KVKK",
        "article":     "Madde 16",
        "requirement": "Veri Sorumluları Sicil Bilgi Sistemi'ne (VERBİS) kayıt",
        "category":    "data_privacy",
        "severity":    "high",
        "applies_to":  "all",  # 50+ çalışan veya 25M+ TL ciro
        "penalty":     "20.000 - 1.000.000 TL",
        "checklist": [
            "VERBİS kaydı tamamlanmış",
            "Veri işleme envanteri VERBİS'e girilmiş",
            "VERBİS kayıtları güncel tutulmakta",
        ],
    },
]

# ── TTK Requirements ──────────────────────────────────────────────────────────

TTK_REQUIREMENTS: list[dict[str, Any]] = [
    {
        "id":          "TTK-001",
        "regulation":  "TTK",
        "article":     "Madde 64-88",
        "requirement": "Ticari defterlerin usulüne uygun tutulması",
        "category":    "corporate",
        "severity":    "critical",
        "applies_to":  "all",
        "penalty":     "Defterlerin delil niteliği kaybı + vergi cezaları",
        "checklist": [
            "Yevmiye defteri tutulmakta ve onaylı",
            "Defteri kebir tutulmakta",
            "Envanter defteri tutulmakta",
            "Defterlerde imza ve onay şartları sağlanmış",
        ],
    },
    {
        "id":          "TTK-002",
        "regulation":  "TTK",
        "article":     "Madde 524-528",
        "requirement": "Bağımsız denetim yükümlülüğü (kapsama giren şirketler için)",
        "category":    "corporate",
        "severity":    "high",
        "applies_to":  "large",  # Belirli büyüklük kriterlerini aşan şirketler
        "penalty":     "Yönetim kurulu üyelerinin şahsi sorumluluğu",
        "checklist": [
            "Bağımsız denetim yükümlülüğü analiz edilmiş",
            "Denetçi atanmış (kapsama giriyorsa)",
            "Denetim raporları zamanında hazırlanmış",
        ],
    },
    {
        "id":          "TTK-003",
        "regulation":  "TTK",
        "article":     "Madde 362-375",
        "requirement": "Yönetim kurulu toplantıları ve karar defteri tutulması",
        "category":    "corporate",
        "severity":    "medium",
        "applies_to":  "all",
        "penalty":     "Kararların geçersizliği + tazminat",
        "checklist": [
            "YK toplantıları düzenli yapılmakta",
            "Karar defteri tutulmakta ve imzalı",
            "Toplantı tutanakları arşivlenmekte",
        ],
    },
]

# ── SGK / Labor Requirements ──────────────────────────────────────────────────

SGK_REQUIREMENTS: list[dict[str, Any]] = [
    {
        "id":          "SGK-001",
        "regulation":  "SGK",
        "article":     "5510 s. Kanun Madde 4",
        "requirement": "Tüm çalışanların SGK'ya bildirilmesi (işe giriş bildirimi)",
        "category":    "labor",
        "severity":    "critical",
        "applies_to":  "all",
        "penalty":     "Aylık brüt ücretin %100'ü idari para cezası",
        "checklist": [
            "Tüm çalışanlar işe başlamadan önce SGK'ya bildirilmiş",
            "İşe giriş bildirgesi süresi içinde verilmiş",
            "SGK borcu yok veya yapılandırılmış",
        ],
    },
    {
        "id":          "SGK-002",
        "regulation":  "İş Kanunu",
        "article":     "4857 s. Kanun Madde 8",
        "requirement": "Yazılı iş sözleşmesi düzenlenmesi (≥1 ay süreli işler)",
        "category":    "labor",
        "severity":    "high",
        "applies_to":  "all",
        "penalty":     "1 aylık brüt ücret tutarında ceza",
        "checklist": [
            "Tüm çalışanların imzalı iş sözleşmesi mevcut",
            "Sözleşmeler gerekli bilgileri içeriyor (ücret, görev, süre)",
            "Sözleşme değişiklikleri yazılı olarak yapılmış",
        ],
    },
    {
        "id":          "SGK-003",
        "regulation":  "İş Kanunu",
        "article":     "4857 s. Kanun Madde 63-77",
        "requirement": "Çalışma saatleri, fazla mesai ve izin kayıtlarının tutulması",
        "category":    "labor",
        "severity":    "medium",
        "applies_to":  "all",
        "penalty":     "Fazla mesai ücreti 3 katı + idari para cezası",
        "checklist": [
            "Mesai takip sistemi mevcut",
            "Yıllık izin kayıtları tutulmakta",
            "Fazla mesai ücretleri mevzuata uygun ödenmekte",
        ],
    },
]

# ── Vergi Mevzuatı Requirements ───────────────────────────────────────────────

VERGI_REQUIREMENTS: list[dict[str, Any]] = [
    {
        "id":          "VRG-001",
        "regulation":  "KDV Kanunu",
        "article":     "3065 s. Kanun Madde 29",
        "requirement": "KDV beyannamelerinin aylık olarak verilmesi",
        "category":    "tax",
        "severity":    "critical",
        "applies_to":  "all",
        "penalty":     "Vergi aslının %50'si + gecikme faizi",
        "checklist": [
            "Aylık KDV beyannamesi zamanında verilmekte",
            "KDV ödemeleri (26. gün) takip edilmekte",
            "KDV iade süreçleri yönetilmekte",
        ],
    },
    {
        "id":          "VRG-002",
        "regulation":  "Kurumlar Vergisi",
        "article":     "5520 s. Kanun",
        "requirement": "Geçici vergi ve yıllık kurumlar vergisi beyannamesi",
        "category":    "tax",
        "severity":    "critical",
        "applies_to":  "all",
        "penalty":     "Vergi aslı + %50 ceza + faiz",
        "checklist": [
            "Geçici vergi beyannameleri (3'er aylık) zamanında verilmekte",
            "Yıllık kurumlar vergisi beyannamesi (Nisan ayı) zamanında verilmekte",
            "Vergi karşılıkları muhasebede ayrılmakta",
        ],
    },
    {
        "id":          "VRG-003",
        "regulation":  "Muhtasar",
        "article":     "Gelir Vergisi Kanunu Madde 98",
        "requirement": "Muhtasar ve prim hizmet beyannamesi (aylık/3 aylık)",
        "category":    "tax",
        "severity":    "high",
        "applies_to":  "all",
        "penalty":     "Vergi aslı + %25 ceza",
        "checklist": [
            "Muhtasar beyanname zamanında verilmekte",
            "Çalışan stopaj kesintileri doğru hesaplanmakta",
            "SGK bildirimleriyle uyumlu",
        ],
    },
    {
        "id":          "VRG-004",
        "regulation":  "e-Fatura/e-Defter",
        "article":     "VUK Genel Tebliğleri",
        "requirement": "e-Fatura ve e-Defter zorunluluklarına uyum",
        "category":    "tax",
        "severity":    "high",
        "applies_to":  "all",  # Belirli ciro eşiğini geçenler
        "penalty":     "Özel usulsüzlük cezası (fatura başına)",
        "checklist": [
            "e-Fatura mükellefi olup olmadığı kontrol edilmiş",
            "e-Fatura sistemi aktif ve çalışıyor",
            "e-Defter tutulmakta (kapsama giriyorsa)",
            "e-Arşiv fatura kullanılmakta (kapsama giriyorsa)",
        ],
    },
]

# ── SPK Requirements (halka açık şirketler) ───────────────────────────────────

SPK_REQUIREMENTS: list[dict[str, Any]] = [
    {
        "id":          "SPK-001",
        "regulation":  "SPK",
        "article":     "6362 s. Kanun Madde 17",
        "requirement": "Kamuyu Aydınlatma Platformu'na (KAP) zamanında bildirim",
        "category":    "reporting",
        "severity":    "critical",
        "applies_to":  "public",
        "penalty":     "İdari para cezası + işlem durdurma",
        "checklist": [
            "Özel durum açıklamaları zamanında yapılmakta",
            "Finansal tablolar KAP'a zamanında yüklenmekte",
            "İçeriden öğrenenlerin ticareti politikası mevcut",
        ],
    },
]

# ── Full Knowledge Base ───────────────────────────────────────────────────────

ALL_REQUIREMENTS: list[dict[str, Any]] = (
    KVKK_REQUIREMENTS
    + TTK_REQUIREMENTS
    + SGK_REQUIREMENTS
    + VERGI_REQUIREMENTS
    + SPK_REQUIREMENTS
)

# Index by ID for fast lookup
REQUIREMENTS_BY_ID: dict[str, dict[str, Any]] = {
    req["id"]: req for req in ALL_REQUIREMENTS
}

# Index by regulation
REQUIREMENTS_BY_REGULATION: dict[str, list[dict[str, Any]]] = {}
for req in ALL_REQUIREMENTS:
    REQUIREMENTS_BY_REGULATION.setdefault(req["regulation"], []).append(req)

# Index by category
REQUIREMENTS_BY_CATEGORY: dict[str, list[dict[str, Any]]] = {}
for req in ALL_REQUIREMENTS:
    REQUIREMENTS_BY_CATEGORY.setdefault(req["category"], []).append(req)


def get_applicable_requirements(
    company_size: str = "all",     # all | sme | large | public | fintech
    categories: list[str] | None = None,  # Filter by category
    min_severity: str = "medium",  # minimum severity: critical | high | medium
) -> list[dict[str, Any]]:
    """
    Return requirements applicable to a company profile.

    Args:
        company_size:  Company size/type filter
        categories:    List of categories to include (None = all)
        min_severity:  Minimum severity level

    Returns:
        Filtered list of requirements sorted by severity.
    """
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    min_sev_num = severity_order.get(min_severity, 2)

    filtered: list[dict[str, Any]] = []
    for req in ALL_REQUIREMENTS:
        # Size filter
        applies = req.get("applies_to", "all")
        if applies != "all" and company_size != "all" and applies != company_size:
            continue

        # Severity filter
        if severity_order.get(req.get("severity", "medium"), 2) > min_sev_num:
            continue

        # Category filter
        if categories and req.get("category") not in categories:
            continue

        filtered.append(req)

    filtered.sort(key=lambda r: severity_order.get(r.get("severity", "medium"), 2))
    return filtered
