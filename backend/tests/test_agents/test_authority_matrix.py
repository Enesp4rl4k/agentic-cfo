"""Yetki Matrisi — Delegation-of-Authority engine."""
from __future__ import annotations

from app.platform.authority_matrix import (
    DEFAULT_POLICY_RULES,
    AuthorityRequest,
    evaluate,
    validate_rules,
)


def _req(**kw):
    base = dict(domain="journal_entry", amount_kurus=1000)
    base.update(kw)
    return AuthorityRequest(**base)


class TestDefaultPolicy:
    def test_small_entry_auto_approves(self):
        d = evaluate(DEFAULT_POLICY_RULES, _req(amount_kurus=5_000))
        assert d.outcome == "auto_approve"
        assert d.needs_review is False

    def test_exactly_100k_still_auto(self):
        # old behaviour was `amount > LIMIT`, so exactly 100k does not trip
        d = evaluate(DEFAULT_POLICY_RULES, _req(amount_kurus=100_000 * 100))
        assert d.outcome == "auto_approve"

    def test_over_100k_needs_owner(self):
        d = evaluate(DEFAULT_POLICY_RULES, _req(amount_kurus=100_000 * 100 + 1))
        assert d.outcome == "needs_approval"
        assert d.required_approvals == [{"role": "owner", "count": 1}]
        assert d.matched_rule_id == "high_value"

    def test_low_confidence_needs_smmm(self):
        d = evaluate(DEFAULT_POLICY_RULES, _req(confidence=0.5))
        assert d.matched_rule_id == "low_confidence"
        assert d.required_approvals == [{"role": "smmm", "count": 1}]

    def test_unclassified_needs_review(self):
        d = evaluate(DEFAULT_POLICY_RULES, _req(classification_method="varsayılan"))
        assert d.matched_rule_id == "unclassified"

    def test_fixed_asset_needs_review(self):
        d = evaluate(DEFAULT_POLICY_RULES, _req(is_fixed_asset=True))
        assert d.matched_rule_id == "fixed_asset"

    def test_related_party_wins_and_requires_disclosure(self):
        d = evaluate(
            DEFAULT_POLICY_RULES,
            _req(amount_kurus=100_000 * 100 + 1, is_related_party=True),
        )
        assert d.matched_rule_id == "related_party"  # first rule, beats high_value
        assert d.required_evidence == ["disclosure"]
        assert d.required_approvals == [{"role": "owner", "count": 1}]


class TestCustomPolicy:
    POLICY = [
        {"id": "blocked_gambling", "domain": "*",
         "when": {"category_in": ["kumar"]}, "decision": "block", "note": "yasak"},
        {"id": "tier1", "domain": "spending",
         "when": {"amount_kurus_lt": 2_500_000},
         "decision": "auto_approve", "note": "₺25k altı serbest"},
        {"id": "tier2", "domain": "spending",
         "when": {"amount_kurus_gte": 2_500_000, "amount_kurus_lt": 10_000_000},
         "decision": "require_approvals",
         "approvals": [{"role": "finance_manager", "count": 1}], "note": "₺25k–₉100k"},
        {"id": "tier3", "domain": "spending",
         "when": {"amount_kurus_gte": 10_000_000},
         "decision": "require_approvals",
         "approvals": [{"role": "finance_manager", "count": 1}, {"role": "owner", "count": 1}],
         "note": "₺100k üzeri"},
        {"id": "catch_all", "domain": "*", "when": {}, "decision": "auto_approve", "note": "-"},
    ]

    def test_tiered_bands(self):
        assert evaluate(self.POLICY, _req(domain="spending", amount_kurus=1_000_000)).outcome == "auto_approve"
        mid = evaluate(self.POLICY, _req(domain="spending", amount_kurus=5_000_000))
        assert mid.matched_rule_id == "tier2"
        top = evaluate(self.POLICY, _req(domain="spending", amount_kurus=20_000_000))
        assert [a["role"] for a in top.required_approvals] == ["finance_manager", "owner"]

    def test_block_decision(self):
        d = evaluate(self.POLICY, _req(domain="spending", amount_kurus=100, category="kumar"))
        assert d.outcome == "blocked"

    def test_domain_scoping(self):
        # a journal_entry request should skip the spending-scoped tiers → catch_all
        d = evaluate(self.POLICY, _req(domain="journal_entry", amount_kurus=20_000_000))
        assert d.matched_rule_id == "catch_all"


class TestNoMatchEscalates:
    def test_policy_without_catch_all_escalates(self):
        policy = [{"id": "only", "domain": "spending", "when": {"amount_kurus_gte": 999_999_999},
                   "decision": "auto_approve"}]
        d = evaluate(policy, _req(domain="journal_entry", amount_kurus=1))
        assert d.outcome == "needs_approval"
        assert d.matched_rule_id is None
        assert d.required_approvals == [{"role": "owner", "count": 1}]


class TestValidation:
    def test_accepts_default(self):
        assert validate_rules(DEFAULT_POLICY_RULES) == []

    def test_rejects_non_list(self):
        assert validate_rules({}) != []

    def test_rejects_missing_id(self):
        errs = validate_rules([{"decision": "auto_approve", "when": {}, "domain": "*"}])
        assert any("id" in e for e in errs)

    def test_rejects_bad_decision(self):
        errs = validate_rules([{"id": "x", "decision": "maybe", "when": {}, "domain": "*"}])
        assert any("decision" in e for e in errs)

    def test_rejects_unknown_when_key(self):
        errs = validate_rules([
            {"id": "x", "decision": "auto_approve", "when": {"vibe_check": True}, "domain": "*"},
        ])
        assert any("vibe_check" in e for e in errs)

    def test_requires_catch_all(self):
        errs = validate_rules([
            {"id": "x", "decision": "auto_approve", "when": {"amount_kurus_gte": 1}, "domain": "*"},
        ])
        assert any("catch-all" in e for e in errs)

    def test_require_approvals_needs_list(self):
        errs = validate_rules([
            {"id": "x", "decision": "require_approvals", "when": {}, "domain": "*"},
        ])
        assert any("approvals" in e for e in errs)
