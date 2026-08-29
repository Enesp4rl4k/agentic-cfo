"""
Muhasebe Agent Orchestrator — MUHASEBE-3

THP sınıflandırıcı + double-entry engine'i birleştiren ana orchestrator.

Akış:
  1. İşlemleri al (Transaction listesi)
  2. Her işlem için THP sınıflandır (kural → LLM fallback)
  3. Her işlem için yevmiye kaydı oluştur (double-entry)
  4. Mizan özeti çıkar
  5. SMMM onayı gereken kayıtları işaretle
  6. Analiz sonucu döndür

Bu agent CFO pipeline'ından bağımsız çalışabilir
ama aynı zamanda auto_chain ile entegre çalışır:
  CFO analizi biter → muhasebe agent tetiklenir → kayıtlar oluşur → SMMM onaylar
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.agents.accounting.double_entry import (
    DoubleEntryEngine,
    YevmiyeKaydi,
    get_double_entry_engine,
)
from app.services.accounting.thp_classifier import (
    THPSonucu,
)

logger = logging.getLogger(__name__)


# ── Sonuç yapısı ─────────────────────────────────────────────────────────────

@dataclass
class MuhasebeSonucu:
    job_id: str
    islem_sayisi: int
    kayit_sayisi: int
    onay_bekleyen: int
    dengeli: bool
    denge_hatalari: list[str] = field(default_factory=list)

    # Hesap bazlı özet
    mizan: dict[str, dict[str, int]] = field(default_factory=dict)

    # THP dağılımı: {hesap_kodu: sayı}
    thp_dagilim: dict[str, int] = field(default_factory=dict)

    # Güven skoru özeti
    ortalama_confidence: float = 0.0
    dusuk_confidence_sayisi: int = 0  # confidence < 0.6

    # Tüm yevmiye kayıtları (seri)
    yevmiye_kayitlari: list[dict[str, Any]] = field(default_factory=list)

    # SMMM onay kuyruğu
    onay_kuyrugu: list[dict[str, Any]] = field(default_factory=list)

    # Meta
    tamamlanma_zamani: str = ""
    hata: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id":                self.job_id,
            "islem_sayisi":          self.islem_sayisi,
            "kayit_sayisi":          self.kayit_sayisi,
            "onay_bekleyen":         self.onay_bekleyen,
            "dengeli":               self.dengeli,
            "denge_hatalari":        self.denge_hatalari,
            "mizan":                 self.mizan,
            "thp_dagilim":           self.thp_dagilim,
            "ortalama_confidence":   round(self.ortalama_confidence, 3),
            "dusuk_confidence_sayisi": self.dusuk_confidence_sayisi,
            "onay_kuyrugu":          self.onay_kuyrugu,
            "tamamlanma_zamani":     self.tamamlanma_zamani,
            "hata":                  self.hata,
        }

    def to_full_dict(self) -> dict[str, Any]:
        """Like `to_dict()` but includes every journal entry — for durable
        persistence (defensibility packet), not the lean API response."""
        return {**self.to_dict(), "yevmiye_kayitlari": self.yevmiye_kayitlari}


# ── Orchestrator ──────────────────────────────────────────────────────────────

class MuhasebeAgent:
    """
    Muhasebe Agent Orchestrator.

    Uses ChartOfAccountsAdapter when regional pack is not TR;
    TR pack keeps native THPClassifier (+ optional LLM fallback).
    """

    def __init__(
        self,
        classifier: Any | None = None,
        engine: DoubleEntryEngine | None = None,
        use_llm_fallback: bool = True,
        regional_packs: list[str] | None = None,
    ) -> None:
        from app.services.regional.coa_bridge import build_classifier_for_packs

        self.regional_packs = [p.lower() for p in (regional_packs or [])]
        self.classifier = classifier or build_classifier_for_packs(
            self.regional_packs, use_llm_fallback=use_llm_fallback
        )
        self.engine = engine or get_double_entry_engine()
        self.use_llm_fallback = use_llm_fallback and ("tr" in self.regional_packs)

    async def run(
        self,
        job_id: str,
        transactions: list[dict[str, Any]],
        company_name: str | None = None,
        donem: str | None = None,
    ) -> MuhasebeSonucu:
        """
        Ana entry point: işlem listesinden tam muhasebe analizi.

        Parameters
        ----------
        job_id : str
            Analiz iş kimliği (takip için)
        transactions : list[dict]
            Transaction modeli listesi (amount_kurus/amount_cents, type, description, vendor, ...)
        company_name : str, optional
            Şirket adı (log/rapor için)
        donem : str, optional
            Dönem bilgisi (ör. "2024-01")
        """
        logger.info(
            "MuhasebeAgent: job=%s transactions=%d company=%s",
            job_id, len(transactions), company_name or "N/A",
        )

        if not transactions:
            return MuhasebeSonucu(
                job_id=job_id,
                islem_sayisi=0,
                kayit_sayisi=0,
                onay_bekleyen=0,
                dengeli=True,
                hata="İşlem listesi boş",
                tamamlanma_zamani=datetime.now(UTC).isoformat(),
            )

        # ── 1. THP Sınıflandırma ──────────────────────────────────────────────
        thp_sonuclari: list[THPSonucu] = []

        for tx in transactions:
            description = tx.get("description") or tx.get("vendor") or ""
            amount = abs(int(tx.get("amount_kurus") or tx.get("amount_cents") or 0))
            tx_type = tx.get("type", "expense")
            vendor = tx.get("vendor")

            if self.use_llm_fallback:
                sonuc = await self.classifier.async_classify(
                    description=description,
                    amount_kurus=amount,
                    transaction_type=tx_type,
                    vendor=vendor,
                )
            else:
                sonuc = self.classifier.classify(
                    description=description,
                    amount_kurus=amount,
                    transaction_type=tx_type,
                    vendor=vendor,
                )
            thp_sonuclari.append(sonuc)

        # ── 2. Yevmiye Kayıtları ──────────────────────────────────────────────
        kayitlar: list[YevmiyeKaydi] = self.engine.create_entries_batch(
            transactions, thp_sonuclari
        )

        # ── 3. Denge kontrolü ─────────────────────────────────────────────────
        dengeli, denge_hatalari = DoubleEntryEngine.verify_balance(kayitlar)
        if not dengeli:
            logger.warning("MuhasebeAgent: denge hatası job=%s: %s", job_id, denge_hatalari)

        # ── 4. Mizan özeti ────────────────────────────────────────────────────
        mizan = DoubleEntryEngine.mizan_ozet(kayitlar)

        # ── 5. İstatistikler ──────────────────────────────────────────────────
        onay_bekleyen = sum(1 for k in kayitlar if k.onay_gerekli)
        toplam_confidence = sum(t.confidence for t in thp_sonuclari)
        ort_confidence = toplam_confidence / len(thp_sonuclari) if thp_sonuclari else 0.0
        dusuk_conf = sum(1 for t in thp_sonuclari if t.confidence < 0.6)

        # THP dağılımı
        thp_dagilim: dict[str, int] = {}
        for sonuc in thp_sonuclari:
            thp_dagilim[sonuc.hesap_kodu] = thp_dagilim.get(sonuc.hesap_kodu, 0) + 1

        # ── 6. Onay kuyruğu ───────────────────────────────────────────────────
        onay_kuyrugu = [
            {
                **kayit.to_dict(),
                "tx_description": transactions[i].get("description", ""),
                "tx_amount_try": abs(int(transactions[i].get("amount_kurus") or
                                        transactions[i].get("amount_cents") or 0)) / 100,
            }
            for i, kayit in enumerate(kayitlar)
            if kayit.onay_gerekli
        ]

        sonuc = MuhasebeSonucu(
            job_id=job_id,
            islem_sayisi=len(transactions),
            kayit_sayisi=len(kayitlar),
            onay_bekleyen=onay_bekleyen,
            dengeli=dengeli,
            denge_hatalari=denge_hatalari,
            mizan=mizan,
            thp_dagilim=thp_dagilim,
            ortalama_confidence=ort_confidence,
            dusuk_confidence_sayisi=dusuk_conf,
            yevmiye_kayitlari=[k.to_dict() for k in kayitlar],
            onay_kuyrugu=onay_kuyrugu,
            tamamlanma_zamani=datetime.now(UTC).isoformat(),
        )

        logger.info(
            "MuhasebeAgent tamamlandı: job=%s kayıt=%d onay_bekleyen=%d dengeli=%s conf=%.2f",
            job_id, len(kayitlar), onay_bekleyen, dengeli, ort_confidence,
        )

        return sonuc

    def run_sync(
        self,
        job_id: str,
        transactions: list[dict[str, Any]],
    ) -> MuhasebeSonucu:
        """
        Senkron çalıştırma (LLM fallback olmadan, sadece kural motoru).
        Test veya hızlı batch işleme için.
        """
        import asyncio
        # Geçici olarak LLM fallback'i kapat
        orig = self.use_llm_fallback
        self.use_llm_fallback = False
        try:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(self.run(job_id, transactions))
            return result
        finally:
            self.use_llm_fallback = orig
            loop.close()


# ── Modül düzeyinde singleton ─────────────────────────────────────────────────

_agent: MuhasebeAgent | None = None
_agent_key: str | None = None


def get_muhasebe_agent(
    use_llm_fallback: bool = True,
    regional_packs: list[str] | None = None,
) -> MuhasebeAgent:
    """
    Return a MuhasebeAgent for the given regional packs.
    Cache key includes packs so TR vs generic adapters don't collide.
    """
    global _agent, _agent_key
    packs = tuple(sorted(p.lower() for p in (regional_packs or [])))
    key = f"{packs}:{use_llm_fallback}"
    if _agent is None or _agent_key != key:
        _agent = MuhasebeAgent(
            use_llm_fallback=use_llm_fallback,
            regional_packs=list(packs),
        )
        _agent_key = key
    return _agent


async def run_muhasebe_pipeline(
    job_id: str,
    transactions: list[dict[str, Any]],
    company_name: str | None = None,
    donem: str | None = None,
    regional_packs: list[str] | None = None,
    include_full_journal: bool = False,
) -> dict[str, Any]:
    """
    Convenience wrapper — auto_chain ve worker entegrasyonu için.

    `include_full_journal=True` adds `yevmiye_kayitlari` (every entry, not just
    the review queue) — used by the defensibility packet path.
    """
    agent = get_muhasebe_agent(regional_packs=regional_packs)
    sonuc = await agent.run(
        job_id=job_id,
        transactions=transactions,
        company_name=company_name,
        donem=donem,
    )
    return sonuc.to_full_dict() if include_full_journal else sonuc.to_dict()
