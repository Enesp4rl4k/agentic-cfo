"""
Model catalog — the model roster, per-model economics, and task→model routing.

This is platform *policy* data (like `policies.py`), not a service: it has no
I/O and no dependencies on other app layers. Both the LLM router
(`app.services.llm_router`) and the Model Gateway (`app.platform.model_gateway`)
import from here so the boundary test can keep `platform` below `services`.
"""
from __future__ import annotations

from dataclasses import dataclass


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


@dataclass
class ModelConfig:
    model_id: str
    max_tokens: int
    temperature: float
    cost_per_1k_in: float   # USD / 1K input tokens
    cost_per_1k_out: float  # USD / 1K output tokens
    supports_vision: bool = False
    context_window: int = 8192


MODELS: dict[str, ModelConfig] = {
    "gpt-3.5-turbo": ModelConfig("gpt-3.5-turbo", 1000, 0.2, 0.0005, 0.0015, context_window=16385),
    "gpt-4o-mini": ModelConfig("gpt-4o-mini", 2000, 0.3, 0.00015, 0.0006, context_window=128000),
    "gpt-4o": ModelConfig("gpt-4o", 4000, 0.3, 0.0025, 0.010, supports_vision=True, context_window=128000),
    "gpt-4o-high": ModelConfig("gpt-4o", 8000, 0.1, 0.0025, 0.010, supports_vision=True, context_window=128000),
}

TASK_TO_MODEL: dict[str, str] = {
    TaskType.CLASSIFY_INTENT: "gpt-4o-mini",
    TaskType.ROUTE_QUERY: "gpt-4o-mini",
    TaskType.SIMPLE_EXTRACTION: "gpt-4o-mini",
    TaskType.KEYWORD_MATCH: "gpt-4o-mini",
    TaskType.TRANSLATE_SHORT: "gpt-4o-mini",
    TaskType.SHORT_NARRATIVE: "gpt-4o-mini",
    TaskType.METRIC_COMMENTARY: "gpt-4o-mini",
    TaskType.ALERT_MESSAGE: "gpt-4o-mini",
    TaskType.QUICK_ANALYSIS: "gpt-4o-mini",
    TaskType.DEEP_ANALYSIS: "gpt-4o",
    TaskType.BOARD_NARRATIVE: "gpt-4o",
    TaskType.SWOT_GENERATION: "gpt-4o",
    TaskType.STRATEGIC_ADVICE: "gpt-4o",
    TaskType.COMPLEX_REASONING: "gpt-4o",
    TaskType.LONG_DOCUMENT: "gpt-4o",
    TaskType.CONTRACT_ANALYSIS: "gpt-4o",
    TaskType.MULTI_PERIOD: "gpt-4o",
}

LONG_PROMPT_CHAR_THRESHOLD = 8000


def select_model(task: str, prompt_length: int = 0) -> ModelConfig:
    """Pure task→model resolution. Raises ValueError for deterministic tasks."""
    if task in DETERMINISTIC_TASKS:
        raise ValueError(
            f"Task '{task}' LLM gerektirmiyor — deterministik hesapla "
            "(does not need an LLM)"
        )
    if prompt_length > LONG_PROMPT_CHAR_THRESHOLD:
        return MODELS["gpt-4o"]  # 128K context
    return MODELS.get(TASK_TO_MODEL.get(task, "gpt-4o"), MODELS["gpt-4o"])
