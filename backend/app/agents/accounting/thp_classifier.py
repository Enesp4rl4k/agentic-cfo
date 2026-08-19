"""
Tekdüzen Hesap Planı (THP) Sınıflandırıcı — MUHASEBE-1

Türkiye Muhasebe Sistemi Tebliği'ne göre standart hesap kodlarına
otomatik sınıflandırma yapar.

Mimari:
  1. Kural motoru (deterministic, sıfır maliyet) — önce çalışır
  2. LLM fallback (sadece kural motorunun başarısız olduğu durumlar)
  3. Confidence scoring — hangi yöntemle bulunduğunu ve güvenilirliği bildir

THP Ana Sınıflar:
  1xx — Dönen Varlıklar (Nakit, Alacaklar, Stoklar)
  2xx — Duran Varlıklar
  3xx — Kısa Vadeli Yabancı Kaynaklar (Borçlar)
  4xx — Uzun Vadeli Yabancı Kaynaklar
  5xx — Özkaynaklar
  6xx — Gelir Tablosu (Satışlar, Maliyetler, GGiderler)
  7xx — Maliyet Hesapları
  9xx — Nazım Hesaplar

Usage:
    classifier = THPClassifier()
    result = classifier.classify(
        description="Kiralar ödemesi Ocak 2024",
        amount=15000_00,  # kuruş
        transaction_type="expense",
        vendor="ABC Gayrimenkul"
    )
    print(result.hesap_kodu)   # "770"
    print(result.hesap_adi)    # "Genel Yönetim Giderleri"
    print(result.confidence)   # 0.95
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── THP Hesap kodu tanımları ──────────────────────────────────────────────────

@dataclass
class THPHesap:
    kod: str                    # Hesap kodu (ör. "770")
    adi: str                    # Hesap adı (ör. "Genel Yönetim Giderleri")
    ana_grup: str               # Ana grup (ör. "7 - Maliyet Hesapları")
    normal_bakiye: str          # "borç" veya "alacak"
    tip: str                    # "gider" | "gelir" | "varlık" | "borç" | "özkaynak"
    anahtar_kelimeler: list[str] = field(default_factory=list)


# Türkiye THP'nin en sık kullanılan hesapları
THP_HESAPLARI: dict[str, THPHesap] = {
    # ── Dönen Varlıklar (1xx) ─────────────────────────────────────────────────
    "100": THPHesap("100", "Kasa", "1 - Dönen Varlıklar", "borç", "varlık",
                    ["kasa", "nakit", "cash", "para"]),
    "102": THPHesap("102", "Bankalar", "1 - Dönen Varlıklar", "borç", "varlık",
                    ["banka", "bank", "hesap", "eft", "havale", "swift", "transfer"]),
    "120": THPHesap("120", "Alıcılar", "1 - Dönen Varlıklar", "borç", "varlık",
                    ["alacak", "alıcı", "müşteri", "tahsilat", "fatura alacak"]),
    "153": THPHesap("153", "Ticari Mallar", "1 - Dönen Varlıklar", "borç", "varlık",
                    ["stok", "mal alış", "ticari mal", "ürün alım"]),

    # ── Duran Varlıklar (2xx) ─────────────────────────────────────────────────
    "253": THPHesap("253", "Tesis, Makine ve Cihazlar", "2 - Duran Varlıklar", "borç", "varlık",
                    ["makine", "ekipman", "cihaz", "demirbaş", "donanım"]),
    "255": THPHesap("255", "Demirbaşlar", "2 - Duran Varlıklar", "borç", "varlık",
                    ["demirbaş", "ofis ekipman", "mobilya", "bilgisayar alım"]),
    "260": THPHesap("260", "Haklar", "2 - Duran Varlıklar", "borç", "varlık",
                    ["lisans", "patent", "marka", "yazılım lisans", "franchise"]),

    # ── Kısa Vadeli Yabancı Kaynaklar (3xx) ──────────────────────────────────
    "320": THPHesap("320", "Satıcılar", "3 - Kısa Vadeli Yabancı Kaynaklar", "alacak", "borç",
                    ["satıcı", "tedarikçi", "supplier", "borç fatura", "alım borcu"]),
    "360": THPHesap("360", "Ödenecek Vergi ve Fonlar", "3 - Kısa Vadeli Yabancı Kaynaklar", "alacak", "borç",
                    ["kdv", "stopaj", "gelir vergisi ödeme", "kurumlar vergisi", "muhtasar",
                     "vergi öde", "sgk", "bağkur"]),
    "361": THPHesap("361", "Ödenecek Sosyal Güvenlik Kesintileri", "3 - Kısa Vadeli Yabancı Kaynaklar", "alacak", "borç",
                    ["sgk", "sigorta primi", "sosyal güvenlik", "işçi sigortası"]),

    # ── Gelir Tablosu — Satışlar (6xx) ────────────────────────────────────────
    "600": THPHesap("600", "Yurt İçi Satışlar", "6 - Gelir Tablosu", "alacak", "gelir",
                    ["satış", "gelir", "hizmet bedeli", "fatura gelir", "tahsilat",
                     "revenue", "income", "ciro", "satıştan gelir"]),
    "601": THPHesap("601", "Yurt Dışı Satışlar", "6 - Gelir Tablosu", "alacak", "gelir",
                    ["ihracat", "export", "döviz gelir", "yurt dışı satış"]),
    "602": THPHesap("602", "Diğer Gelirler", "6 - Gelir Tablosu", "alacak", "gelir",
                    ["faiz gelir", "kira gelir", "komisyon gelir", "diğer gelir",
                     "other income", "temettü"]),

    # ── Satışların Maliyeti (62x) ─────────────────────────────────────────────
    "620": THPHesap("620", "Satılan Mamüller Maliyeti", "6 - Gelir Tablosu", "borç", "gider",
                    ["üretim maliyet", "mamül maliyet", "cogs", "cost of goods"]),
    "621": THPHesap("621", "Satılan Ticari Mallar Maliyeti", "6 - Gelir Tablosu", "borç", "gider",
                    ["ticari mal maliyet", "satın alma", "mal alış gider"]),

    # ── Faaliyet Giderleri (77x) ──────────────────────────────────────────────
    "740": THPHesap("740", "Hizmet Üretim Maliyeti", "7 - Maliyet Hesapları", "borç", "gider",
                    ["hizmet üretim", "servis maliyeti"]),
    "770": THPHesap("770", "Genel Yönetim Giderleri", "7 - Maliyet Hesapları", "borç", "gider",
                    ["kira", "rent", "ofis", "yönetim gider", "muhasebe ücreti",
                     "danışmanlık", "elektrik", "su", "doğalgaz", "internet",
                     "telefon", "posta", "kırtasiye", "temizlik", "güvenlik"]),
    "771": THPHesap("771", "Pazarlama Satış ve Dağıtım Giderleri", "7 - Maliyet Hesapları", "borç", "gider",
                    ["reklam", "marketing", "pazarlama", "satış gider", "komisyon",
                     "dağıtım", "lojistik", "kargo", "sosyal medya", "google ads",
                     "facebook ads", "dijital pazarlama", "pr "]),
    "772": THPHesap("772", "Araştırma ve Geliştirme Giderleri", "7 - Maliyet Hesapları", "borç", "gider",
                    ["ar-ge", "r&d", "araştırma", "geliştirme", "prototip",
                     "yazılım geliştirme", "inovasyon"]),

    # ── Personel (7x) ─────────────────────────────────────────────────────────
    "730": THPHesap("730", "Genel Üretim Giderleri - Personel", "7 - Maliyet Hesapları", "borç", "gider",
                    ["maaş", "salary", "ücret", "personel", "bordro", "ikramiye",
                     "prim", "izin ücreti", "kıdem tazminat"]),

    # ── Finansman (65x) ───────────────────────────────────────────────────────
    "657": THPHesap("657", "Reeskont Faiz Giderleri", "6 - Gelir Tablosu", "borç", "gider",
                    ["faiz gider", "kredi faiz", "loan interest", "interest expense",
                     "banka faiz", "finansman gider"]),
    "644": THPHesap("644", "Konusu Kalmayan Karşılıklar", "6 - Gelir Tablosu", "alacak", "gelir",
                    ["faiz gelir", "banka faiz gelir", "mevduat faiz"]),

    # ── Vergiler (69x) ───────────────────────────────────────────────────────
    "690": THPHesap("690", "Dönem Karı veya Zararı", "6 - Gelir Tablosu", "borç", "gider",
                    ["kurumlar vergisi", "gelir vergisi yıllık", "vergi karşılık"]),
    "193": THPHesap("193", "Peşin Ödenen Vergi ve Fonlar", "1 - Dönen Varlıklar", "borç", "varlık",
                    ["geçici vergi", "peşin vergi", "vergi avans"]),

    # ── Kredi / Finansman (3xx) ────────────────────────────────────────────────
    "300": THPHesap("300", "Banka Kredileri", "3 - Kısa Vadeli Yabancı Kaynaklar", "alacak", "borç",
                    ["kredi çekim", "banka kredisi", "loan", "kredi kullanım",
                     "borçlanma"]),
    "400": THPHesap("400", "Uzun Vadeli Banka Kredileri", "4 - Uzun Vadeli Yabancı Kaynaklar", "alacak", "borç",
                    ["uzun vadeli kredi", "yatırım kredisi", "mortgage"]),
}


# ── Sınıflandırma sonucu ──────────────────────────────────────────────────────

@dataclass
class THPSonucu:
    hesap_kodu: str
    hesap_adi: str
    ana_grup: str
    normal_bakiye: str      # "borç" | "alacak"
    tip: str                # "gelir" | "gider" | "varlık" | "borç" | "özkaynak"
    confidence: float       # 0.0 – 1.0
    yontem: str             # "kural" | "llm" | "varsayılan"
    aciklama: str           # neden bu hesap seçildi


# ── Kural motoru ──────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Lowercase, Türkçe karakter normalize, noktalama temizle."""
    text = text.lower().strip()
    replacements = {"ı": "i", "ğ": "g", "ü": "u", "ş": "s", "ö": "o", "ç": "c",
                    "İ": "i", "Ğ": "g", "Ü": "u", "Ş": "s", "Ö": "o", "Ç": "c"}
    for k, v in replacements.items():
        text = text.replace(k, v)
    return re.sub(r"[^\w\s]", " ", text)


def _kural_motoru_siniflandir(
    description: str,
    vendor: str | None,
    transaction_type: str,
    amount_kurus: int,
) -> tuple[str, float] | None:
    """
    Kural tabanlı sınıflandırma.
    Döndürür: (hesap_kodu, confidence) veya None
    """
    desc_norm = _normalize(description or "")
    vendor_norm = _normalize(vendor or "")
    combined = f"{desc_norm} {vendor_norm}"

    best_kod: str | None = None
    best_score: float = 0.0

    for kod, hesap in THP_HESAPLARI.items():
        # Tip uyum kontrolü
        if transaction_type == "income" and hesap.tip not in ("gelir", "varlık"):
            # Gelir işlemi → sadece gelir veya varlık hesapları
            # (ama alacak tahsilatı varlık azaltır, borç ödemesi borç azaltır)
            pass  # type kontrolü anahtar kelime eşleşmesine bırak

        score = 0.0
        for anahtar in hesap.anahtar_kelimeler:
            anahtar_norm = _normalize(anahtar)
            if anahtar_norm in combined:
                # Tam eşleşme daha yüksek puan
                if f" {anahtar_norm} " in f" {combined} ":
                    score += 1.0
                else:
                    score += 0.6

        if score > best_score:
            best_score = score
            best_kod = kod

    if best_kod and best_score >= 0.6:
        # Normalize confidence: max ~5 keyword hits = 1.0
        confidence = min(1.0, best_score / 3.0) * 0.9  # max 0.9 for rule-based
        return best_kod, confidence

    return None


# ── LLM fallback ──────────────────────────────────────────────────────────────

async def _llm_siniflandir(
    description: str,
    vendor: str | None,
    transaction_type: str,
    amount_kurus: int,
) -> tuple[str, float] | None:
    """
    LLM ile THP sınıflandırması — kural motoru başarısız olduğunda kullanılır.
    Düşük maliyet için sadece hesap kodu soru/cevap formatı.
    """
    try:
        from app.config import get_settings
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage

        settings = get_settings()
        llm = ChatOpenAI(
            model=settings.llm_model,
            temperature=0.0,
            max_tokens=50,
            api_key=settings.openai_api_key,
            base_url=settings.llm_base_url or None,
        )

        hesap_listesi = "\n".join(
            f"{kod}: {h.adi}" for kod, h in THP_HESAPLARI.items()
        )

        prompt = (
            f"Türkiye Tekdüzen Hesap Planı'na göre aşağıdaki işlemi sınıflandır.\n\n"
            f"İşlem: {description}\n"
            f"Tutar: {amount_kurus / 100:.2f} TRY\n"
            f"Tür: {'Gelir' if transaction_type == 'income' else 'Gider'}\n"
            f"Tedarikçi/Kaynak: {vendor or 'Bilinmiyor'}\n\n"
            f"Hesap kodları:\n{hesap_listesi}\n\n"
            f"Sadece hesap kodunu yaz (örn: 770). Başka bir şey yazma."
        )

        response = await llm.ainvoke([
            SystemMessage(content="Sen Türk muhasebe uzmanısın. Sadece THP hesap kodu döndür."),
            HumanMessage(content=prompt),
        ])

        kod_str = response.content.strip().split()[0]
        if kod_str in THP_HESAPLARI:
            return kod_str, 0.75  # LLM confidence = 0.75
        return None

    except Exception as exc:
        logger.debug("LLM THP sınıflandırma hatası: %s", exc)
        return None


# ── Ana sınıflandırıcı ────────────────────────────────────────────────────────

class THPClassifier:
    """
    Tekdüzen Hesap Planı sınıflandırıcısı.

    Önce kural motoru dener (hızlı, ücretsiz).
    Başarısız olursa LLM kullanır (yavaş, ücretli).
    Her iki yöntem de başarısız olursa tip bazlı varsayılan döndürür.
    """

    def classify(
        self,
        description: str,
        amount_kurus: int,
        transaction_type: str,
        vendor: str | None = None,
    ) -> THPSonucu:
        """
        Senkron sınıflandırma — sadece kural motoru.
        LLM fallback için `async_classify` kullanın.
        """
        result = _kural_motoru_siniflandir(description, vendor, transaction_type, amount_kurus)

        if result:
            kod, confidence = result
            hesap = THP_HESAPLARI[kod]
            return THPSonucu(
                hesap_kodu=kod,
                hesap_adi=hesap.adi,
                ana_grup=hesap.ana_grup,
                normal_bakiye=hesap.normal_bakiye,
                tip=hesap.tip,
                confidence=confidence,
                yontem="kural",
                aciklama=f"Kural motoru eşleşmesi: '{description[:50]}'",
            )

        return self._varsayilan(transaction_type)

    async def async_classify(
        self,
        description: str,
        amount_kurus: int,
        transaction_type: str,
        vendor: str | None = None,
    ) -> THPSonucu:
        """
        Async sınıflandırma — kural motoru + LLM fallback.
        """
        # 1. Kural motoru
        result = _kural_motoru_siniflandir(description, vendor, transaction_type, amount_kurus)
        if result:
            kod, confidence = result
            hesap = THP_HESAPLARI[kod]
            return THPSonucu(
                hesap_kodu=kod,
                hesap_adi=hesap.adi,
                ana_grup=hesap.ana_grup,
                normal_bakiye=hesap.normal_bakiye,
                tip=hesap.tip,
                confidence=confidence,
                yontem="kural",
                aciklama=f"Kural motoru: '{description[:50]}'",
            )

        # 2. LLM fallback
        llm_result = await _llm_siniflandir(description, vendor, transaction_type, amount_kurus)
        if llm_result:
            kod, confidence = llm_result
            hesap = THP_HESAPLARI[kod]
            return THPSonucu(
                hesap_kodu=kod,
                hesap_adi=hesap.adi,
                ana_grup=hesap.ana_grup,
                normal_bakiye=hesap.normal_bakiye,
                tip=hesap.tip,
                confidence=confidence,
                yontem="llm",
                aciklama=f"LLM sınıflandırması: '{description[:50]}'",
            )

        # 3. Varsayılan
        return self._varsayilan(transaction_type)

    @staticmethod
    def _varsayilan(transaction_type: str) -> THPSonucu:
        """Tip bazlı güvenli varsayılan."""
        if transaction_type == "income":
            hesap = THP_HESAPLARI["602"]
            return THPSonucu(
                hesap_kodu="602",
                hesap_adi=hesap.adi,
                ana_grup=hesap.ana_grup,
                normal_bakiye=hesap.normal_bakiye,
                tip=hesap.tip,
                confidence=0.3,
                yontem="varsayılan",
                aciklama="Sınıflandırılamadı — Diğer Gelirler hesabına atandı",
            )
        else:
            hesap = THP_HESAPLARI["770"]
            return THPSonucu(
                hesap_kodu="770",
                hesap_adi=hesap.adi,
                ana_grup=hesap.ana_grup,
                normal_bakiye=hesap.normal_bakiye,
                tip=hesap.tip,
                confidence=0.3,
                yontem="varsayılan",
                aciklama="Sınıflandırılamadı — Genel Yönetim Giderleri hesabına atandı",
            )

    def classify_batch(
        self,
        transactions: list[dict[str, Any]],
    ) -> list[THPSonucu]:
        """Toplu sınıflandırma (senkron, batch için)."""
        return [
            self.classify(
                description=tx.get("description") or tx.get("vendor") or "",
                amount_kurus=int(tx.get("amount_cents") or tx.get("amount_kurus") or 0),
                transaction_type=tx.get("type", "expense"),
                vendor=tx.get("vendor"),
            )
            for tx in transactions
        ]


# ── Modül düzeyinde singleton ─────────────────────────────────────────────────

_default_classifier = THPClassifier()


def get_thp_classifier() -> THPClassifier:
    return _default_classifier
