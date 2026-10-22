"""P4 trigger engine (Tetikleyici Motoru).

P4-0: the condition DSL + the trigger envelope contracts.
P4-1 (bu paket): ``trigger_definitions`` / ``trigger_runs`` tables, the
evaluation engine with idempotency + audit (``engine.handle_event``), and the
action registry with ``alert.dispatch`` (``actions.ACTION_REGISTRY``).
P4-2: the remaining concrete actions (analysis.start, cascade.simulate,
report.generate, webhook.call). P4-3: event sources. P4-4: /tetikler UI.
"""
from app.services.triggers.actions import ACTION_REGISTRY
from app.services.triggers.conditions import (
    AllCondition,
    AnyCondition,
    ComparisonCondition,
    Condition,
    NotCondition,
    condition_to_dict,
    evaluate,
    parse_condition,
    unknown_metrics,
)
from app.services.triggers.contracts import ActionKind, EventKind, TriggerDefinition
from app.services.triggers.engine import (
    CONDITION_FALSE,
    COOLDOWN,
    DUPLICATE,
    ERROR,
    FIRED,
    TriggerRunOutcome,
    handle_event,
    row_to_definition,
)

__all__ = [
    "ACTION_REGISTRY",
    "CONDITION_FALSE",
    "COOLDOWN",
    "DUPLICATE",
    "ERROR",
    "FIRED",
    "ActionKind",
    "AllCondition",
    "AnyCondition",
    "ComparisonCondition",
    "Condition",
    "EventKind",
    "NotCondition",
    "TriggerDefinition",
    "TriggerRunOutcome",
    "condition_to_dict",
    "evaluate",
    "handle_event",
    "parse_condition",
    "row_to_definition",
    "unknown_metrics",
]
