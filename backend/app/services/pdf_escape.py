"""Escaping for the HTML that WeasyPrint renders: the right escape for the context, not a blacklist.

A report is built from text a person typed (company, counterparty, descriptions, member names, notes,
titles). `escape_tree` HTML-escapes every string of a data tree (keys too) before any builder interpolates
it, so element content and quoted attribute values are safe; `css_string` makes text safe inside a CSS
`"..."` string (the page-margin footer), where HTML escaping does not apply.
"""
from __future__ import annotations

import html
from typing import Any

# What ends or breaks a CSS string or the <style> element around it: written as a hex escape, which CSS
# reads back as the literal character (a quote, a backslash, `<`, `>`, `&`).
_CSS_ESCAPE = frozenset("\"'\\<>&")


def escape_tree(value: Any) -> Any:
    """HTML-escape every str in dicts, lists and tuples (dict keys too); other values pass unchanged."""
    if isinstance(value, str):
        return html.escape(value, quote=True)
    if isinstance(value, dict):
        return {escape_tree(k): escape_tree(v) for k, v in value.items()}
    if isinstance(value, list):
        return [escape_tree(v) for v in value]
    if isinstance(value, tuple):
        return tuple(escape_tree(v) for v in value)
    return value


def rl_text(value: Any) -> str:
    """Text for reportlab's `Paragraph` mini-markup (`<b>`, `<br/>`, `&amp;`): `&`, `<` and `>` escaped.

    A `Paragraph` parses its text as markup, so a company named `<b>x` or `R&D` must be escaped before it is
    interpolated. Quotes need no escaping in element text. Slice long text BEFORE calling this: a cut after
    escaping can end inside an entity (`&am`).
    """
    return html.escape(str(value), quote=False)


def css_string(text: str) -> str:
    r"""The text as the inside of a CSS string literal.

    Quote, backslash, `<`, `>`, `&` become `\<hex> ` escapes (the trailing space ends the escape). Control
    characters and line separators (newline, carriage return, form feed, U+0085, U+2028/9), which CSS treats
    as string-ending newlines, become a plain space.
    """
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if ch in _CSS_ESCAPE:
            out.append(rf"\{code:x} ")
        elif code < 0x20 or code == 0x7F or code in (0x85, 0x2028, 0x2029):
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)
