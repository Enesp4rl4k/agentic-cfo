"""The code that reads an uploaded spreadsheet or CSV INSIDE the child process of `sheet_isolation`.

An .xlsx is a zip of XML: a few kilobytes can inflate to gigabytes (zip bomb), and XML can declare entities
that expand the same way (entity bomb). So openpyxl, `zipfile` and the csv module run only here, in a process
that has `RLIMIT_AS` / `RLIMIT_CPU`, a deadline and a capped stdout (`pdf_isolation.run_worker`), and the
parent never touches the bytes. This module is light on purpose (standard library, openpyxl on demand): the
child starts fast and the parent can import `metin_coz` without pulling a parser.

Limits (all from settings, passed as JSON; a breach is a `SheetLimit` the parent shows as a specific refusal):
  file size; zip member count and TOTAL uncompressed size, checked from the zip directory before anything is
  read AND counted again while members are read (a directory can lie); rows, columns and cells returned;
  CSV line length. Over a limit the file is refused, never truncated: no row is dropped silently.
openpyxl runs `read_only=True, data_only=True`, and with `defusedxml` (a missing or disabled defusedxml is
a refusal, not a quiet fallback to the stdlib parser).

Protocol: argv = [ext, mem_mb, cpu_s, limits_json]; the file's bytes arrive on stdin; stdout is one JSON object,
`{"sheets": [{"title": ..., "rows": [[cell, ...], ...]}]}` or `{"refusal": {"code": ..., "params": {...}}}`.
A cell is null, a string, a number, a bool, or a one-letter tagged list for a date/time (`["d", iso]`).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import zipfile
from datetime import date, datetime, time, timedelta
from typing import Any

_MAX_BASLIK_ARAMA = 25   # a header is never further down than this (table.py shares the number)


class SheetLimit(BaseException):
    """A limit was hit. BaseException on purpose: a library's `except Exception` must not swallow it."""

    def __init__(self, code: str, **params: Any) -> None:
        super().__init__(code)
        self.code = code
        self.params = params


# ── Text: shared by the child and by every door that reads a CSV or text file as text ────────

def metin_coz(veri: bytes) -> str:
    """Text of a file as written: UTF-8 (with or without BOM), else Windows-1254, else Latin-1.

    Turkish bank and ERP exports are very often Windows-1254; every door that reads a CSV or text file as
    text goes through this one, so they cannot disagree. The detection is bounded: three fixed candidates,
    each one pass over a file the upload cap has already bounded.
    """
    for enc in ("utf-8-sig", "cp1254"):
        try:
            return veri.decode(enc)
        except UnicodeDecodeError:
            continue
    return veri.decode("latin-1")


def ayirici(metin: str) -> str:
    satirlar = [s for s in metin.splitlines() if s.strip()][:_MAX_BASLIK_ARAMA]
    best, best_score = ",", -1
    for d in (";", "\t", ",", "|"):
        counts = [s.count(d) for s in satirlar]
        if not counts or max(counts) == 0:
            continue
        # The delimiter is the one most lines agree on, weighted by how many
        # columns that makes: "1.234,56" puts commas in amounts, not in headers.
        mode = max(set(counts), key=counts.count)
        score = counts.count(mode) * mode
        if score > best_score:
            best, best_score = d, score
    return best


def check_text_bytes(veri: bytes, max_bytes: int, max_line_chars: int) -> None:
    """Raise `SheetLimit` for a CSV or text file over the size cap, or with a line longer than the cap."""
    if len(veri) > max_bytes:
        raise SheetLimit("sheet_too_large", size_mb=f"{len(veri) / 1024 / 1024:.1f}", limit_mb=max(1, max_bytes // (1024 * 1024)))
    # Linear scan, no copy: any run of `max_line_chars + 1` bytes without a line break.
    if re.search(rb"[^\r\n]{%d}" % (max_line_chars + 1), veri):
        raise SheetLimit("csv_line_too_long", limit=max_line_chars)


# ── Cells as JSON ────────────────────────────────────────────────────────────────────────────

def encode_cell(v: Any) -> Any:
    if v is None or isinstance(v, (str, bool, int, float)):
        return v
    if isinstance(v, datetime):   # before date: datetime is a date
        return ["dt", v.isoformat()]
    if isinstance(v, date):
        return ["d", v.isoformat()]
    if isinstance(v, time):
        return ["t", v.isoformat()]
    if isinstance(v, timedelta):
        return ["td", v.total_seconds()]
    return str(v)


def decode_cell(v: Any) -> Any:
    if isinstance(v, list) and len(v) == 2:
        tag, val = v
        if tag == "dt":
            return datetime.fromisoformat(val)
        if tag == "d":
            return date.fromisoformat(val)
        if tag == "t":
            return time.fromisoformat(val)
        if tag == "td":
            return timedelta(seconds=val)
    return v


# ── xlsx ─────────────────────────────────────────────────────────────────────────────────────

class _Count:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.total = 0

    def add(self, n: int) -> None:
        self.total += n
        if self.total > self.limit:
            raise SheetLimit("sheet_uncompressed_too_large", limit_mb=max(1, self.limit // (1024 * 1024)))


class _CountingFile:
    """A zip member as openpyxl reads it, counting every byte that comes out against the file's total."""

    def __init__(self, inner: Any, count: _Count) -> None:
        self._inner, self._count = inner, count

    def read(self, n: int = -1) -> bytes:
        data = self._inner.read(n)
        self._count.add(len(data))
        return data

    def read1(self, n: int = -1) -> bytes:
        data = self._inner.read1(n)
        self._count.add(len(data))
        return data

    def readline(self, limit: int = -1) -> bytes:
        data = self._inner.readline(limit)
        self._count.add(len(data))
        return data

    def __iter__(self) -> _CountingFile:
        return self

    def __next__(self) -> bytes:
        line = self.readline()
        if not line:
            raise StopIteration
        return line

    def __enter__(self) -> _CountingFile:
        return self

    def __exit__(self, *exc: Any) -> None:
        self._inner.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def check_zip_directory(data: bytes, limits: dict[str, int]) -> None:
    """From the zip directory alone, before any member is read."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
    except (zipfile.BadZipFile, ValueError, OSError, NotImplementedError) as exc:
        raise SheetLimit("sheet_unreadable") from exc
    if len(infos) > limits["max_zip_members"]:
        raise SheetLimit("sheet_too_many_members", members=len(infos), limit=limits["max_zip_members"])
    declared = sum(i.file_size for i in infos)
    if declared > limits["max_uncompressed"]:
        raise SheetLimit("sheet_uncompressed_too_large", limit_mb=max(1, limits["max_uncompressed"] // (1024 * 1024)))


@contextlib.contextmanager
def counting_zip_reads(limit: int):
    """While active, every member opened from any ZipFile in this (child) process counts against `limit`."""
    count = _Count(limit)
    original = zipfile.ZipFile.open

    def guarded(self: zipfile.ZipFile, name: Any, mode: str = "r", pwd: Any = None, *, force_zip64: bool = False):
        member = original(self, name, mode, pwd, force_zip64=force_zip64)
        return _CountingFile(member, count) if mode == "r" else member

    zipfile.ZipFile.open = guarded  # type: ignore[method-assign]
    try:
        yield count
    finally:
        zipfile.ZipFile.open = original  # type: ignore[method-assign]


def _trim(row: tuple[Any, ...]) -> list[Any]:
    cells = list(row)
    while cells and cells[-1] is None:
        cells.pop()
    return cells


def _caused_by_defused(exc: BaseException | None) -> bool:
    """openpyxl wraps XML errors in a ValueError; the refusal of an entity or DTD is somewhere down the chain."""
    from defusedxml import DefusedXmlException

    seen = 0
    while exc is not None and seen < 10:
        if isinstance(exc, DefusedXmlException):
            return True
        exc, seen = exc.__cause__ or exc.__context__, seen + 1
    return False


def read_xlsx(data: bytes, limits: dict[str, int], *, check_directory: bool = True) -> list[dict[str, Any]]:
    from openpyxl.xml import DEFUSEDXML

    if not DEFUSEDXML:   # openpyxl would fall back to the stdlib parser, which expands entities
        raise SheetLimit("sheet_unreadable", reason="defusedxml is not active")
    if check_directory:
        check_zip_directory(data, limits)
    from openpyxl import load_workbook

    sheets: list[dict[str, Any]] = []
    cells = 0
    with counting_zip_reads(limits["max_uncompressed"]) as count:
        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:
            if _caused_by_defused(exc):
                raise SheetLimit("sheet_unsafe_xml") from exc
            if count.total > count.limit:
                raise SheetLimit("sheet_uncompressed_too_large", limit_mb=max(1, count.limit // (1024 * 1024))) from exc
            raise SheetLimit("sheet_unreadable") from exc
        try:
            for ws in wb.worksheets:
                rows: list[list[Any]] = []
                width = 0
                for raw in ws.iter_rows(values_only=True):
                    row = _trim(raw)
                    if len(row) > limits["max_columns"]:
                        raise SheetLimit("sheet_too_many_columns", sheet=ws.title, limit=limits["max_columns"])
                    if len(rows) >= limits["max_rows"]:
                        raise SheetLimit("sheet_too_many_rows", sheet=ws.title, limit=limits["max_rows"])
                    cells += len(row)
                    if cells > limits["max_cells"]:
                        raise SheetLimit("sheet_too_many_cells", limit=limits["max_cells"])
                    width = max(width, len(row))
                    rows.append(row)
                # The rows had been padded to the sheet's width by openpyxl; keep them that way (see `sheet_isolation`).
                sheets.append({"title": ws.title, "rows": [[encode_cell(c) for c in r] for r in rows], "width": width})
        except Exception as exc:
            if _caused_by_defused(exc):
                raise SheetLimit("sheet_unsafe_xml") from exc
            raise
        finally:
            wb.close()
    return sheets


# ── csv ──────────────────────────────────────────────────────────────────────────────────────

def read_csv(data: bytes, limits: dict[str, int]) -> list[dict[str, Any]]:
    import csv

    check_text_bytes(data, limits["max_bytes"], limits["max_csv_line_chars"])
    metin = metin_coz(data)
    csv.field_size_limit(limits["max_csv_line_chars"])
    rows: list[list[str]] = []
    cells = 0
    try:
        for r in csv.reader(io.StringIO(metin), delimiter=ayirici(metin)):
            if len(r) > limits["max_columns"]:
                raise SheetLimit("sheet_too_many_columns", sheet="", limit=limits["max_columns"])
            if len(rows) >= limits["max_rows"]:
                raise SheetLimit("sheet_too_many_rows", sheet="", limit=limits["max_rows"])
            cells += len(r)
            if cells > limits["max_cells"]:
                raise SheetLimit("sheet_too_many_cells", limit=limits["max_cells"])
            rows.append(list(r))
    except csv.Error as exc:
        raise SheetLimit("csv_line_too_long", limit=limits["max_csv_line_chars"]) from exc
    return [{"title": None, "rows": rows, "width": 0}]


# ── Entry point ──────────────────────────────────────────────────────────────────────────────

def parse(data: bytes, ext: str, limits: dict[str, int]) -> dict[str, Any]:
    try:
        if len(data) > limits["max_bytes"]:
            raise SheetLimit("sheet_too_large", size_mb=f"{len(data) / 1024 / 1024:.1f}", limit_mb=max(1, limits["max_bytes"] // (1024 * 1024)))
        return {"sheets": read_xlsx(data, limits) if ext == "xlsx" else read_csv(data, limits)}
    except SheetLimit as limit:
        return {"refusal": {"code": limit.code, "params": limit.params}}
    except MemoryError:
        return {"refusal": {"code": "sheet_unreadable", "params": {}}}


def _child_main(argv: list[str]) -> int:
    # Before openpyxl is imported: with lxml present openpyxl parses most parts with lxml, which tolerates an
    # entity declaration; with this off, EVERY part goes through defusedxml, which refuses it.
    os.environ["OPENPYXL_LXML"] = "False"
    ext, mem_mb, cpu_s = argv[1], int(argv[2]), int(argv[3])
    limits = {k: int(v) for k, v in json.loads(argv[4]).items()}
    from app.services.pdf_isolation import _apply_limits

    _apply_limits(mem_mb, cpu_s)
    data = sys.stdin.buffer.read(limits["max_bytes"] + 1)
    with contextlib.redirect_stdout(sys.stderr):
        result = parse(data, ext, limits)
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":
    from app.services import sheet_child

    raise SystemExit(sheet_child._child_main(sys.argv))
