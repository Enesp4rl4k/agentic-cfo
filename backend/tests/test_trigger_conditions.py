"""P4-0 contract pins: the trigger condition DSL and the trigger envelope.

These pin behaviour BEFORE the P4-1 engine exists — the evaluator is pure, so
the contract is testable without a database, a router or a single cron job.
"""
import pytest
from pydantic import ValidationError

from app.services.triggers import (
    ComparisonCondition,
    TriggerDefinition,
    condition_to_dict,
    evaluate,
    parse_condition,
    unknown_metrics,
)

# ── Parsing / serialisation ─────────────────────────────────────────────────


class TestParsing:
    def test_comparison_roundtrip(self) -> None:
        payload = {"metric": "finance.runway_months", "op": "lt", "value": 3}
        condition = parse_condition(payload)
        assert isinstance(condition, ComparisonCondition)
        assert condition_to_dict(condition) == payload

    def test_nested_roundtrip_keeps_json_keys(self) -> None:
        payload = {
            "all": [
                {"metric": "finance.runway_months", "op": "lt", "value": 3},
                {
                    "any": [
                        {"metric": "risk.critical_kri_count", "op": "gt", "value": 0},
                        {"not": {"metric": "people.attrition_rate", "op": "gt", "value": 0.2}},
                    ]
                },
            ]
        }
        condition = parse_condition(payload)
        assert condition_to_dict(condition) == payload

    def test_int_threshold_is_a_number(self) -> None:
        condition = parse_condition({"metric": "finance.ebitda", "op": "lt", "value": 0})
        assert isinstance(condition, ComparisonCondition)
        assert condition.value == 0.0

    def test_rejects_unknown_operator(self) -> None:
        with pytest.raises(ValidationError):
            parse_condition({"metric": "finance.ebitda", "op": "approx", "value": 1})

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            parse_condition(
                {"metric": "finance.ebitda", "op": "gt", "value": 1, "window": "30d"}
            )

    def test_rejects_empty_metric(self) -> None:
        with pytest.raises(ValidationError):
            parse_condition({"metric": "", "op": "gt", "value": 1})

    def test_rejects_garbage_value(self) -> None:
        with pytest.raises(ValidationError):
            parse_condition({"metric": "finance.ebitda", "op": "gt", "value": "yok"})

    def test_rejects_empty_all(self) -> None:
        with pytest.raises(ValidationError):
            parse_condition({"all": []})

    def test_rejects_empty_any(self) -> None:
        with pytest.raises(ValidationError):
            parse_condition({"any": []})

    def test_rejects_bare_dict(self) -> None:
        with pytest.raises(ValidationError):
            parse_condition({"metric": "finance.ebitda"})


# ── Operator semantics ──────────────────────────────────────────────────────


class TestOperators:
    @pytest.mark.parametrize(
        ("op", "actual", "threshold", "expected"),
        [
            ("gt", 5.0, 5.0, False),      # gt is strict
            ("gt", 5.01, 5.0, True),
            ("gte", 5.0, 5.0, True),      # gte is inclusive
            ("lt", 4.99, 5.0, True),
            ("lt", 5.0, 5.0, False),
            ("lte", 5.0, 5.0, True),
            ("eq", 5.0, 5.0, True),
            ("eq", 5.0, 5.0001, False),
            ("ne", 5.0, 5.0, False),
            ("ne", 5.0, 6.0, True),
            ("abs_gt", 9.0, 8.0, True),   # magnitude on both signs
            ("abs_gt", -9.0, 8.0, True),
            ("abs_gt", -8.0, 8.0, False),
        ],
    )
    def test_operator_truth_table(
        self, op: str, actual: float, threshold: float, expected: bool
    ) -> None:
        condition = parse_condition({"metric": "m", "op": op, "value": threshold})
        assert evaluate(condition, {"m": actual}) is expected

    def test_kurus_thresholds_stay_raw(self) -> None:
        # finance.revenue is unit="cents" in the catalog; the evaluator is
        # unit-agnostic — a 1M-lira month is 100_000_000 kuruş.
        condition = parse_condition(
            {"metric": "finance.revenue", "op": "lt", "value": 100_000_000}
        )
        assert evaluate(condition, {"finance.revenue": 99_999_999}) is True
        assert evaluate(condition, {"finance.revenue": 100_000_000}) is False


# ── Absence never fires ─────────────────────────────────────────────────────


class TestMissingMetrics:
    @pytest.mark.parametrize("op", ["gt", "gte", "lt", "lte", "eq", "ne", "abs_gt"])
    def test_absent_metric_never_fires(self, op: str) -> None:
        condition = parse_condition({"metric": "not.in.snapshot", "op": op, "value": 0})
        assert evaluate(condition, {"other.metric": 5.0}) is False

    def test_any_fires_on_the_present_leg(self) -> None:
        condition = parse_condition(
            {
                "any": [
                    {"metric": "absent.one", "op": "gt", "value": 1},
                    {"metric": "present.one", "op": "gt", "value": 1},
                ]
            }
        )
        assert evaluate(condition, {"present.one": 2.0}) is True

    def test_all_is_false_when_any_leg_is_absent(self) -> None:
        condition = parse_condition(
            {
                "all": [
                    {"metric": "absent.one", "op": "gt", "value": 1},
                    {"metric": "present.one", "op": "gt", "value": 1},
                ]
            }
        )
        assert evaluate(condition, {"present.one": 2.0}) is False

    def test_not_of_missing_comparison_fires(self) -> None:
        # Documented sharp edge: `not` is pure boolean negation, and an absent
        # comparison is False — so its negation is True. Alerts should prefer
        # positive comparisons.
        condition = parse_condition({"not": {"metric": "absent.one", "op": "gt", "value": 1}})
        assert evaluate(condition, {}) is True


# ── Composition ─────────────────────────────────────────────────────────────


class TestComposition:
    def test_all_needs_every_leg(self) -> None:
        condition = parse_condition(
            {
                "all": [
                    {"metric": "a", "op": "gt", "value": 1},
                    {"metric": "b", "op": "gt", "value": 1},
                ]
            }
        )
        assert evaluate(condition, {"a": 2.0, "b": 2.0}) is True
        assert evaluate(condition, {"a": 2.0, "b": 0.0}) is False

    def test_any_needs_one_leg(self) -> None:
        condition = parse_condition(
            {
                "any": [
                    {"metric": "a", "op": "gt", "value": 1},
                    {"metric": "b", "op": "gt", "value": 1},
                ]
            }
        )
        assert evaluate(condition, {"a": 0.0, "b": 2.0}) is True
        assert evaluate(condition, {"a": 0.0, "b": 0.0}) is False

    def test_not_inverts_a_present_comparison(self) -> None:
        condition = parse_condition({"not": {"metric": "a", "op": "gt", "value": 1}})
        assert evaluate(condition, {"a": 2.0}) is False
        assert evaluate(condition, {"a": 0.0}) is True

    def test_deep_nesting(self) -> None:
        condition = parse_condition(
            {
                "all": [
                    {
                        "any": [
                            {"metric": "runway", "op": "lt", "value": 3},
                            {"all": [{"metric": "kri", "op": "gt", "value": 0}]},
                        ]
                    },
                    {"not": {"metric": "revenue", "op": "gt", "value": 1_000}},
                ]
            }
        )
        assert evaluate(condition, {"runway": 2.0, "kri": 1.0, "revenue": 500.0}) is True
        assert evaluate(condition, {"runway": 9.0, "kri": 0.0, "revenue": 500.0}) is False
        assert evaluate(condition, {"runway": 2.0, "kri": 1.0, "revenue": 2_000.0}) is False


# ── Catalog validation ──────────────────────────────────────────────────────


class TestCatalog:
    def test_known_metrics_pass(self) -> None:
        condition = parse_condition(
            {
                "all": [
                    {"metric": "finance.runway_months", "op": "lt", "value": 3},
                    {"not": {"metric": "risk.overall_score", "op": "gt", "value": 70}},
                ]
            }
        )
        assert unknown_metrics(condition) == []

    def test_unknown_metric_is_reported(self) -> None:
        condition = parse_condition({"metric": "nope.metric", "op": "gt", "value": 1})
        assert unknown_metrics(condition) == ["nope.metric"]

    def test_unknown_metrics_are_deduped_and_sorted(self) -> None:
        condition = parse_condition(
            {
                "all": [
                    {"metric": "z.z", "op": "gt", "value": 1},
                    {
                        "any": [
                            {"metric": "a.a", "op": "gt", "value": 1},
                            {"metric": "z.z", "op": "lt", "value": 9},
                        ]
                    },
                ]
            }
        )
        assert unknown_metrics(condition) == ["a.a", "z.z"]


# ── Trigger envelope ────────────────────────────────────────────────────────


class TestTriggerDefinition:
    def _minimal(self, **overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "name": "Runway daralması",
            "events": ["job.completed"],
            "condition": {"metric": "finance.runway_months", "op": "lt", "value": 3},
            "action_kind": "alert.dispatch",
        }
        base.update(overrides)
        return base

    def test_minimal_valid_with_defaults(self) -> None:
        trigger = TriggerDefinition.model_validate(self._minimal())
        assert trigger.enabled is True
        assert trigger.cooldown_minutes == 60
        assert trigger.action_params == {}

    def test_roundtrip(self) -> None:
        payload = self._minimal(
            events=["job.completed", "schedule"],
            action_kind="analysis.start",
            action_params={"agent": "risk"},
            cooldown_minutes=15,
            enabled=False,
        )
        trigger = TriggerDefinition.model_validate(payload)
        assert TriggerDefinition.model_validate(trigger.model_dump()) == trigger

    def test_rejects_empty_name(self) -> None:
        with pytest.raises(ValidationError):
            TriggerDefinition.model_validate(self._minimal(name=""))

    def test_rejects_no_events(self) -> None:
        with pytest.raises(ValidationError):
            TriggerDefinition.model_validate(self._minimal(events=[]))

    def test_rejects_unknown_event(self) -> None:
        with pytest.raises(ValidationError):
            TriggerDefinition.model_validate(self._minimal(events=["coffee.ready"]))

    def test_rejects_unknown_action(self) -> None:
        with pytest.raises(ValidationError):
            TriggerDefinition.model_validate(self._minimal(action_kind="nuke"))

    def test_rejects_broken_condition(self) -> None:
        with pytest.raises(ValidationError):
            TriggerDefinition.model_validate(
                self._minimal(condition={"metric": "finance.runway_months", "op": "~", "value": 3})
            )

    def test_rejects_out_of_range_cooldown(self) -> None:
        with pytest.raises(ValidationError):
            TriggerDefinition.model_validate(self._minimal(cooldown_minutes=-1))
        with pytest.raises(ValidationError):
            TriggerDefinition.model_validate(self._minimal(cooldown_minutes=43_201))

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            TriggerDefinition.model_validate(self._minimal(org_id="x"))
