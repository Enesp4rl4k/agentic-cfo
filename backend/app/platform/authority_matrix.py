"""Yetki Matrisi — the Delegation-of-Authority engine.

Institutionalising a family business means moving from "ask the boss for
everything" to "the policy decides; exceptions escalate". This is that policy,
as ordered rules (first match wins, like an ACL):

    when <conditions>  ->  auto_approve | require_approvals([{role, count}]) | block

`evaluate()` is pure — the accounting engine calls it per journal entry with no
DB. `load_active_rules()` fetches an org's editable policy (or the sane default
that reproduces the previously hard-coded thresholds).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Request / decision ──────────────────────────────────────────────────────

@dataclass
class AuthorityRequest:
    domain: str                       # journal_entry | spending | hiring | agent_recommendation
    amount_kurus: int = 0
    category: str | None = None
    counterparty: str | None = None
    is_related_party: bool = False
    is_fixed_asset: bool = False
    confidence: float | None = None
    classification_method: str | None = None  # kural | llm | varsayılan
    requested_by_role: str | None = None


@dataclass
class AuthorityDecision:
    outcome: str                      # auto_approve | needs_approval | blocked
    matched_rule_id: str | None
    required_approvals: list[dict[str, Any]] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    rationale: str = ""

    @property
    def needs_review(self) -> bool:
        return self.outcome != "auto_approve"

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "matched_rule_id": self.matched_rule_id,
            "required_approvals": self.required_approvals,
            "required_evidence": self.required_evidence,
            "rationale": self.rationale,
        }


# ── Default policy — reproduces the old hard-coded behaviour ─────────────────
# (double_entry.ONAY_LIMIT_TRY, confidence < 0.6, method "varsayılan", fixed asset)

DEFAULT_POLICY_RULES: list[dict[str, Any]] = [
    {
        "id": "related_party",
        "domain": "*",
        "when": {"is_related_party": True},
        "decision": "require_approvals",
        "approvals": [{"role": "owner", "count": 1}],
        "require_evidence": ["disclosure"],
        "note": "İlişkili taraf işlemi — sahibin onayı ve beyan zorunlu",
    },
    {
        "id": "low_confidence",
        "domain": "*",
        "when": {"confidence_lt": 0.6},
        "decision": "require_approvals",
        "approvals": [{"role": "smmm", "count": 1}],
        "note": "Düşük güven skoru",
    },
    {
        "id": "unclassified",
        "domain": "journal_entry",
        "when": {"classification_method_in": ["varsayılan"]},
        "decision": "require_approvals",
        "approvals": [{"role": "smmm", "count": 1}],
        "note": "Otomatik sınıflandırılamadı",
    },
    {
        "id": "fixed_asset",
        "domain": "journal_entry",
        "when": {"is_fixed_asset": True},
        "decision": "require_approvals",
        "approvals": [{"role": "smmm", "count": 1}],
        "note": "Duran varlık alımı",
    },
    {
        "id": "high_value",
        "domain": "*",
        "when": {"amount_kurus_gt": 100_000 * 100},
        "decision": "require_approvals",
        "approvals": [{"role": "owner", "count": 1}],
        "note": "Yüksek tutarlı işlem (₺100.000 üzeri)",
    },
    {
        "id": "default_auto",
        "domain": "*",
        "when": {},
        "decision": "auto_approve",
        "note": "Politika eşiklerinin altında — otomatik",
    },
]


# ── Matching ────────────────────────────────────────────────────────────────

def _matches(when: dict[str, Any], req: AuthorityRequest) -> bool:
    if "amount_kurus_gte" in when and req.amount_kurus < when["amount_kurus_gte"]:
        return False
    if "amount_kurus_gt" in when and req.amount_kurus <= when["amount_kurus_gt"]:
        return False
    if "amount_kurus_lt" in when and req.amount_kurus >= when["amount_kurus_lt"]:
        return False
    if "confidence_lt" in when:
        if req.confidence is None or req.confidence >= when["confidence_lt"]:
            return False
    if "category_in" in when and req.category not in (when.get("category_in") or []):
        return False
    if "classification_method_in" in when:
        if req.classification_method not in (when.get("classification_method_in") or []):
            return False
    if "is_related_party" in when and bool(req.is_related_party) != bool(when["is_related_party"]):
        return False
    if "is_fixed_asset" in when and bool(req.is_fixed_asset) != bool(when["is_fixed_asset"]):
        return False
    if "requested_by_role_in" in when:
        if req.requested_by_role not in (when.get("requested_by_role_in") or []):
            return False
    return True


def evaluate(rules: list[dict[str, Any]], req: AuthorityRequest) -> AuthorityDecision:
    """First matching rule wins. A rule matches when its `domain` is `*` or equal
    to the request domain AND its `when` clause matches."""
    for rule in rules or DEFAULT_POLICY_RULES:
        rdomain = rule.get("domain", "*")
        if rdomain not in ("*", req.domain):
            continue
        if not _matches(rule.get("when") or {}, req):
            continue
        decision = rule.get("decision", "auto_approve")
        if decision == "auto_approve":
            return AuthorityDecision(
                outcome="auto_approve", matched_rule_id=rule.get("id"),
                rationale=rule.get("note", ""),
            )
        if decision == "block":
            return AuthorityDecision(
                outcome="blocked", matched_rule_id=rule.get("id"),
                rationale=rule.get("note", "Politika tarafından engellendi"),
            )
        return AuthorityDecision(
            outcome="needs_approval",
            matched_rule_id=rule.get("id"),
            required_approvals=list(rule.get("approvals") or []),
            required_evidence=list(rule.get("require_evidence") or []),
            rationale=rule.get("note", ""),
        )
    # No rule matched (policy has no catch-all) — safest is to escalate.
    return AuthorityDecision(
        outcome="needs_approval", matched_rule_id=None,
        required_approvals=[{"role": "owner", "count": 1}],
        rationale="Eşleşen kural yok — güvenli tarafta kalmak için yükseltildi",
    )


# ── Validation ──────────────────────────────────────────────────────────────

_VALID_DECISIONS = {"auto_approve", "require_approvals", "block"}
_VALID_WHEN_KEYS = {
    "amount_kurus_gte", "amount_kurus_gt", "amount_kurus_lt", "confidence_lt",
    "category_in", "classification_method_in", "is_related_party", "is_fixed_asset",
    "requested_by_role_in",
}


def validate_rules(rules: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(rules, list) or not rules:
        return ["Politika en az bir kural içeren bir liste olmalı."]
    seen: set[str] = set()
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"Kural #{i}: nesne olmalı.")
            continue
        rid = rule.get("id")
        if not rid or not isinstance(rid, str):
            errors.append(f"Kural #{i}: 'id' zorunlu.")
        elif rid in seen:
            errors.append(f"Kural '{rid}': id tekrar ediyor.")
        else:
            seen.add(rid)
        if rule.get("decision") not in _VALID_DECISIONS:
            errors.append(f"Kural '{rid}': geçersiz 'decision' ({rule.get('decision')}).")
        if rule.get("decision") == "require_approvals":
            appr = rule.get("approvals")
            if not isinstance(appr, list) or not appr:
                errors.append(f"Kural '{rid}': 'approvals' listesi zorunlu.")
        bad = set((rule.get("when") or {}).keys()) - _VALID_WHEN_KEYS
        if bad:
            errors.append(f"Kural '{rid}': bilinmeyen koşul anahtar(lar)ı: {sorted(bad)}")
    if not any((r.get("when") in (None, {}) and r.get("domain", "*") == "*") for r in rules if isinstance(r, dict)):
        errors.append("Politikada bir catch-all kural yok (when'i boş, domain '*').")
    return errors


async def load_active_rules(org_id: str | None, db: Any) -> list[dict[str, Any]]:
    """Return the org's active policy rules, or the default set."""
    if not org_id:
        return DEFAULT_POLICY_RULES
    try:
        from sqlalchemy import select

        from app.models.authority_policy import AuthorityPolicy

        row = (
            await db.execute(
                select(AuthorityPolicy)
                .where(AuthorityPolicy.org_id == org_id, AuthorityPolicy.active.is_(True))
                .order_by(AuthorityPolicy.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row and row.rules:
            return list(row.rules)
    except Exception:
        pass
    return DEFAULT_POLICY_RULES
