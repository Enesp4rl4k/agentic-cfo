"""Her açıklama üreticisi ya korumalı ya da kendi yedeği var."""
from __future__ import annotations

import ast
import pathlib

import pytest

from app.agents.narrative_guard import ACIKLAMA_YOK, narrative_guard

AGENTS = pathlib.Path(__file__).resolve().parents[1] / "app" / "agents"


def test_every_narrative_function_survives_an_llm_failure() -> None:
    unguarded = []
    for p in AGENTS.rglob("*.py"):
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.AsyncFunctionDef) and n.name.startswith("_generate_") and n.name.endswith("_narrative"):
                guarded = any(getattr(d, "id", None) == "narrative_guard" for d in n.decorator_list)
                own_fallback = any(isinstance(x, ast.Try) for x in ast.walk(n))
                if not (guarded or own_fallback):
                    unguarded.append(f"{p.relative_to(AGENTS)}:{n.lineno} {n.name}")
    assert not unguarded, "LLM hatası hesaplanmış analizi silebilir:\n  " + "\n  ".join(unguarded)


@pytest.mark.asyncio
async def test_the_guard_keeps_the_analysis_and_says_the_narrative_is_missing() -> None:
    @narrative_guard
    async def boom() -> str:
        raise TimeoutError("llm")

    assert await boom() == ACIKLAMA_YOK
