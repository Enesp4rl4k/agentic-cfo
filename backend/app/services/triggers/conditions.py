"""Trigger condition DSL — pure evaluation, JSON in/out, no I/O.

A trigger's `condition` is a small JSON tree over semantic metric IDs:

    {"metric": "finance.runway_months", "op": "lt", "value": 3}
    {"any":  [ ...conditions... ]}
    {"all":  [ ...conditions... ]}
    {"not":  {...}}

Semantics pinned by backend/tests/test_trigger_conditions.py:

* Values are the raw numbers the semantic projector produces per metric_id
  (kuruş for unit="cents", plain numbers otherwise). The evaluator is
  unit-agnostic — thresholds are written in the metric's own unit.
* A metric missing from the snapshot never fires its comparison, for EVERY
  operator (a missing `ne` does not fire either): partial snapshots must not
  raise, and absence is not evidence.
* `not` is pure boolean negation of the child result — so `not` of a
  missing-metric comparison fires. Prefer `any`-lists of positive comparisons
  for alerts; `not` is a sharp tool.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.services.semantic.catalog import METRIC_CATALOG

Operator = Literal["gt", "gte", "lt", "lte", "eq", "ne", "abs_gt"]


class ComparisonCondition(BaseModel):
    """Leaf: compare one metric's actual value against a threshold."""

    model_config = ConfigDict(extra="forbid")

    metric: str = Field(min_length=1)
    op: Operator
    value: float


class AllCondition(BaseModel):
    """Conjunction: every child must hold."""

    model_config = ConfigDict(extra="forbid")

    all: list[Condition] = Field(min_length=1)


class AnyCondition(BaseModel):
    """Disjunction: at least one child must hold."""

    model_config = ConfigDict(extra="forbid")

    any: list[Condition] = Field(min_length=1)


class NotCondition(BaseModel):
    """Negation of exactly one child."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    not_: Condition = Field(alias="not")


Condition = ComparisonCondition | AllCondition | AnyCondition | NotCondition

# Resolve the forward references now, at import time, not on first validation.
AllCondition.model_rebuild()
AnyCondition.model_rebuild()
NotCondition.model_rebuild()

_condition_adapter: TypeAdapter[Condition] = TypeAdapter(Condition)


def parse_condition(payload: object) -> Condition:
    """Validate a raw JSON-shaped payload into a condition tree."""
    return _condition_adapter.validate_python(payload)


def condition_to_dict(condition: Condition) -> dict[str, Any]:
    """JSON-serialisable form (keys `all`/`any`/`not`) for storage and APIs."""
    dumped: dict[str, Any] = _condition_adapter.dump_python(
        condition, mode="json", by_alias=True
    )
    return dumped


def evaluate(condition: Condition, values: Mapping[str, float]) -> bool:
    """Evaluate the tree against a {metric_id: raw_value} snapshot."""
    if isinstance(condition, ComparisonCondition):
        actual = values.get(condition.metric)
        if actual is None:
            return False
        return _compare(condition.op, actual, condition.value)
    if isinstance(condition, AllCondition):
        return all(evaluate(child, values) for child in condition.all)
    if isinstance(condition, AnyCondition):
        return any(evaluate(child, values) for child in condition.any)
    if isinstance(condition, NotCondition):
        return not evaluate(condition.not_, values)
    raise TypeError(f"unsupported condition type: {type(condition).__name__}")


def unknown_metrics(condition: Condition) -> list[str]:
    """Sorted metric IDs the tree references but the frozen catalog lacks."""
    if isinstance(condition, ComparisonCondition):
        return [] if condition.metric in METRIC_CATALOG else [condition.metric]
    if isinstance(condition, AllCondition):
        children = condition.all
    elif isinstance(condition, AnyCondition):
        children = condition.any
    elif isinstance(condition, NotCondition):
        children = [condition.not_]
    else:
        raise TypeError(f"unsupported condition type: {type(condition).__name__}")
    found: set[str] = set()
    for child in children:
        found.update(unknown_metrics(child))
    return sorted(found)


def _compare(op: Operator, actual: float, threshold: float) -> bool:
    match op:
        case "gt":
            return actual > threshold
        case "gte":
            return actual >= threshold
        case "lt":
            return actual < threshold
        case "lte":
            return actual <= threshold
        case "eq":
            return actual == threshold
        case "ne":
            return actual != threshold
        case "abs_gt":
            return abs(actual) > threshold
    raise TypeError(f"unknown operator: {op!r}")
