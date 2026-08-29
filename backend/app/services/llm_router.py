"""
LLM Task Router

DDIA prensibine gore: farkli okuma patternleri icin farkli storage.
Ayni sekilde: farkli LLM gorevleri icin farkli modeller.

Kural: "doğru araç doğru iş için"
  - Sınıflandırma/routing → GPT-3.5-turbo (hızlı, ucuz)
  - Kısa narrative      → GPT-4o-mini
  - Derin analiz        → GPT-4o
  - Uzun doküman        → Claude 3.5 Sonnet (128K context)
  - Deterministik hesap → LLM YOK (Python)

Maliyet tasarrufu örneği:
  Intent classification: GPT-3.5 → $0.002 / 1K token (vs GPT-4o $0.015)
  %85 işlem basit sınıflandırma → %73 maliyet tasarrufu

Kullanim:
    router = get_llm_router()

    # Otomatik model seçimi
    result = await router.complete(
        task="classify_intent",
        prompt="Bu sorunun intent'i nedir?",
        context={"query": "..."},
    )

    # Manuel model override
    result = await router.complete(
        task="deep_analysis",
        prompt="...",
        model_override="gpt-4o",
    )
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ── Model catalog (moved to app.platform.model_catalog) ──────────────────────
# Re-exported for backwards compatibility. New code should import from
# app.platform.model_catalog directly.
from app.platform.model_catalog import (
    MODELS,
    TASK_TO_MODEL,
    ModelConfig,
    TaskType,
)
from app.platform.model_catalog import select_model as _catalog_select_model

__all__ = [
    "MODELS",
    "TASK_TO_MODEL",
    "LLMResponse",
    "LLMTaskRouter",
    "ModelConfig",
    "TaskType",
    "get_llm_router",
]

# ── LLM çağrı sonucu ──────────────────────────────────────────────────────────

@dataclass
class LLMResponse:
    content:      str
    model_used:   str
    task_type:    str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms:   float = 0.0
    cost_usd:     float = 0.0
    from_cache:   bool = False


# ── LLM Task Router ──────────────────────────────────────────────────────────

class LLMTaskRouter:
    """
    Görev tipine göre doğru LLM modelini seçen akıllı router.

    DDIA prensipleri:
    - Separation of concerns: routing kararı ayrı, LLM çağrısı ayrı
    - Observability: her çağrının maliyeti ve latency'si loglanır
    - Graceful degradation: model yoksa bir sonrakine düş
    - Caching: aynı prompt → aynı cevap (idempotent task'lar için)
    """

    def __init__(self, settings: Any = None) -> None:
        self._settings  = settings
        self._cache:    dict[str, str] = {}  # basit in-memory cache
        self._stats:    dict[str, Any] = {
            "calls": 0, "total_cost_usd": 0.0, "saved_usd": 0.0
        }

    def select_model(self, task: str, prompt_length: int = 0) -> ModelConfig:
        """Görev tipine göre model seç — kural app.platform.model_catalog'da."""
        return _catalog_select_model(task, prompt_length)

    async def complete(
        self,
        task:           str,
        prompt:         str,
        system_prompt:  str | None = None,
        model_override: str | None = None,
        use_cache:      bool = False,
        org_id:         str | None = None,
    ) -> LLMResponse:
        """
        Göreve uygun modelle LLM tamamlama yap.

        Parametreler:
            task:           TaskType sabitlerinden biri
            prompt:         Kullanıcı promptu
            system_prompt:  Sistem promptu (None = varsayılan)
            model_override: Model seçimini zorla (test için)
            use_cache:      True ise aynı prompt için cache kullan
            org_id:         Kullanım takibi için org ID
        """
        start = time.time()

        # Cache kontrolü
        if use_cache:
            cache_key = f"{task}:{hash(prompt)}"
            if cache_key in self._cache:
                return LLMResponse(
                    content     = self._cache[cache_key],
                    model_used  = "cache",
                    task_type   = task,
                    from_cache  = True,
                )

        # Model seç
        if model_override:
            config = MODELS.get(model_override, MODELS["gpt-4o"])
        else:
            config = self.select_model(task, len(prompt))

        # Varsayılan sistem promptu
        if system_prompt is None:
            system_prompt = (
                "Sen C-Suite düzeyinde Türk iş danışmanısın. "
                "Kısa, net ve eyleme dönüştürülebilir cevaplar ver. "
                "Sayısal verileri vurgula."
            )

        # LLM çağrısı
        try:
            response_text, in_tok, out_tok = await self._call_llm(
                config        = config,
                prompt        = prompt,
                system_prompt = system_prompt,
            )

            latency = (time.time() - start) * 1000
            cost    = (in_tok * config.cost_per_1k_in + out_tok * config.cost_per_1k_out) / 1000

            # İstatistik güncelle
            self._stats["calls"] += 1
            self._stats["total_cost_usd"] = round(
                self._stats["total_cost_usd"] + cost, 6
            )

            # Ucuz model kullandıysak tasarrufu hesapla
            expensive_cost = (in_tok * MODELS["gpt-4o"].cost_per_1k_in +
                              out_tok * MODELS["gpt-4o"].cost_per_1k_out) / 1000
            saved = max(0, expensive_cost - cost)
            self._stats["saved_usd"] = round(self._stats["saved_usd"] + saved, 6)

            # Cache'e yaz
            if use_cache:
                self._cache[cache_key] = response_text  # type: ignore[possibly-undefined]

            logger.debug(
                "LLM task=%s model=%s tokens=%d/%d cost=$%.4f latency=%.0fms",
                task, config.model_id, in_tok, out_tok, cost, latency,
            )

            return LLMResponse(
                content       = response_text,
                model_used    = config.model_id,
                task_type     = task,
                input_tokens  = in_tok,
                output_tokens = out_tok,
                latency_ms    = round(latency, 1),
                cost_usd      = round(cost, 6),
            )

        except Exception as exc:
            logger.error("LLM task router hatasi: task=%s model=%s err=%s", task, config.model_id, exc)
            # Graceful degradation: basit fallback
            return LLMResponse(
                content    = f"[LLM hatası: {exc}]",
                model_used = config.model_id,
                task_type  = task,
            )

    async def _call_llm(
        self,
        config:        ModelConfig,
        prompt:        str,
        system_prompt: str,
    ) -> tuple[str, int, int]:
        """
        Gerçek LLM API çağrısı.

        ``ChatOpenAI`` doğrudan burada kurulmaz — tek çıkış kapısı olan
        ``app.platform.model_gateway`` üzerinden gider (retry / timeout / trace
        orada uygulanır). Lazy import: gateway bu modülü import ettiği için.
        """
        try:
            from app.platform.model_gateway import _raw_chat

            text, _parsed, in_tok, out_tok = await _raw_chat(
                config,
                system_prompt,
                prompt,
                schema=None,
                temperature=None,
                max_tokens=None,
            )
            return text, int(in_tok), int(out_tok)

        except Exception as exc:
            raise RuntimeError(f"LLM API çağrısı başarısız: {exc}") from exc

    def get_stats(self) -> dict[str, Any]:
        """Router istatistiklerini dön."""
        return {
            **self._stats,
            "cache_size":   len(self._cache),
            "avg_cost_usd": round(
                self._stats["total_cost_usd"] / max(1, self._stats["calls"]), 6
            ),
        }

    def cost_estimate(self, task: str, estimated_tokens: int = 500) -> float:
        """Bir görevin tahmini maliyetini hesapla (USD)."""
        try:
            config = self.select_model(task)
            return round(
                (estimated_tokens * config.cost_per_1k_in +
                 estimated_tokens * 0.5 * config.cost_per_1k_out) / 1000,
                6,
            )
        except ValueError:
            return 0.0


# ── Global singleton ──────────────────────────────────────────────────────────

_router_instance: LLMTaskRouter | None = None


def get_llm_router() -> LLMTaskRouter:
    """Global LLM router singleton."""
    global _router_instance
    if _router_instance is None:
        _router_instance = LLMTaskRouter()
    return _router_instance
