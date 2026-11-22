"""
Model catalog — the model roster, per-model economics, and task→model routing.

This is platform *policy* data (like `policies.py`), not a service: it has no
I/O and depends only on `app.config`. Both the LLM router
(`app.services.llm_router`) and the Model Gateway (`app.platform.model_gateway`)
import from here so the boundary test can keep `platform` below `services`.

A task maps to a *tier* (cheap / strong), never to a vendor model id. The
concrete model id per tier, and its price, come from settings, so the shipped
default (one `LLM_MODEL` for every tier) works against whatever provider
`LLM_BASE_URL` points at.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


class TaskType:
    """Standard LLM task types (string constants)."""

    CLASSIFY_INTENT = "classify_intent"
    ROUTE_QUERY = "route_query"
    SIMPLE_EXTRACTION = "simple_extraction"
    KEYWORD_MATCH = "keyword_match"
    TRANSLATE_SHORT = "translate_short"

    SHORT_NARRATIVE = "short_narrative"
    METRIC_COMMENTARY = "metric_commentary"
    ALERT_MESSAGE = "alert_message"
    QUICK_ANALYSIS = "quick_analysis"

    DEEP_ANALYSIS = "deep_analysis"
    BOARD_NARRATIVE = "board_narrative"
    SWOT_GENERATION = "swot_generation"
    STRATEGIC_ADVICE = "strategic_advice"
    COMPLEX_REASONING = "complex_reasoning"

    LONG_DOCUMENT = "long_document"
    CONTRACT_ANALYSIS = "contract_analysis"
    MULTI_PERIOD = "multi_period"

    # Deterministic — never routed to an LLM
    CALCULATION = "calculation"
    DATA_TRANSFORM = "data_transform"
    RULE_BASED = "rule_based"


DETERMINISTIC_TASKS = frozenset(
    {TaskType.CALCULATION, TaskType.DATA_TRANSFORM, TaskType.RULE_BASED}
)


logger = logging.getLogger(__name__)


class Tier:
    """Model tiers a task can ask for. The id behind each is deployment config."""

    CHEAP = "cheap"
    STRONG = "strong"


@dataclass
class ModelConfig:
    model_id: str
    tier: str
    # None = "not specified here": the gateway falls back to settings.llm_*.
    max_tokens: int | None = None
    temperature: float | None = None
    # USD / 1K tokens. None = price unknown (cost is recorded as null, not 0).
    cost_per_1k_in: float | None = None
    cost_per_1k_out: float | None = None
    supports_vision: bool = False
    context_window: int = 128000

    @property
    def price_known(self) -> bool:
        return self.cost_per_1k_in is not None and self.cost_per_1k_out is not None


TASK_TO_TIER: dict[str, str] = {
    TaskType.CLASSIFY_INTENT: Tier.CHEAP,
    TaskType.ROUTE_QUERY: Tier.CHEAP,
    TaskType.SIMPLE_EXTRACTION: Tier.CHEAP,
    TaskType.KEYWORD_MATCH: Tier.CHEAP,
    TaskType.TRANSLATE_SHORT: Tier.CHEAP,
    TaskType.SHORT_NARRATIVE: Tier.CHEAP,
    TaskType.METRIC_COMMENTARY: Tier.CHEAP,
    TaskType.ALERT_MESSAGE: Tier.CHEAP,
    TaskType.QUICK_ANALYSIS: Tier.CHEAP,
    TaskType.DEEP_ANALYSIS: Tier.STRONG,
    TaskType.BOARD_NARRATIVE: Tier.STRONG,
    TaskType.SWOT_GENERATION: Tier.STRONG,
    TaskType.STRATEGIC_ADVICE: Tier.STRONG,
    TaskType.COMPLEX_REASONING: Tier.STRONG,
    TaskType.LONG_DOCUMENT: Tier.STRONG,
    TaskType.CONTRACT_ANALYSIS: Tier.STRONG,
    TaskType.MULTI_PERIOD: Tier.STRONG,
}

# Deprecated names still imported by app.services.llm_router (not edited here).
# MODELS answers any key with the strong-tier config; prices are None unless
# configured, so that router's cost arithmetic needs its own follow-up fix.
TASK_TO_MODEL = TASK_TO_TIER


class _LegacyModels(dict[str, "ModelConfig"]):
    def __missing__(self, key: str) -> ModelConfig:
        return config_for_tier(Tier.STRONG)


MODELS: dict[str, ModelConfig] = _LegacyModels()

LONG_PROMPT_CHAR_THRESHOLD = 8000

_warned_unpriced: set[str] = set()


def _settings(settings: Any | None) -> Any:
    if settings is not None:
        return settings
    from app.config import get_settings

    return get_settings()


def model_id_for_tier(tier: str, settings: Any | None = None) -> str:
    """Concrete model id for a tier: the tier override, else `llm_model`."""
    s = _settings(settings)
    override = s.llm_model_cheap if tier == Tier.CHEAP else s.llm_model_strong
    return override or s.llm_model


def price_for(model_id: str, settings: Any | None = None) -> tuple[float, float] | None:
    """(in, out) USD per 1K tokens from `llm_model_prices`, or None if unknown.

    Logs once per model id. Never invents a price and never reuses another
    model's price.
    """
    prices = _settings(settings).llm_model_prices or {}
    hit = prices.get(model_id)
    if hit is None:
        if model_id not in _warned_unpriced:
            _warned_unpriced.add(model_id)
            logger.warning(
                "LLM price unknown for model %r: cost is recorded as null. "
                "Set LLM_MODEL_PRICES to track spend.", model_id,
            )
        return None
    return float(hit[0]), float(hit[1])


def config_for_model(
    model_id: str, tier: str = Tier.STRONG, settings: Any | None = None,
) -> ModelConfig:
    p = price_for(model_id, settings)
    return ModelConfig(
        model_id=model_id,
        tier=tier,
        cost_per_1k_in=p[0] if p else None,
        cost_per_1k_out=p[1] if p else None,
        supports_vision=tier == Tier.STRONG,
    )


def config_for_tier(tier: str, settings: Any | None = None) -> ModelConfig:
    return config_for_model(model_id_for_tier(tier, settings), tier, settings)


def select_model(
    task: str, prompt_length: int = 0, settings: Any | None = None,
) -> ModelConfig:
    """Pure task→model resolution. Raises ValueError for deterministic tasks."""
    if task in DETERMINISTIC_TASKS:
        raise ValueError(
            f"Task '{task}' LLM gerektirmiyor — deterministik hesapla "
            "(does not need an LLM)"
        )
    if prompt_length > LONG_PROMPT_CHAR_THRESHOLD:
        return config_for_tier(Tier.STRONG, settings)
    return config_for_tier(TASK_TO_TIER.get(task, Tier.STRONG), settings)


def llm_config_report(
    settings: Any | None = None, api_key_configured: bool | None = None,
) -> dict[str, Any]:
    """Which base_url host and model ids are configured. No network, no key."""
    s = _settings(settings)
    base = getattr(s, "llm_base_url", "") or ""
    host = urlsplit(base).netloc or "(provider default)"
    return {
        "base_url_host": host,
        "models": {t: model_id_for_tier(t, s) for t in (Tier.CHEAP, Tier.STRONG)},
        "priced_models": sorted((s.llm_model_prices or {}).keys()),
        "api_key_configured": api_key_configured,
        "ready": bool(api_key_configured),  # a key is set; the provider is not asked
    }


def cost_usd(cfg: ModelConfig, in_tok: int, out_tok: int) -> float | None:
    if cfg.cost_per_1k_in is None or cfg.cost_per_1k_out is None:
        return None
    return round((in_tok * cfg.cost_per_1k_in + out_tok * cfg.cost_per_1k_out) / 1000, 6)


def http_status(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return status if isinstance(status, int) else None


def is_provider_rejection(exc: BaseException) -> bool:
    """4xx means the request itself is refused (bad model, bad key): retrying
    cannot help. 408 and 429 are transient and stay retryable."""
    status = http_status(exc)
    return status is not None and 400 <= status < 500 and status not in (408, 429)
