"""Does a page that yielded no text mean DATA IS MISSING? Decided from evidence, never from "there was an image".

A logo-only cover, a stamp or signature page, a blank page give OCR nothing and lose no row. A SCANNED page (an image
covering most of the page, classified in the child from its geometry: `ocr_service.SCAN_COVERAGE`) that OCR could not
read may hold transactions. A person's attention is spent where rows may be missing, so for every text-less page:

1. The statement says where it ends and the rows do not reach it: a stated closing balance ("Kapanış Bakiyesi",
   "Closing Balance") that neither the last nor the first row's balance equals, or a stated period end
   (`stated_period.py`) more than a week after the latest row. HOLD, naming the page. When the rows DO reach the stated
   end that is the strongest evidence nothing is missing at the edges: a note only.
2. The page sits between pages with transaction rows: the first row after it must differ from the last row before it by
   exactly its own amount (oldest first) or the earlier row's (newest first). Not chaining, or no balance to check: HOLD.
   Chaining: a note (a scan then says the balances are continuous).
3. Nothing stated and no rows on one side: a scan HOLDS ("N. sayfa taranmış görünüyor ve okunamadı; işlemler eksik
   olabilir"); a small image or a blank page is a note ("görsel/boş sayfa"); the page before saying the statement
   continues ("sonraki sayfada devam") with no rows after also holds.

The whole-statement checks (coverage, balance continuity over the parsed rows) are unchanged. Pure functions over page
texts; the decision is recorded in the OCR result's metadata (`pages_unread`, `pages_scan`, `pages_gap`).
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from typing import Any

_DATE = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)")
_MONEY = re.compile(r"(?<![\d.,])-?\d{1,3}(?:\.\d{3})*,\d{2}(?!\d)|(?<![\d.,])-?\d+,\d{2}(?!\d)")
_CONTINUES = re.compile(r"sonraki\s+sayfada\s+devam|devam[ıi]\s+(?:var|sonraki)|continued\s+on\s+(?:the\s+)?next\s+page", re.I)
_CLOSING = re.compile(
    r"(?:kapanış|kapanis|dönem\s*sonu|donem\s*sonu|son|closing|ending)\s*(?:bakiye|balance)(?:si)?[^\d\n-]{0,25}"
    r"(-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2})", re.I)
END_SLACK = timedelta(days=7)    # a statement may end a few quiet days before its stated period end


def _cents(token: str) -> int:
    return int(token.replace(".", "").replace(",", ""))


def _fmt(cents: int) -> str:
    return f"{abs(cents) // 100:,}".replace(",", ".") + f",{abs(cents) % 100:02d}"


def _day(line: str) -> date | None:
    m = _DATE.search(line)
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None
    except ValueError:
        return None


def dated_rows(text: str) -> list[tuple[date | None, list[int]]]:
    """For each line with a date and at least one amount: (its date, its amounts in cents in reading order)."""
    rows = []
    for line in text.splitlines():
        if _DATE.search(line):
            amounts = [_cents(m) for m in _MONEY.findall(line)]
            if amounts:
                rows.append((_day(line), amounts))
    return rows


def row_lines(text: str) -> list[list[int]]:
    return [amounts for _day_, amounts in dated_rows(text)]


def chains(before: list[int], after: list[int]) -> bool | None:
    """Do the balances of two rows that follow each other in the statement connect? (amount, balance) are the last two
    figures of a row. None when either row has no balance to compare."""
    if len(before) < 2 or len(after) < 2:
        return None
    step = abs(after[-1] - before[-1])
    return step == abs(after[-2]) or step == abs(before[-2])


def stated_end(pages: Sequence[tuple[int, str]]) -> tuple[bool, tuple[str, str]] | None:
    """What the statement says about where it ends, against the rows read: (reached, (Turkish, English) why not).
    None when it states nothing checkable (no closing balance or period, or no balance on the rows)."""
    text = "\n\n".join(t for _no, t in pages)
    rows = [r for page in pages for r in dated_rows(page[1])]
    if not rows:
        return None
    closing = _CLOSING.search(text)
    balances = [a[-1] for _d, a in (rows[0], rows[-1]) if len(a) >= 2]
    if closing and balances:
        stated = _cents(closing.group(1))
        if stated in balances:
            return True, ("", "")
        return False, (f"ekstrenin kapanış bakiyesi {_fmt(stated)}, okunan son bakiye {_fmt(balances[-1])}",
                       f"the statement's closing balance is {_fmt(stated)}, the last balance read is {_fmt(balances[-1])}")
    try:
        from app.services.stated_period import stated_period

        period = stated_period(text, [d.isoformat() for d, _a in rows if d])
    except Exception:   # a header the line reader cannot place is "nothing stated"
        period = None
    days = [d for d, _a in rows if d]
    if period and days:
        end = date.fromisoformat(period["end"])
        if max(days) + END_SLACK >= end:
            return True, ("", "")
        return False, (f"ekstre dönemi {end:%d.%m.%Y} tarihine kadar, okunan son işlem {max(days):%d.%m.%Y}",
                       f"the statement period runs to {end:%d.%m.%Y}, the last transaction read is {max(days):%d.%m.%Y}")
    return None


def holding_pages(pages: Sequence[tuple[int, str]], unread: Iterable[int], scans: Iterable[int] = ()) -> dict[int, tuple[str, str]]:
    """{page number: (Turkish, English) sentence} for the text-less pages that hold the upload. `pages` is every page as
    (1-based number, text); `unread` the text-less pages with content; `scans` those of them that are page-sized rasters."""
    texts = dict(pages)
    rows = {no: r for no, r in ((no, row_lines(t)) for no, t in pages if t.strip()) if r}
    scan_pages = set(scans)
    end = stated_end(pages)
    held: dict[int, tuple[str, str]] = {}
    for no in sorted(set(unread)):
        before = max((p for p in rows if p < no), default=None)
        after = min((p for p in rows if p > no), default=None)
        if end is not None and not end[0]:
            held[no] = (f"{no}. sayfa okunamadı: {end[1][0]}; işlemler eksik olabilir",
                        f"page {no} could not be read: {end[1][1]}; rows may be missing")
        elif before is not None and after is not None:
            linked = chains(rows[before][-1], rows[after][0])
            if linked is False:
                held[no] = (f"{no}. sayfa okunamadı: {before}. ve {after}. sayfadaki bakiyeler birbirine bağlanmıyor; işlemler eksik olabilir",
                            f"page {no} could not be read: the balances on pages {before} and {after} do not connect; rows may be missing")
            elif linked is None:
                held[no] = (f"{no}. sayfa okunamadı: {before}. ve {after}. sayfada işlem satırı var, bakiye bağlantısı doğrulanamadı; işlemler eksik olabilir",
                            f"page {no} could not be read: pages {before} and {after} hold transactions and the balance link could not be checked; rows may be missing")
        elif end is not None:
            continue    # the rows reach the statement's stated end
        elif no in scan_pages:
            held[no] = (f"{no}. sayfa taranmış görünüyor ve okunamadı; işlemler eksik olabilir",
                        f"page {no} looks scanned and could not be read; rows may be missing")
        elif before is not None and after is None and _CONTINUES.search(texts.get(before, "")):
            held[no] = (f"{no}. sayfa okunamadı: {before}. sayfa ekstrenin devam ettiğini söylüyor; işlemler eksik olabilir",
                        f"page {no} could not be read: page {before} says the statement continues; rows may be missing")
    return held


SCAN_COVERAGE = 0.5   # images covering at least this share of the page make it a scan (a logo or stamp covers far less)


def is_scan(rect: Sequence[float], boxes: Iterable[Sequence[float]]) -> bool:
    """Do these image boxes, clipped to the page rectangle (x0, y0, x1, y1), cover at least SCAN_COVERAGE of it?"""
    x0, y0, x1, y1 = rect
    area = (x1 - x0) * (y1 - y0)
    covered = sum(max(0.0, min(x1, b[2]) - max(x0, b[0])) * max(0.0, min(y1, b[3]) - max(y0, b[1])) for b in boxes)
    return area > 0 and covered / area >= SCAN_COVERAGE


def page_is_scan(page: Any) -> bool:
    """`is_scan` for a PyMuPDF page: its image boxes against its rectangle. Geometry only, no pixel is decoded."""
    try:
        return is_scan(tuple(page.rect), [info["bbox"] for info in page.get_image_info()])
    except (KeyError, TypeError, ValueError, RuntimeError, AttributeError):
        return False


def page_meta(page_results: Sequence[Any]) -> dict[str, Any]:
    """The OCR result's metadata about its text-less pages (`pages_unread`, `pages_scan`, `pages_gap`); empty when
    every page was read. Pages with an image or text are judged; a page with neither is a note only."""
    content = [pr.page_num + 1 for pr in page_results if pr.warnings and pr.had_content]
    blank = [pr.page_num + 1 for pr in page_results if pr.warnings and not pr.had_content]
    if not content and not blank:
        return {}
    meta: dict[str, Any] = {"pages_unread": sorted(content + blank)}
    scans = [pr.page_num + 1 for pr in page_results if pr.scan_like and pr.page_num + 1 in content]
    held = holding_pages([(pr.page_num + 1, pr.text) for pr in page_results], content, scans) if content else {}
    if scans:
        meta["pages_scan"] = scans
    if held:
        meta["pages_gap"] = {str(no): list(why) for no, why in held.items()}
    return meta


def _shown(pages: list[int]) -> str:
    return ", ".join(str(p) for p in pages[:20]) + (f" (+{len(pages) - 20})" if len(pages) > 20 else "")


def note(meta: dict) -> tuple[str, bool] | None:
    """(Turkish then English note, hold) from an OCR result's metadata; None when every page was read. A hold only for
    the pages in `pages_gap`. A page is called decorative ("görsel/boş sayfa") only when it is not a scan."""
    pages = [int(p) for p in meta.get("pages_unread") or []]
    if not pages:
        return None
    gap = {int(p): why for p, why in (meta.get("pages_gap") or {}).items()}
    scans = {int(p) for p in meta.get("pages_scan") or []}
    parts: list[str] = []
    if gap:
        parts.append("; ".join(gap[p][0] for p in sorted(gap)[:10]) + ". " + "; ".join(gap[p][1] for p in sorted(gap)[:10]) + ".")
    soft_scans = [p for p in pages if p not in gap and p in scans]
    plain = [p for p in pages if p not in gap and p not in scans]
    if soft_scans:
        shown = _shown(soft_scans)
        parts.append(f"{shown}. sayfa taranmış sayfa, okunamadı; hesap bakiyeleri tutarlı, kayıt eksik görünmüyor. "
                     f"Page(s) {shown} are scanned and could not be read; the balances are consistent, no rows look missing.")
    if plain:
        shown = _shown(plain)
        parts.append(f"{shown}. sayfada okunabilir metin yok (görsel/boş sayfa). No readable text on page(s) {shown} (image or blank page).")
    return " ".join(parts), bool(gap)
