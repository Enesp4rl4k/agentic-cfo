"""Locale helpers for agent system prompts."""
from __future__ import annotations


def locale_language_instruction(locale: str | None) -> str:
    """
    Short system-prompt addendum from org BCP-47 locale.
    Agents still mirror the user's question language when conflicting.
    """
    loc = (locale or "en-US").lower()
    if loc.startswith("tr"):
        return (
            "Organization locale is Turkish (tr). Prefer clear Turkish executive language "
            "unless the user writes in another language — then match the user."
        )
    if loc.startswith("de"):
        return (
            "Organization locale is German (de). Prefer clear German executive language "
            "unless the user writes in another language — then match the user."
        )
    if loc.startswith("en-gb"):
        return (
            "Organization locale is English (UK). Prefer clear British English "
            "unless the user writes in another language — then match the user."
        )
    return (
        "Organization locale is English (international). Prefer clear executive English "
        "unless the user writes in another language — then match the user."
    )


def with_locale_instruction(system_prompt: str, locale: str | None) -> str:
    hint = locale_language_instruction(locale)
    base = (system_prompt or "").rstrip()
    if not base:
        return hint
    if hint in base:
        return base
    return f"{base}\n\n{hint}"
