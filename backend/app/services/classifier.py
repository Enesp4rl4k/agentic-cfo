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
from typing import TYPE_CHECKING

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
    "tax":            ["vergi", "kdv", "stopaj", "tax", "vat", "withholding"],
    "loan":           ["kredi", "borç", "faiz", "loan", "interest", "installment"],
}


def classify_by_keywords(description: str) -> str:
    """Rule-based classification using built-in keyword heuristics."""
    desc_lower = description.lower()
    for category, keywords in KEYWORD_RULES.items():
        if any(kw in desc_lower for kw in keywords):
            return category
    return "other_expense"


async def classify(
    description: str,
    vendor: str | None,
    db: "AsyncSession",
) -> str:
    """
    Classify a transaction description into a category.
    Checks user-defined rules first, falls back to keyword heuristics.
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F401
    from app.models.category_rule import CategoryRule

    # 1. Vendor match — most specific
    if vendor:
        result = await db.execute(
            select(CategoryRule)
            .where(CategoryRule.vendor_match.ilike(f"%{vendor.strip()}%"))
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
        .where(CategoryRule.keyword_match.isnot(None))
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


async def learn(
    description: str,
    vendor: str | None,
    new_category: str,
    apply_always: bool,
    db: "AsyncSession",
) -> "CategoryRule":
    """
    Persist a user correction as a CategoryRule.
    Called when user changes a transaction's category in the UI.
    """
    from sqlalchemy import select
    from app.models.category_rule import CategoryRule

    # Upsert: if an identical rule already exists, update the category
    if vendor and apply_always:
        existing = await db.execute(
            select(CategoryRule).where(
                CategoryRule.vendor_match.ilike(vendor.strip())
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
