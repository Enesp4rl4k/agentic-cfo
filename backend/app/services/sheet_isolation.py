"""Reading an uploaded spreadsheet or CSV: the parent side. The parsing is `sheet_child`, in a child process.

The same mechanism as the PDF reader, not a second copy of it: `pdf_isolation.run_worker` starts the child
(environment whitelist, own process group killed on timeout, capped stdout and stderr, a slot so only
`PDF_PARSE_CONCURRENCY` children run per process, a wait that gives up as "busy"). Here are only the argv, the
limits taken from settings, and the refusal texts.

Every refusal is `SheetOkunamadi`, an `OkunamayanDosya` (so each door that already shows that message shows
this one), whose text is Turkish then English, names the limit and what to do. Never an empty table.
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

from app.services import pdf_isolation
from app.services.ingest.table import OkunamayanDosya
from app.services.sheet_child import decode_cell

logger = logging.getLogger(__name__)

# Overridable in tests: the argv prefix of the child (extension, limits and the JSON follow).
_WORKER_COMMAND: list[str] | None = None

_SPLIT = "Dosyayı daha küçük parçalara bölüp yükleyin."
_SPLIT_EN = "Split the file into smaller parts and upload them separately."

_TEXTS: dict[str, tuple[str, str]] = {
    "sheet_too_large": (
        "Dosya okunamadı: dosya {size_mb} MB, sınır {limit_mb} MB (MAX_UPLOAD_SIZE_MB). " + _SPLIT,
        "The file could not be read: it is {size_mb} MB, the limit is {limit_mb} MB. " + _SPLIT_EN,
    ),
    "sheet_uncompressed_too_large": (
        "Excel dosyası okunamadı: açıldığında içeriği {limit_mb} MB sınırını aşıyor (SHEET_MAX_UNCOMPRESSED_MB). "
        "Dosya bozuk ya da kasıtlı olarak şişirilmiş olabilir. Excel'de açıp yalnızca gerekli sayfaları yeni bir "
        "dosyaya kaydedip yükleyin.",
        "The Excel file could not be read: its content is larger than {limit_mb} MB once opened. It may be damaged "
        "or inflated on purpose. Open it in Excel, save only the sheets you need as a new file, and upload that.",
    ),
    "sheet_too_many_members": (
        "Excel dosyası okunamadı: içinde {members} parça var, sınır {limit} (SHEET_MAX_ZIP_MEMBERS). "
        "Excel'de açıp yeni bir dosyaya kaydedip yükleyin.",
        "The Excel file could not be read: it holds {members} internal parts, the limit is {limit}. "
        "Open it in Excel, save it as a new file, and upload that.",
    ),
    "sheet_too_many_rows": (
        "Dosya okunamadı: {sheet} sayfasında {limit} satır sınırı (SHEET_MAX_ROWS) aşıldı. " + _SPLIT,
        "The file could not be read: sheet {sheet} is over the {limit} row limit. " + _SPLIT_EN,
    ),
    "sheet_too_many_columns": (
        "Dosya okunamadı: {sheet} sayfasında {limit} sütun sınırı (SHEET_MAX_COLUMNS) aşıldı. "
        "Yalnızca tablonuzu içeren sütunları yeni bir dosyaya kaydedip yükleyin.",
        "The file could not be read: sheet {sheet} is over the {limit} column limit. "
        "Save only the columns of your table as a new file and upload that.",
    ),
    "sheet_too_many_cells": (
        "Dosya okunamadı: toplam hücre sayısı {limit} sınırını (SHEET_MAX_CELLS) aştı. " + _SPLIT,
        "The file could not be read: it has more than {limit} cells (the limit). " + _SPLIT_EN,
    ),
    "csv_line_too_long": (
        "CSV dosyası okunamadı: bir satır {limit} karakter sınırını (SHEET_MAX_CSV_LINE_CHARS) aşıyor. "
        "Dosya bozuk olabilir; kaynağından yeniden dışa aktarın.",
        "The CSV file could not be read: a line is longer than the {limit} character limit. "
        "The file may be damaged; export it again from its source.",
    ),
    "sheet_unsafe_xml": (
        "Excel dosyası okunamadı: içinde güvenli olmayan bir XML tanımı (varlık/DTD) var. "
        "Dosyayı Excel'de açıp yeni bir dosyaya kaydedip yükleyin.",
        "The Excel file could not be read: it contains an unsafe XML declaration (entity or DTD). "
        "Open it in Excel, save it as a new file, and upload that.",
    ),
    "sheet_timeout": (
        "Dosya okunamadı: okuma {seconds} saniyelik sınırı aştı (SHEET_PARSE_TIMEOUT_SECONDS). " + _SPLIT,
        "The file could not be read: reading exceeded the {seconds} second limit. " + _SPLIT_EN,
    ),
    "sheet_output_too_large": (
        "Dosya okunamadı: dosyadan çıkan veri beklenenden çok büyük. " + _SPLIT,
        "The file could not be read: the data it produces is far larger than expected. " + _SPLIT_EN,
    ),
    "sheet_busy": (
        "Dosya okunamadı: sistem yoğun, {seconds} saniye içinde boş bir okuyucu bulunamadı. "
        "Sistem yoğun, tekrar deneyin: birkaç dakika sonra aynı dosyayı yeniden yükleyin.",
        "The file could not be read: the system is busy and no free reader became available within {seconds} seconds. "
        "Try again in a few minutes by uploading the same file again.",
    ),
    "sheet_memory": (
        "Dosya okunamadı: dosya bellek sınırını aştı (SHEET_CHILD_MEMORY_MB); dosyayı daha küçük parçalara bölüp yükleyin.",
        "The file could not be read: it exceeded the memory limit; split the file into smaller parts and upload them separately.",
    ),
    "sheet_unreadable": (
        "Excel dosyası açılamadı; bozuk ya da parola korumalı olabilir. Parolayı kaldırıp ya da dosyayı "
        "Excel'de yeniden kaydedip tekrar yükleyin.",
        "The Excel file could not be opened; it may be damaged or password-protected. "
        "Remove the password or re-save it in Excel and upload it again.",
    ),
}


class SheetOkunamadi(OkunamayanDosya):
    """The spreadsheet or CSV was refused or could not be read safely. `str(exc)` is Turkish, then English."""

    def __init__(self, code: str, **params: Any) -> None:
        self.code = code if code in _TEXTS else "sheet_unreadable"
        self.params = {"sheet": "", "members": 0, **params}
        super().__init__(self.user_text)

    @property
    def tr(self) -> str:
        return _TEXTS[self.code][0].format(**self.params)

    @property
    def en(self) -> str:
        return _TEXTS[self.code][1].format(**self.params)

    @property
    def user_text(self) -> str:
        return f"{self.tr}\n{self.en}"


def limits_from_settings() -> dict[str, int]:
    from app.config import get_settings

    s = get_settings()
    mb = 1024 * 1024
    return {
        "max_bytes": s.max_upload_size_mb * mb, "max_uncompressed": s.sheet_max_uncompressed_mb * mb,
        "max_zip_members": s.sheet_max_zip_members, "max_rows": s.sheet_max_rows, "max_columns": s.sheet_max_columns,
        "max_cells": s.sheet_max_cells, "max_csv_line_chars": s.sheet_max_csv_line_chars,
    }


_REFUSAL_FOR_STATUS = {"overflow": "sheet_output_too_large", "memory": "sheet_memory", "failed": "sheet_unreadable"}


def read_sheets(data: bytes, ext: str) -> list[tuple[str | None, list[list[Any]]]]:
    """Every sheet's rows as (sheet name, rows) for an `xlsx`, `csv` or `txt` file's bytes, read in the child.

    Raises `SheetOkunamadi` for a limit, a damaged file, a timeout or a busy system.
    """
    from app.config import get_settings

    s = get_settings()
    ext = ext.lower().lstrip(".")
    limits = limits_from_settings()
    if len(data) > limits["max_bytes"]:
        raise SheetOkunamadi("sheet_too_large", size_mb=f"{len(data) / 1024 / 1024:.1f}", limit_mb=s.max_upload_size_mb)
    argv = [
        *(_WORKER_COMMAND or [sys.executable, "-m", "app.services.sheet_child"]),
        "xlsx" if ext == "xlsx" else "csv", str(s.sheet_child_memory_mb), str(2 * s.sheet_parse_timeout_seconds),
        json.dumps(limits),
    ]
    outcome = pdf_isolation.run_worker(argv, timeout_s=s.sheet_parse_timeout_seconds, stdin_data=data, label=f"a .{ext} upload")
    if outcome.status == "busy":
        raise SheetOkunamadi("sheet_busy", seconds=s.parse_queue_wait_seconds)
    if outcome.status == "timeout":
        raise SheetOkunamadi("sheet_timeout", seconds=s.sheet_parse_timeout_seconds)
    if outcome.status != "ok":
        raise SheetOkunamadi(_REFUSAL_FOR_STATUS.get(outcome.status, "sheet_unreadable"))
    try:
        payload = json.loads(outcome.out.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("not an object")
    except ValueError:
        logger.warning("Sheet worker returned unreadable output")
        raise SheetOkunamadi("sheet_unreadable") from None
    if "refusal" in payload:
        refusal = payload["refusal"]
        raise SheetOkunamadi(refusal.get("code", "sheet_unreadable"), **refusal.get("params", {}))
    out: list[tuple[str | None, list[list[Any]]]] = []
    for sheet in payload.get("sheets", []):
        width = sheet.get("width", 0)
        rows = [[decode_cell(c) for c in r] + [None] * (width - len(r)) for r in sheet["rows"]]
        out.append((sheet["title"], rows))
    return out
