"""Every decision kind has a label in the decision log, in both languages."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.models.decision import DecisionKind

_MESSAGES = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "i18n" / "messages"


@pytest.mark.parametrize("lang", ["tr", "en"])
def test_every_kind_is_labelled(lang: str) -> None:
    text = (_MESSAGES / f"{lang}.ts").read_text(encoding="utf-8")
    block = re.search(r"decisionLog: \{.*?\n    kinds: \{(.*?)\n    \},", text, re.S)
    assert block, f"{lang}.ts has no decisionLog.kinds"
    labelled = set(re.findall(r"^\s+(\w+): ", block.group(1), re.M))
    missing = sorted({k.value for k in DecisionKind} - labelled)
    assert not missing, f"{lang}: decision kinds without a label in the decision log: {missing}"
