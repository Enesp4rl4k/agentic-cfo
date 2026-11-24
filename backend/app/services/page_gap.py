"""Does a page that yielded no text mean DATA IS MISSING? Decided from evidence, never from "there was an image".

A logo-only cover, a stamp or signature page, a blank page give OCR nothing and lose no row. A SCANNED page (images
covering at least `SCAN_COVERAGE` of a page that has no readable text, classified in the child from geometry) that
OCR could not read may hold transactions. A person's attention is spent where rows may be missing, so for every
text-less page, in this order:

1. The statement states a closing balance or period end and the rows fall short of it: hold, naming the page. (A stated
   period end counts only against the rows: reaching it, even with a week of slack, proves nothing and suppresses
   nothing.)
2. The page sits between pages with transaction rows: the first row after it must differ from the last row before it by
   exactly its own amount (oldest first) or the earlier row's (newest first). Not chaining, or no balance to check: HOLD.
   Chaining: VERIFIED (a scan then says the balances are continuous).
3. An edge page (rows on one side only): ONLY a stated closing balance equal to the chronologically last row's running
   balance verifies it. Otherwise a scan holds ("N. sayfa taranmış görünüyor ve okunamadı; işlemler eksik olabilir"),
   a small image or blank page is a note ("görsel/boş sayfa"), and a page before it saying the statement continues,
   with no rows after, holds.

Wording follows the evidence: "bakiyeler süreklidir / satır eksik görünmüyor" appears only for a VERIFIED page.
The whole-statement checks (coverage, balance continuity over the parsed rows) are unchanged. Pure functions over page
texts; the decision is recorded in the OCR result's metadata (`pages_unread`, `pages_scan`, `pages_gap`, `pages_verified`).
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

SCAN_COVERAGE = 0.2   # images covering this share of a page with no readable text: a scan. A logo or stamp covers a few percent; a half-page scan of the last rows must count.

_DATE = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)")
_MONEY = re.compile(r"(?<![\d.,])-?\d{1,3}(?:\.\d{3})*,\d{2}(?!\d)|(?<![\d.,])-?\d+,\d{2}(?!\d)")
_CONTINUES = re.compile(r"sonraki\s+sayfada\s+devam|devam[ıi]\s+(?:var|sonraki)|continued\s+on\s+(?:the\s+)?next\s+page", re.I)
_AMOUNT = r"(-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2})"
# The statement's OWN closing balance. "Önceki dönem kapanış bakiyesi", "Devreden", "Açılış" are its opening balance.
_CLOSING = re.compile(r"(?:kapanış|kapanis|dönem\s*sonu|donem\s*sonu|son|closing|ending)\s*(?:bakiye|balance)(?:si)?[^\d\n-]{0,25}" + _AMOUNT, re.I)
_OPENING = re.compile(r"önceki|onceki|açılış|acilis|devreden|opening|previous|başlangıç|baslangic|brought", re.I)


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


def stated_closing(text: str) -> int | None:
    """The statement's own closing balance in cents; None when it states none, or states two different ones (ambiguous:
    treated as not stated). Opening-balance phrasings never match."""
    found = set()
    for m in _CLOSING.finditer(text):
        before_on_line = text[text.rfind("\n", 0, m.start()) + 1:m.start()]
        if not _OPENING.search(before_on_line) and not _OPENING.search(m.group(0)):
            found.add(_cents(m.group(1)))
    return found.pop() if len(found) == 1 else None


def stated_end(pages: Sequence[tuple[int, str]]) -> tuple[str, tuple[str, str]] | None:
    """What the statement says about where it ends, against the rows read: ("exact", ...) when the stated closing
    balance equals the chronologically last row's balance, ("short", (Turkish, English why)) when a stated closing
    balance or period end is not reached, None when nothing checkable is stated."""
    text = "\n\n".join(t for _no, t in pages)
    rows = [r for page in pages for r in dated_rows(page[1])]
    if not rows:
        return None
    newest_first = bool(rows[0][0] and rows[-1][0] and rows[0][0] > rows[-1][0])
    last_row = rows[0] if newest_first else rows[-1]
    closing = stated_closing(text)
    if closing is not None and len(last_row[1]) >= 2:
        last = last_row[1][-1]
        if closing == last:
            return "exact", ("", "")
        return "short", (f"ekstrenin kapanış bakiyesi {_fmt(closing)}, okunan son bakiye {_fmt(last)}",
                         f"the statement's closing balance is {_fmt(closing)}, the last balance read is {_fmt(last)}")
    try:
        from app.services.stated_period import stated_period

        period = stated_period(text, [d.isoformat() for d, _a in rows if d])
    except Exception:   # a header the line reader cannot place is "nothing stated"
        period = None
    days = [d for d, _a in rows if d]
    if period and days:
        end = date.fromisoformat(period["end"])
        if max(days) < end and (end - max(days)).days > 7:   # a week of quiet days is normal; more is evidence
            return "short", (f"ekstre dönemi {end:%d.%m.%Y} tarihine kadar, okunan son işlem {max(days):%d.%m.%Y}",
                             f"the statement period runs to {end:%d.%m.%Y}, the last transaction read is {max(days):%d.%m.%Y}")
    return None


def judge(pages: Sequence[tuple[int, str]], unread: Iterable[int], scans: Iterable[int] = ()) -> tuple[dict[int, tuple[str, str]], dict[int, str]]:
    """(holds, verified) for the text-less pages. `holds` is {page: (Turkish, English) sentence}; `verified` is
    {page: "chain" | "closing"} for the pages whose neighbours or stated closing balance positively show nothing is missing.
    `pages` is every page as (1-based number, text); `unread` the text-less pages with content; `scans` the page-sized rasters."""
    texts = dict(pages)
    rows = {no: r for no, r in ((no, row_lines(t)) for no, t in pages if t.strip()) if r}
    scan_pages = set(scans)
    end = stated_end(pages)
    held: dict[int, tuple[str, str]] = {}
    verified: dict[int, str] = {}
    for no in sorted(set(unread)):
        before = max((p for p in rows if p < no), default=None)
        after = min((p for p in rows if p > no), default=None)
        if end is not None and end[0] == "short":
            held[no] = (f"{no}. sayfa okunamadı: {end[1][0]}; işlemler eksik olabilir",
                        f"page {no} could not be read: {end[1][1]}; rows may be missing")
        elif before is not None and after is not None:
            linked = chains(rows[before][-1], rows[after][0])
            if linked is True:
                verified[no] = "chain"
            elif linked is False:
                held[no] = (f"{no}. sayfa okunamadı: {before}. ve {after}. sayfadaki bakiyeler birbirine bağlanmıyor; işlemler eksik olabilir",
                            f"page {no} could not be read: the balances on pages {before} and {after} do not connect; rows may be missing")
            else:
                held[no] = (f"{no}. sayfa okunamadı: {before}. ve {after}. sayfada işlem satırı var, bakiye bağlantısı doğrulanamadı; işlemler eksik olabilir",
                            f"page {no} could not be read: pages {before} and {after} hold transactions and the balance link could not be checked; rows may be missing")
        elif end is not None:   # "exact": the stated closing balance is the last row's balance
            verified[no] = "closing"
        elif no in scan_pages:
            held[no] = (f"{no}. sayfa taranmış görünüyor ve okunamadı; işlemler eksik olabilir",
                        f"page {no} looks scanned and could not be read; rows may be missing")
        elif before is not None and after is None and _CONTINUES.search(texts.get(before, "")):
            held[no] = (f"{no}. sayfa okunamadı: {before}. sayfa ekstrenin devam ettiğini söylüyor; işlemler eksik olabilir",
                        f"page {no} could not be read: page {before} says the statement continues; rows may be missing")
    return held, verified


def holding_pages(pages: Sequence[tuple[int, str]], unread: Iterable[int], scans: Iterable[int] = ()) -> dict[int, tuple[str, str]]:
    return judge(pages, unread, scans)[0]


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
    """The OCR result's metadata about its text-less pages; empty when every page was read. Pages with an image or
    text are judged; a page with neither is a note only."""
    content = [pr.page_num + 1 for pr in page_results if pr.warnings and pr.had_content]
    blank = [pr.page_num + 1 for pr in page_results if pr.warnings and not pr.had_content]
    if not content and not blank:
        return {}
    meta: dict[str, Any] = {"pages_unread": sorted(content + blank)}
    scans = [pr.page_num + 1 for pr in page_results if pr.scan_like and pr.page_num + 1 in content]
    held, verified = judge([(pr.page_num + 1, pr.text) for pr in page_results], content, scans) if content else ({}, {})
    if scans:
        meta["pages_scan"] = scans
    if held:
        meta["pages_gap"] = {str(no): list(why) for no, why in held.items()}
    if verified:
        meta["pages_verified"] = {str(no): how for no, how in verified.items()}
    return meta


def entries(meta: dict) -> list[dict[str, Any]]:
    """One entry per text-less page: {page, state, tr, en}. State: "hold" (rows may be missing), "scan_verified" (a scan
    whose neighbours chain or whose closing balance matches), "note". A page is called an image or blank page only when
    it is not a scan; the "balances are continuous" sentence is only for a verified one."""
    gap = {int(p): why for p, why in (meta.get("pages_gap") or {}).items()}
    scans = {int(p) for p in meta.get("pages_scan") or []}
    verified = {int(p): how for p, how in (meta.get("pages_verified") or {}).items()}
    out: list[dict[str, Any]] = []
    for p in sorted(int(x) for x in meta.get("pages_unread") or []):
        if p in gap:
            out.append({"page": p, "state": "hold", "tr": gap[p][0], "en": gap[p][1]})
        elif p in scans and p in verified:
            how_tr, how_en = (("bakiyeler süreklidir", "the balances are continuous") if verified[p] == "chain" else
                              ("ekstrenin kapanış bakiyesi okunan son bakiyeyle aynıdır", "the statement's closing balance equals the last balance read"))
            out.append({"page": p, "state": "scan_verified",
                        "tr": f"{p}. sayfa taranmış sayfa ve okunamadı; {how_tr}, satır eksik görünmüyor",
                        "en": f"page {p} is a scanned page and could not be read; {how_en}, no rows look missing"})
        elif p in scans:
            out.append({"page": p, "state": "note", "tr": f"{p}. sayfada okunabilir metin yok", "en": f"page {p} has no readable text"})
        else:
            out.append({"page": p, "state": "note", "tr": f"{p}. sayfada okunabilir metin yok (görsel/boş sayfa)",
                        "en": f"page {p} has no readable text (image or blank page)"})
    return out


def note(meta: dict) -> tuple[str, bool] | None:
    """(Turkish then English note, hold) from an OCR result's metadata; None when every page was read."""
    items = entries(meta)
    if not items:
        return None
    shown, more = items[:20], len(items) - 20
    tail = f" (+{more})" if more > 0 else ""
    return ("; ".join(e["tr"] for e in shown) + tail + ". " + "; ".join(e["en"] for e in shown) + tail + ".",
            any(e["state"] == "hold" for e in items))
