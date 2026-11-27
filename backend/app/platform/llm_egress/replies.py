"""Model replies that are JSON: parse the MASKED text first, then restore the parsed string values.

Restoring inside serialised JSON would break it (a name with a quote or a backslash) and would miss a
placeholder the provider escaped; parsing first avoids both. The placeholders are ASCII, so the
provider's unicode escaping cannot change them.
"""
from __future__ import annotations

import json
import re
from typing import Any

NOT_JSON = object()  # the reply could not be parsed as JSON (the caller decides; nothing is guessed)
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def parse_json_text(text: str) -> Any:
    """The JSON value in a model reply (code fences and surrounding prose tolerated), or NOT_JSON."""
    body = _FENCE.sub("", (text or "").strip())
    try:
        return json.loads(body)
    except ValueError:
        pass
    for opener, closer in (("[", "]"), ("{", "}")):
        start, end = body.find(opener), body.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(body[start:end + 1])
            except ValueError:
                continue
    return NOT_JSON


def restore_json_reply(session: Any, text: str, *, strict: bool) -> tuple[str, Any]:
    """(text to show, parsed value): parsed from the masked reply, then restored value by value."""
    parsed = parse_json_text(text)
    if parsed is NOT_JSON:
        return session.restore(text), NOT_JSON
    restored = session.restore_json(parsed, strict=strict)
    return json.dumps(restored, ensure_ascii=False), restored
