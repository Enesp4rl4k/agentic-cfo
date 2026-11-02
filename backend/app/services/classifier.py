"""
Classifier service — rule-based categorization with user feedback loop.

Priority order:
1. User-defined CategoryRules (vendor match first, then keyword match)
2. Built-in keyword heuristics (from data_ingestion)
3. "other_expense" fallback

When user corrects a category, call learn() to persist the rule.
Next time the same vendor/keyword appears, the correct category is applied.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.core import tdhp
from app.core.turkish import fold

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.category_rule import CategoryRule

logger = logging.getLogger(__name__)

# ── Built-in keyword heuristics (same as data_ingestion, centralised here) ──

KEYWORD_RULES: dict[str, list[str]] = {
    "revenue":        ["satış", "gelir", "tahsilat", "sales", "income", "revenue", "payment received"],
    "cogs":           ["hammadde", "malzeme", "raw material", "goods", "manufacturing", "inventory"],
    "salary":         ["maaş", "ücret", "bordro", "sgk", "salary", "payroll", "wages", "staff"],
    "rent":           ["kira", "kiralık", "rent", "lease"],
    "utilities":      ["elektrik", "su", "doğalgaz", "electricity", "water", "gas", "internet", "phone"],
    "marketing":      ["reklam", "pazarlama", "advertising", "marketing", "google ads", "meta ads"],
    "technology":     ["yazılım", "sunucu", "software", "cloud", "aws", "azure", "saas", "license"],
    # KDV is paid over to the state: cash, not a P&L expense (plan v8 §A1).
    "tax_payment":    ["kdv", "katma değer", "vat"],
    "tax":            ["vergi", "stopaj", "tax", "withholding"],
    "loan":           ["kredi", "borç", "faiz", "loan", "interest", "installment"],
}


def classify_by_keywords(description: str) -> str:
    """Rule-based classification using built-in keyword heuristics.

    Matched with Turkish diacritics folded on both sides. ERP exports and bank
    statements write "maas odemesi" and "dogalgaz faturasi" far more often than
    "maaş ödemesi" and "doğalgaz faturası", and a payroll line that misses
    `salary` lands in other_expense — where every report that groups by
    category is then quietly wrong about where the money went.
    """
    folded = fold(description)
    for category, keywords in KEYWORD_RULES.items():
        if any(fold(kw) in folded for kw in keywords):
            return category
    return "other_expense"


_INCOME = frozenset({"revenue", "other_income"})


def classify_posting(description: str, tx_type: str, account_code: str | None = None) -> str:
    """Category of a row from an accounting export: the account decides when the
    source names one (app.core.tdhp); otherwise keywords, but never a category
    of the other direction — "Satış Ekibi Maaşı" matched `revenue` first."""
    hesap = tdhp.hesap(account_code)
    if hesap is not None and hesap.rol != "gider":
        return hesap.kategori
    folded = fold(description)
    for category, keywords in KEYWORD_RULES.items():
        if hesap is not None or tx_type != "income":
            if category in _INCOME:
                continue
        elif category not in _INCOME and category not in tdhp.BILANCO_KATEGORILERI:
            continue
        if any(fold(kw) in folded for kw in keywords):
            return category
    if hesap is not None:
        return hesap.kategori
    return "revenue" if tx_type == "income" else "other_expense"


async def classify(
    description: str,
    vendor: str | None,
    db: AsyncSession,
    org_id: str | None = None,
) -> str:
    """
    Classify a transaction description into a category.
    Checks user-defined rules first, falls back to keyword heuristics.
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F401

    from app.models.category_rule import CategoryRule

    # Rules are an organisation's own corrections; without one, only the
    # built-in heuristics apply.
    if org_id is None:
        return classify_by_keywords(description)

    # 1. Vendor match — most specific
    if vendor:
        result = await db.execute(
            select(CategoryRule)
            .where(CategoryRule.org_id == org_id,
                   CategoryRule.vendor_match.ilike(f"%{vendor.strip()}%"))
            .order_by(CategoryRule.hit_count.desc())
            .limit(1)
        )
        rule = result.scalars().first()
        if rule:
            rule.hit_count += 1
            await db.commit()
            logger.debug("Vendor rule match: '%s' → %s", vendor, rule.category)
            return rule.category

    # 2. Keyword match against description
    result = await db.execute(
        select(CategoryRule)
        .where(CategoryRule.org_id == org_id, CategoryRule.keyword_match.isnot(None))
        .order_by(CategoryRule.hit_count.desc())
    )
    keyword_rules = result.scalars().all()
    desc_lower = description.lower()
    for rule in keyword_rules:
        if rule.keyword_match and rule.keyword_match.lower() in desc_lower:
            rule.hit_count += 1
            await db.commit()
            logger.debug("Keyword rule match: '%s' → %s", rule.keyword_match, rule.category)
            return rule.category

    # 3. Built-in heuristics
    return classify_by_keywords(description)


# ── Batch application (plan v5 §F0) ──────────────────────────────────────────
# `classify()` above answers one transaction at a time with a query and a commit
# per hit, and no ingest path ever called it: corrections were learned and never
# applied. Ingest applies them in bulk instead — rules are loaded once per run
# by whoever holds the session, matched in memory, and hits are counted at the
# end in the caller's transaction.

USER_RULE = "user_rule"


@dataclass(frozen=True)
class RuleSpec:
    """A CategoryRule as plain data, safe to carry through the agent state."""

    id: str
    category: str
    vendor: str | None = None
    keyword: str | None = None


def rules_to_state(rules: list[RuleSpec]) -> list[dict[str, Any]]:
    return [r.__dict__.copy() for r in rules]


def rules_from_state(raw: list[dict[str, Any]] | None) -> list[RuleSpec]:
    return [RuleSpec(**r) for r in (raw or [])]


async def load_rules(org_id: str | None, db: AsyncSession) -> list[RuleSpec]:
    """The organisation's standing rules, most-used first.

    Only `apply_always` rules: a correction made without "apply always" changed
    that one transaction, and the user did not ask for more.
    """
    if not org_id:
        return []
    from sqlalchemy import select

    from app.models.category_rule import CategoryRule

    rows = (
        await db.execute(
            select(CategoryRule)
            .where(CategoryRule.org_id == org_id, CategoryRule.apply_always.is_(True))
            .order_by(CategoryRule.hit_count.desc())
        )
    ).scalars().all()
    return [
        RuleSpec(
            id=str(r.id),
            category=r.category,
            vendor=r.vendor_match or None,
            keyword=r.keyword_match or None,
        )
        for r in rows
        if r.vendor_match or r.keyword_match
    ]


def match_rule(
    rules: list[RuleSpec], *, vendor: str | None, description: str | None
) -> RuleSpec | None:
    """First rule that matches: vendor rules, then keyword rules (each in the
    given order). Diacritics are folded on both sides, as for the heuristics.

    A vendor rule also matches a description that names the vendor: bank
    statements carry the counterparty inside the description, not in a field.
    """
    vendor_f = fold(vendor or "")
    desc_f = fold(description or "")
    return next(
        (r for r in rules if _vendor_hit(r, vendor_f, desc_f)),
        next((r for r in rules if _keyword_hit(r, desc_f)), None),
    )


def _vendor_hit(rule: RuleSpec, vendor_f: str, desc_f: str) -> bool:
    needle = fold(rule.vendor or "")
    return bool(needle) and (needle in vendor_f or needle in desc_f)


def _keyword_hit(rule: RuleSpec, desc_f: str) -> bool:
    if rule.vendor:
        return False
    needle = fold(rule.keyword or "")
    return bool(needle) and needle in desc_f


def apply_rules(
    transactions: list[dict[str, Any]],
    rules: list[RuleSpec],
    *,
    vendor_key: str = "vendor",
    description_key: str = "description",
) -> Counter[str]:
    """Overwrite `category` where a user rule matches; mark `category_source`.

    Mutates the dicts in place and returns hits per rule id.
    """
    hits: Counter[str] = Counter()
    if not rules:
        return hits
    for tx in transactions:
        rule = match_rule(
            rules, vendor=tx.get(vendor_key), description=tx.get(description_key)
        )
        if rule is None:
            continue
        tx["category"] = rule.category
        tx["category_source"] = USER_RULE
        hits[rule.id] += 1
    return hits


async def record_hits(hits: Counter[str] | dict[str, int], db: AsyncSession) -> None:
    """Add this run's hits to the rules. Does not commit — the caller's
    transaction owns it, so counts land together with the rows they counted."""
    if not hits:
        return
    from app.models.category_rule import CategoryRule

    for rule_id, n in hits.items():
        rule = await db.get(CategoryRule, rule_id)
        if rule is not None:
            rule.hit_count = (rule.hit_count or 0) + int(n)


async def learn(
    description: str,
    vendor: str | None,
    new_category: str,
    apply_always: bool,
    db: AsyncSession,
    org_id: str | None = None,
) -> CategoryRule:
    """
    Persist a user correction as a CategoryRule.
    Called when user changes a transaction's category in the UI.
    """
    from sqlalchemy import select

    from app.models.category_rule import CategoryRule

    # Upsert: if an identical rule already exists, update the category
    if vendor and apply_always:
        existing = await db.execute(
            # Only this organisation's rule: matching on the vendor name alone
            # let one company's correction rewrite another company's rule.
            select(CategoryRule).where(
                CategoryRule.org_id == org_id,
                CategoryRule.vendor_match.ilike(vendor.strip()),
            ).limit(1)
        )
        rule = existing.scalars().first()
        if rule:
            rule.category = new_category
            rule.apply_always = apply_always
            await db.commit()
            return rule

    # Create new rule
    rule = CategoryRule(
        org_id=org_id,
        vendor_match=vendor.strip() if vendor else None,
        keyword_match=_extract_keyword(description) if not vendor else None,
        category=new_category,
        apply_always=apply_always,
        hit_count=1,
    )
    db.add(rule)
    await db.commit()
    logger.info("Learned new rule: vendor=%s keyword=%s → %s", rule.vendor_match, rule.keyword_match, new_category)
    return rule


def _extract_keyword(description: str) -> str | None:
    """
    Extract a useful keyword from a description for rule matching.
    Returns the longest word that's not a stopword (date, amount, etc).
    """
    import re
    stopwords = {"the", "and", "for", "from", "to", "of", "a", "an", "in", "on", "at", "ödeme", "işlem", "transfer"}
    words = re.findall(r"[a-zA-ZğüşıöçĞÜŞİÖÇ]{4,}", description)
    candidates = [w.lower() for w in words if w.lower() not in stopwords]
    # Pick the longest candidate — most specific
    return max(candidates, key=len) if candidates else None
