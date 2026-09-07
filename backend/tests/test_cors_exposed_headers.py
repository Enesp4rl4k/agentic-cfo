"""Bir başlık CORS'ta açılmadıysa tarayıcı onu JavaScript'e vermez.

A cross-origin response hands JavaScript only the CORS-safelisted headers —
Cache-Control, Content-Language, Content-Length, Content-Type, Expires,
Last-Modified, Pragma. Everything else needs naming in `expose_headers`.

This was found by running the flow end to end: the e-Defter downloaded with the
client's guessed filename instead of GİB's convention, because the browser had
dropped `Content-Disposition`. The same was true of every other download in the
app — the server had been naming files carefully and no client could see it —
and of every `X-EDefter-*` header the card was written to display.

Nothing fails when this regresses. The header is simply not there, `undefined`
flows into the UI, and a fallback covers for it. So the check has to be static.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

# Set by the server for its own sake, never read by a browser: security headers
# the browser acts on itself, a proxy hint, and outbound request headers we send
# to somebody else's API.
_NOT_FOR_CLIENTS = {
    "X-Content-Type-Options",
    "X-Frame-Options",
    "X-XSS-Protection",
    "X-Accel-Buffering",
    "X-GitHub-Api-Version",
    "X-Shopify-Access-Token",
    "X-API-Key",
    "X-Audit-Reason",
    "X-Requested-With",
}


def _exposed_headers() -> set[str]:
    """The `expose_headers` list as written in main.py."""
    src = (APP / "main.py").read_text(encoding="utf-8")
    m = re.search(r"expose_headers=\[(.*?)\]", src, re.S)
    assert m, "expose_headers not found in main.py — did the CORS block move?"
    return {h.lower() for h in re.findall(r'"([^"]+)"', m.group(1))}


def _headers_the_api_sets() -> dict[str, str]:
    """Custom response headers set anywhere under app/, mapped to where."""
    found: dict[str, str] = {}
    for path in sorted(APP.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = str(path.relative_to(APP.parent)).replace("\\", "/")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key in node.keys:
                if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                    continue
                name = key.value
                if name in _NOT_FOR_CLIENTS:
                    continue
                if name.lower().startswith("x-") or name == "Content-Disposition":
                    found.setdefault(name, f"{rel}:{key.lineno}")
    return found


def test_every_header_meant_for_a_client_is_exposed() -> None:
    exposed = _exposed_headers()
    missing = [
        f"{name}  ({where})"
        for name, where in sorted(_headers_the_api_sets().items())
        if name.lower() not in exposed
    ]
    assert not missing, (
        "bu başlıklar ayarlanıyor ama CORS'ta açılmıyor — tarayıcı onları "
        "JavaScript'e vermez, yani ölüler. app/main.py içindeki expose_headers "
        "listesine ekleyin (ya da istemciye yönelik değillerse "
        "_NOT_FOR_CLIENTS'a):\n  " + "\n  ".join(missing)
    )


def test_content_disposition_is_exposed() -> None:
    """Named on its own because it is the one every download depends on."""
    assert "content-disposition" in _exposed_headers(), (
        "Content-Disposition açılmadan hiçbir indirme sunucunun verdiği dosya "
        "adını okuyamaz — GİB'in e-Defter adlandırması dahil"
    )


def test_the_exposed_list_has_no_dead_entries() -> None:
    """A header nobody sets is a leftover, and the list should stay readable."""
    set_by_api = {h.lower() for h in _headers_the_api_sets()}
    # Set by middleware rather than a dict literal, so the AST scan misses them.
    from_middleware = {"retry-after", "x-ratelimit-limit", "x-ratelimit-remaining",
                       "x-ratelimit-reset"}
    stale = sorted(_exposed_headers() - set_by_api - from_middleware)
    assert not stale, f"expose_headers'ta artık kimsenin ayarlamadığı başlıklar: {stale}"
