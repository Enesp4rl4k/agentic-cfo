"""Does a page that yielded no text mean DATA IS MISSING? Decided from the pages around it, never from the page alone.

A logo-only cover, a stamp or signature page, a blank scanned back side give OCR nothing and lose no row. A person's
attention is spent only where there is evidence that rows may be missing, so an upload is HELD for a text-less page only when:

1. the page sits between pages that DO carry transaction rows (a date and an amount on a line), and the running
   balance does not chain across it: the first row after the page must differ from the last row before it by exactly
   its own amount (oldest first) or the earlier row's amount (newest first). Where a balance cannot be read on
   both sides, the chain is unproven and that is evidence too; or
2. the page before it says the statement continues ("sonraki sayfada devam", "continued on next page") and no page
   with rows follows.

Every other text-less page gets a NOTE on the result and no hold. The whole-statement checks (stated period,
coverage, balance continuity over the parsed rows: `stated_period.py`, `coverage.py`, `parsers/balance_chain.py`) are
unchanged and still hold a statement whose rows do not add up, whatever the pages looked like.

Pure functions over page texts; the decision is recorded in the OCR result's metadata (`pages_unread`, `pages_gap`).
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

_DATE = re.compile(r"(?<!\d)\d{1,2}[./]\d{1,2}[./]\d{2,4}(?!\d)")
_MONEY = re.compile(r"(?<![\d.,])-?\d{1,3}(?:\.\d{3})*,\d{2}(?!\d)|(?<![\d.,])-?\d+,\d{2}(?!\d)")
_CONTINUES = re.compile(r"sonraki\s+sayfada\s+devam|devam[ıi]\s+(?:var|sonraki)|continued\s+on\s+(?:the\s+)?next\s+page", re.I)


def _cents(token: str) -> int:
    return int(token.replace(".", "").replace(",", ""))


def row_lines(text: str) -> list[list[int]]:
    """For each line with a date and at least one amount: its amounts in cents, in reading order."""
    rows = []
    for line in text.splitlines():
        if _DATE.search(line):
            amounts = [_cents(m) for m in _MONEY.findall(line)]
            if amounts:
                rows.append(amounts)
    return rows


def chains(before: list[int], after: list[int]) -> bool | None:
    """Do the balances of two rows that follow each other in the statement connect? (amount, balance) are the last two
    figures of a row. None when either row has no balance to compare."""
    if len(before) < 2 or len(after) < 2:
        return None
    step = abs(after[-1] - before[-1])
    return step == abs(after[-2]) or step == abs(before[-2])


def holding_pages(pages: Sequence[tuple[int, str]], unread: Iterable[int]) -> dict[int, tuple[str, str]]:
    """{page number: (Turkish reason, English reason)} for the text-less pages that hold the upload.
    `pages` is every page as (1-based number, text); `unread` the numbers of the text-less pages with content."""
    rows = {no: row_lines(text) for no, text in pages if text.strip()}
    rows = {no: r for no, r in rows.items() if r}
    texts = dict(pages)
    held: dict[int, tuple[str, str]] = {}
    for no in sorted(set(unread)):
        before = max((p for p in rows if p < no), default=None)
        after = min((p for p in rows if p > no), default=None)
        if before is not None and after is not None:
            linked = chains(rows[before][-1], rows[after][0])
            if linked is True:
                continue
            if linked is False:
                held[no] = (f"{before}. ve {after}. sayfadaki bakiyeler birbirine bağlanmıyor",
                            f"the balances on pages {before} and {after} do not connect")
            else:
                held[no] = (f"{before}. ve {after}. sayfada işlem satırı var, aradaki sayfa okunamadı ve bakiye bağlantısı doğrulanamadı",
                            f"pages {before} and {after} hold transactions, this page between them was not read and the balance link could not be checked")
        elif before is not None and after is None and _CONTINUES.search(texts.get(before, "")):
            held[no] = (f"{before}. sayfa ekstrenin devam ettiğini söylüyor",
                        f"page {before} says the statement continues")
    return held


def _shown(pages: list[int]) -> str:
    return ", ".join(str(p) for p in pages[:20]) + (f" (+{len(pages) - 20})" if len(pages) > 20 else "")


def note(meta: dict) -> tuple[str, bool] | None:
    """(Turkish then English note, hold) from an OCR result's metadata; None when every page was read. A hold only for
    the pages in `pages_gap`; every other text-less page is a note alone."""
    pages = [int(p) for p in meta.get("pages_unread") or []]
    if not pages:
        return None
    gap = {int(p): why for p, why in (meta.get("pages_gap") or {}).items()}
    plain = [p for p in pages if p not in gap]
    parts: list[str] = []
    if plain:
        shown = _shown(plain)
        parts.append(f"{shown}. sayfada okunabilir metin yok (görsel/boş sayfa). No readable text on page(s) {shown} (image or blank page).")
    if gap:
        shown = _shown(sorted(gap))
        why_tr = "; ".join(f"{p}. sayfa: {gap[p][0]}" for p in sorted(gap)[:5])
        why_en = "; ".join(f"page {p}: {gap[p][1]}" for p in sorted(gap)[:5])
        parts.append(f"Sayfa {shown} okunamadı; bu sayfalardaki kayıtlar eksik olabilir ({why_tr}). "
                     f"Page(s) {shown} could not be read; rows on them may be missing ({why_en}).")
    return " ".join(parts), bool(gap)
