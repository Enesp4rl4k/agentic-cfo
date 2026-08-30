"""
Double-Entry Engine — MUHASEBE-2

Türk muhasebe sistemine göre her işlem için otomatik
borç/alacak kaydı (çift taraflı kayıt) oluşturur.

Muhasebe'nin temel denklemi:
  Varlıklar = Yabancı Kaynaklar + Özkaynaklar

Her kayıt (JournalEntry) borçlar = alacaklar prensibini korur.

Kullanım:
    engine = DoubleEntryEngine()
    entries = engine.create_entries(transaction, thp_result)
    is_balanced = engine.verify_balance(entries)  # her zaman True olmalı
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.services.accounting.thp_classifier import THP_HESAPLARI, THPSonucu

logger = logging.getLogger(__name__)


# ── Kayıt satırı ──────────────────────────────────────────────────────────────

@dataclass
class KayitSatiri:
    """Tek bir borç veya alacak satırı."""
    hesap_kodu: str
    hesap_adi: str
    borc: int = 0       # kuruş cinsinden
    alacak: int = 0     # kuruş cinsinden
    aciklama: str = ""

    @property
    def net(self) -> int:
        """Borç - Alacak (pozitif = borç bakiye, negatif = alacak bakiye)."""
        return self.borc - self.alacak


@dataclass
class YevmiyeKaydi:
    """Tam bir yevmiye kaydı (birden fazla satırdan oluşabilir)."""
    kayit_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tarih: datetime = field(default_factory=lambda: datetime.now(UTC))
    aciklama: str = ""
    satirlar: list[KayitSatiri] = field(default_factory=list)
    kaynak_islem_id: str = ""       # Transaction.id
    thp_hesap_kodu: str = ""
    confidence: float = 1.0
    onay_gerekli: bool = False      # SMMM onayı gerekiyor mu?
    onay_neden: str = ""
    authority: dict[str, Any] = field(default_factory=dict)  # Yetki Matrisi kararı

    @property
    def toplam_borc(self) -> int:
        return sum(s.borc for s in self.satirlar)

    @property
    def toplam_alacak(self) -> int:
        return sum(s.alacak for s in self.satirlar)

    @property
    def dengeli(self) -> bool:
        return self.toplam_borc == self.toplam_alacak

    def to_dict(self) -> dict[str, Any]:
        return {
            "kayit_id":          self.kayit_id,
            "tarih":             self.tarih.isoformat(),
            "aciklama":          self.aciklama,
            "toplam_borc":       self.toplam_borc,
            "toplam_alacak":     self.toplam_alacak,
            "dengeli":           self.dengeli,
            "confidence":        self.confidence,
            "onay_gerekli":      self.onay_gerekli,
            "onay_neden":        self.onay_neden,
            "authority":         self.authority,
            "thp_hesap_kodu":    self.thp_hesap_kodu,
            "kaynak_islem_id":   self.kaynak_islem_id,
            "satirlar": [
                {
                    "hesap_kodu": s.hesap_kodu,
                    "hesap_adi":  s.hesap_adi,
                    "borc":       s.borc,
                    "alacak":     s.alacak,
                    "aciklama":   s.aciklama,
                }
                for s in self.satirlar
            ],
        }


# ── Karşı hesap belirleme ─────────────────────────────────────────────────────

# Gider/gelir işlemlerinin karşı hesabı genellikle banka veya kasa
_KARSIHESAP_BANKA = "102"   # Bankalar
_KARSIHESAP_KASA  = "100"   # Kasa

def _karsi_hesap_belirle(tx: dict[str, Any]) -> str:
    """
    İşlemin karşı hesabını belirle.
    Ödeme yöntemi bilgisine göre banka veya kasa.
    """
    odeme = (tx.get("payment_method") or tx.get("description") or "").lower()
    if any(k in odeme for k in ["banka", "bank", "eft", "havale", "kart", "card", "pos"]):
        return _KARSIHESAP_BANKA
    # Varsayılan: banka (modern işletmelerde nakit az)
    return _KARSIHESAP_BANKA


# ── Double-entry engine ───────────────────────────────────────────────────────

class DoubleEntryEngine:
    """
    Her işlem için otomatik yevmiye kaydı oluşturur.

    Kural:
      - Gider işlemi:
          BORÇ: Gider Hesabı (ör. 770 Genel Yönetim Giderleri)
          ALACAK: Banka/Kasa (ör. 102 Bankalar)

      - Gelir işlemi:
          BORÇ: Banka/Kasa (ör. 102 Bankalar)
          ALACAK: Gelir Hesabı (ör. 600 Yurt İçi Satışlar)

      - Varlık alımı (demirbaş vs.):
          BORÇ: Varlık Hesabı (ör. 255 Demirbaşlar)
          ALACAK: Banka/Kasa veya Satıcı (320)

      - Borç ödemesi (tedarikçi vs.):
          BORÇ: Borç Hesabı (ör. 320 Satıcılar)
          ALACAK: Banka/Kasa

    SMMM onayı tetikleyiciler:
      - Confidence < 0.6
      - Tutar > 100.000 TRY
      - Sınıflandırma yöntemi = "varsayılan"
      - Varlık alımı (duran varlık)
    """

    # Onay tetikleyici limitler
    ONAY_LIMIT_TRY = 100_000 * 100  # 100.000 TRY in kuruş

    def create_entry(
        self,
        transaction: dict[str, Any],
        thp_result: THPSonucu,
        *,
        authority_rules: list[dict[str, Any]] | None = None,
    ) -> YevmiyeKaydi:
        """
        Tek bir işlem için yevmiye kaydı oluştur.

        transaction: Transaction modeli veya dict (amount_kurus, type, description, ...)
        thp_result:  THPClassifier'dan gelen sınıflandırma sonucu
        """
        amount = abs(int(transaction.get("amount_kurus") or transaction.get("amount_cents") or 0))
        tx_type = transaction.get("type", "expense")
        description = transaction.get("description") or transaction.get("vendor") or ""
        tx_id = transaction.get("id", "")
        tx_date = transaction.get("transaction_date")
        if isinstance(tx_date, str):
            try:
                tx_date = datetime.fromisoformat(tx_date)
            except Exception:
                tx_date = datetime.now(UTC)
        elif tx_date is None:
            tx_date = datetime.now(UTC)

        karsi_hesap_kodu = _karsi_hesap_belirle(transaction)
        karsi_hesap = THP_HESAPLARI.get(karsi_hesap_kodu)
        karsi_hesap_adi = karsi_hesap.adi if karsi_hesap else "Bankalar"

        ana_hesap_adi = thp_result.hesap_adi

        # ── Kayıt satırlarını oluştur ──────────────────────────────────────────
        satirlar: list[KayitSatiri] = []

        if thp_result.tip == "gider":
            # Gider: BORÇ gider hesabı, ALACAK banka
            satirlar = [
                KayitSatiri(thp_result.hesap_kodu, ana_hesap_adi, borc=amount,  aciklama=description),
                KayitSatiri(karsi_hesap_kodu,       karsi_hesap_adi, alacak=amount, aciklama=description),
            ]

        elif thp_result.tip == "gelir":
            # Gelir: BORÇ banka, ALACAK gelir hesabı
            satirlar = [
                KayitSatiri(karsi_hesap_kodu,       karsi_hesap_adi, borc=amount,  aciklama=description),
                KayitSatiri(thp_result.hesap_kodu, ana_hesap_adi, alacak=amount, aciklama=description),
            ]

        elif thp_result.tip == "varlık":
            # Varlık alımı: BORÇ varlık hesabı, ALACAK banka veya satıcı
            if tx_type == "expense":
                # Satın alma
                satirlar = [
                    KayitSatiri(thp_result.hesap_kodu, ana_hesap_adi, borc=amount,  aciklama=description),
                    KayitSatiri(karsi_hesap_kodu,       karsi_hesap_adi, alacak=amount, aciklama=description),
                ]
            else:
                # Tahsilat (alacak tahsilatı gibi)
                satirlar = [
                    KayitSatiri(karsi_hesap_kodu,       karsi_hesap_adi, borc=amount,  aciklama=description),
                    KayitSatiri(thp_result.hesap_kodu, ana_hesap_adi, alacak=amount, aciklama=description),
                ]

        elif thp_result.tip == "borç":
            # Borç: BORÇ borç hesabı (azalma), ALACAK banka
            satirlar = [
                KayitSatiri(thp_result.hesap_kodu, ana_hesap_adi, borc=amount,  aciklama=description),
                KayitSatiri(karsi_hesap_kodu,       karsi_hesap_adi, alacak=amount, aciklama=description),
            ]

        else:
            # Bilinmeyen tip — varsayılan gider gibi davran
            satirlar = [
                KayitSatiri(thp_result.hesap_kodu, ana_hesap_adi, borc=amount,  aciklama=description),
                KayitSatiri(karsi_hesap_kodu,       karsi_hesap_adi, alacak=amount, aciklama=description),
            ]

        # ── Yetki Matrisi: does this entry need human approval, and whose? ────
        from app.platform.authority_matrix import (
            DEFAULT_POLICY_RULES,
            AuthorityRequest,
            evaluate,
        )

        decision = evaluate(
            authority_rules or DEFAULT_POLICY_RULES,
            AuthorityRequest(
                domain="journal_entry",
                amount_kurus=amount,
                category=thp_result.hesap_kodu,
                counterparty=transaction.get("vendor"),
                is_related_party=bool(transaction.get("is_related_party")),
                is_fixed_asset=thp_result.hesap_kodu.startswith("2") and tx_type == "expense",
                confidence=thp_result.confidence,
                classification_method=thp_result.yontem,
            ),
        )

        kayit = YevmiyeKaydi(
            tarih=tx_date,
            aciklama=f"{description[:100]} [{thp_result.hesap_kodu}]",
            satirlar=satirlar,
            kaynak_islem_id=tx_id,
            thp_hesap_kodu=thp_result.hesap_kodu,
            confidence=thp_result.confidence,
            onay_gerekli=decision.needs_review,
            onay_neden=decision.rationale,
        )
        kayit.authority = decision.to_dict()

        if not kayit.dengeli:
            logger.error(
                "DENGE HATASI: işlem=%s borç=%d alacak=%d",
                tx_id, kayit.toplam_borc, kayit.toplam_alacak,
            )

        return kayit

    def create_entries_batch(
        self,
        transactions: list[dict[str, Any]],
        thp_results: list[THPSonucu],
        *,
        authority_rules: list[dict[str, Any]] | None = None,
    ) -> list[YevmiyeKaydi]:
        """Toplu yevmiye kaydı oluştur."""
        return [
            self.create_entry(tx, thp, authority_rules=authority_rules)
            for tx, thp in zip(transactions, thp_results, strict=False)
        ]

    @staticmethod
    def verify_balance(entries: list[YevmiyeKaydi]) -> tuple[bool, list[str]]:
        """
        Tüm kayıtların dengeli olduğunu doğrula.
        Döndürür: (tümü_dengeli, hata_listesi)
        """
        hatalar: list[str] = []
        for entry in entries:
            if not entry.dengeli:
                hatalar.append(
                    f"Kayıt {entry.kayit_id[:8]}: borç={entry.toplam_borc} ≠ alacak={entry.toplam_alacak}"
                )
        return len(hatalar) == 0, hatalar

    @staticmethod
    def mizan_ozet(entries: list[YevmiyeKaydi]) -> dict[str, dict[str, int]]:
        """
        Tüm kayıtlardan hesap bazlı mizan özeti çıkar.
        Döndürür: {hesap_kodu: {"borc": x, "alacak": y, "bakiye": z}}
        """
        mizan: dict[str, dict[str, Any]] = {}

        for entry in entries:
            for satir in entry.satirlar:
                if satir.hesap_kodu not in mizan:
                    mizan[satir.hesap_kodu] = {
                        "hesap_adi": satir.hesap_adi,
                        "borc":      0,
                        "alacak":    0,
                    }
                mizan[satir.hesap_kodu]["borc"]   += satir.borc
                mizan[satir.hesap_kodu]["alacak"] += satir.alacak

        for hesap in mizan.values():
            hesap["bakiye"] = hesap["borc"] - hesap["alacak"]

        return mizan


# ── Modül düzeyinde singleton ─────────────────────────────────────────────────

_engine = DoubleEntryEngine()


def get_double_entry_engine() -> DoubleEntryEngine:
    return _engine
