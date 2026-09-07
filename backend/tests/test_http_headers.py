"""HTTP başlıkları latin-1'dir; ürün Türkçedir.

Found by running the governance e2e, not by the suite: two new routes returned
500 on real data while 2744 tests passed. The header carried Turkish prose and
`ı` (U+0131) has no latin-1 encoding.

Pulling that thread found the same fault in code that had been shipping for a
while: three report endpoints build the download filename straight from the
company name. What makes it easy to miss is that latin-1 *does* contain ö, ü
and ç — so "Öztürk Holding" downloads fine and "Yıldız Tekstil" returns a 500,
from the same line.
"""
from __future__ import annotations

import ast
from pathlib import Path
from urllib.parse import unquote

import pytest

from app.core.http_headers import ascii_header_value, content_disposition

APP = Path(__file__).resolve().parents[1] / "app"

# Names a Turkish family business actually has. The first three broke.
COMPANY_NAMES = [
    "Yıldız Tekstil",           # ı — U+0131
    "Çağdaş Gıda",              # ğ — U+011F
    "Demir İnşaat A.Ş.",        # İ, ş
    "Öztürk Holding",           # ö, ü — these latin-1 *can* carry
    "ACME Ltd",
]


@pytest.mark.parametrize("company", COMPANY_NAMES)
def test_content_disposition_survives_latin1(company: str) -> None:
    """Starlette encodes header values as latin-1. Anything else is a 500."""
    header = content_disposition(f"{company.lower().replace(' ', '-')}-rapor.pdf")
    header.encode("latin-1")  # raises if we regressed


@pytest.mark.parametrize("company", COMPANY_NAMES)
def test_the_real_name_still_reaches_the_browser(company: str) -> None:
    """RFC 6266: the ASCII `filename` is a fallback, `filename*` is the truth.

    Folding to ASCII in the visible filename would be a silent downgrade —
    every browser in use reads `filename*`, so the file lands named correctly.
    """
    name = f"{company}-rapor.pdf"
    header = content_disposition(name)
    encoded = header.split("filename*=UTF-8''", 1)[1]
    assert unquote(encoded) == name


def test_ascii_fallback_is_readable_not_mangled() -> None:
    """A client that only reads `filename` should still get a name, not damage."""
    header = content_disposition("Yıldız Tekstil A.Ş.-rapor.pdf")
    ascii_part = header.split('filename="', 1)[1].split('"', 1)[0]
    assert ascii_part == "Yildiz Tekstil A.S.-rapor.pdf"


def test_lowercased_capital_i_loses_its_combining_dot() -> None:
    """`"İ".lower()` is `i` plus U+0307, which is not latin-1 either and is
    invisible in a filename."""
    assert ascii_header_value("İnşaat".lower()) == "insaat"


def test_ascii_header_value_never_raises() -> None:
    """A header is not the place to discover an encoding problem."""
    for value in ("", "düz metin", "日本語", "\x00\x1f control", "ıĞŞ"):
        ascii_header_value(value).encode("latin-1")


def test_quotes_cannot_escape_the_quoted_string() -> None:
    header = content_disposition('evil".pdf')
    ascii_part = header.split('filename="', 1)[1].split('"', 1)[0]
    assert '"' not in ascii_part


def test_empty_name_still_produces_a_usable_header() -> None:
    assert 'filename="download"' in content_disposition("")


# ── The guard ────────────────────────────────────────────────────────────────
# A static check, because the values that break are the interpolated ones and a
# literal-only scan finds nothing. Every Content-Disposition in the API layer
# must go through the helper.

def test_no_route_builds_content_disposition_by_hand() -> None:
    offenders: list[str] = []
    for path in sorted((APP / "api").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = str(path.relative_to(APP.parent)).replace("\\", "/")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if not (isinstance(key, ast.Constant) and key.value == "Content-Disposition"):
                    continue
                ok = (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id == "content_disposition"
                )
                if not ok:
                    offenders.append(f"{rel}:{value.lineno}")
    assert not offenders, (
        "Content-Disposition elle kuruluyor — app.core.http_headers."
        "content_disposition() kullanın; başlık latin-1'dir ve ı/ğ/ş/İ "
        "oraya sığmaz:\n  " + "\n  ".join(offenders)
    )


def test_no_route_puts_turkish_prose_in_a_custom_header() -> None:
    """The 500 that started this: `X-EDefter-Unfilable-Reason` carried a
    sentence. Custom headers carry codes; prose belongs in the body or the
    OpenAPI description."""
    offenders: list[str] = []
    for path in sorted((APP / "api").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = str(path.relative_to(APP.parent)).replace("\\", "/")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                    continue
                if not key.value.lower().startswith("x-"):
                    continue
                for sub in ast.walk(value):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        try:
                            sub.value.encode("latin-1")
                        except UnicodeEncodeError:
                            offenders.append(f"{rel}:{sub.lineno}: {key.value}")
    assert not offenders, (
        "özel başlıkta latin-1'e sığmayan metin:\n  " + "\n  ".join(offenders)
    )


# ── Through Starlette's own encoder, not a simulation of it ──────────────────

@pytest.mark.parametrize("company", COMPANY_NAMES)
def test_a_real_response_can_be_constructed(company: str) -> None:
    """`Response.raw_headers` is where the latin-1 encoding actually happens.

    Asserting `.encode("latin-1")` above tests our understanding of the rule;
    this tests the rule. Constructing the Response is what raised
    UnicodeEncodeError in production.
    """
    from starlette.responses import Response

    resp = Response(
        content=b"<x/>",
        media_type="application/xml",
        headers={
            "Content-Disposition": content_disposition(f"{company}-rapor.pdf"),
            "X-Company": ascii_header_value(company),
        },
    )
    raw = dict(resp.raw_headers)
    assert b"content-disposition" in raw
