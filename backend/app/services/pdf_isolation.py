"""Limits and isolation for parsing an uploaded PDF (untrusted input to PyMuPDF, pdfminer and Tesseract).

`ocr_service.extract_text_from_pdf` calls `guarded_extract`: size cap, then the parse in a child process
(`python -m app.services.pdf_isolation <path> <force_ocr 0|1>`) with a timeout and no secrets in its
environment, so a crash (a segfault in a C parser) or a hang ends that process, not the API worker.

Every refusal, crash, timeout and unreadable output is a result with strategy "failed", no text and a
Turkish "PDF okunamadı: ..." warning; the ingest reader raises it to the user. Never an empty success.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# The upload door already refuses a file over max_upload_size_mb; the same cap is applied at the parser so
# a PDF that reaches it by another road (mail attachment, MCP, scheduled sync) is bounded too.
MAX_PDF_PAGES = 200
# One whole parse (every page, every strategy). A statement of 200 pages needs well under this.
PARSE_TIMEOUT_SECONDS = 90
# A page rendered for OCR may not exceed this many pixels (a 14400 x 14400 pt page at 300 dpi would be a
# 3.4-gigapixel bitmap); also the decompression-bomb ceiling set on Pillow for that render.
MAX_RENDER_PIXELS = 60_000_000
# Tests that patch parser internals switch the child process off; production leaves it on.
ISOLATE_PARSER = True
# Overridable in tests: the argv prefix of the child (the path and flag are appended).
_WORKER_COMMAND: list[str] | None = None
_WORKER_MAX_STDOUT = 64 * 1024 * 1024
# The child parses attacker-controlled bytes: it gets no secrets (no CMAP_PATH, no keys), only what a parser needs.
_WORKER_ENV_KEEP = (
    "PATH", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "HOME", "LANG", "LC_ALL", "TESSDATA_PREFIX",
    "VIRTUAL_ENV", "LD_LIBRARY_PATH",
)


class PdfOkunamadi(Exception):
    """The PDF was refused or could not be parsed safely. The message is shown to the user."""


def refused(file_path: str, reason: str) -> Any:
    from app.services.ocr_service import OCRResult

    return OCRResult(
        text="", confidence=0.0, strategy_used="failed", page_count=0, page_results=[],
        file_path=file_path, warnings=[f"PDF okunamadı: {reason}"],
    )


def _from_payload(payload: dict[str, Any]) -> Any:
    from app.services.ocr_service import OCRResult, PageResult

    pages = [PageResult(**p) for p in payload.pop("page_results", [])]
    return OCRResult(page_results=pages, **payload)


def _command(file_path: str, force_ocr: bool) -> list[str]:
    base = _WORKER_COMMAND or [sys.executable, "-m", "app.services.pdf_isolation"]
    return [*base, file_path, "1" if force_ocr else "0"]


def _run_child(file_path: str, force_ocr: bool) -> Any:
    backend_dir = Path(__file__).resolve().parents[2]
    env = {k: v for k, v in os.environ.items() if k in _WORKER_ENV_KEEP}
    env["PYTHONPATH"] = str(backend_dir)
    try:
        proc = subprocess.run(
            _command(file_path, force_ocr),
            capture_output=True, timeout=PARSE_TIMEOUT_SECONDS, cwd=str(backend_dir), env=env, check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("PDF parse exceeded %ss and was killed: %s", PARSE_TIMEOUT_SECONDS, Path(file_path).name)
        return refused(file_path, f"okuma {PARSE_TIMEOUT_SECONDS} saniyede bitmedi; dosya çok karmaşık ya da bozuk.")
    except OSError as exc:
        logger.error("PDF worker could not be started: %s", exc)
        return refused(file_path, "okuma işlemi başlatılamadı.")
    if proc.returncode != 0 or not proc.stdout:
        logger.warning("PDF worker failed (exit %s): %s", proc.returncode, proc.stderr[-500:].decode("utf-8", "replace"))
        return refused(file_path, "dosya okunurken bir hata oluştu; dosya bozuk olabilir.")
    if len(proc.stdout) > _WORKER_MAX_STDOUT:
        return refused(file_path, "dosyadan çıkan metin beklenenden çok büyük.")
    try:
        return _from_payload(json.loads(proc.stdout.decode("utf-8")))
    except (ValueError, TypeError, KeyError):
        logger.warning("PDF worker returned unreadable output for %s", Path(file_path).name)
        return refused(file_path, "dosya okunurken bir hata oluştu; dosya bozuk olabilir.")


def guarded_extract(file_path: str, force_ocr: bool, in_process: Callable[[str, bool], Any]) -> Any:
    """Size cap, then the parse in a child process (or `in_process` when isolation is off or the file is absent)."""
    path = Path(file_path)
    if path.exists():
        from app.config import get_settings

        limit = get_settings().max_upload_size_mb * 1024 * 1024
        size = path.stat().st_size
        if size > limit:
            return refused(file_path, f"dosya {size / 1024 / 1024:.1f} MB; en fazla {limit // 1024 // 1024} MB okunur.")
        if ISOLATE_PARSER:
            return _run_child(file_path, force_ocr)
    return in_process(file_path, force_ocr)


def _child_main(argv: list[str]) -> int:
    from app.services.ocr_service import _extract_in_process

    # A library may print to stdout (PyMuPDF's `fitz` import does); only the JSON below may reach it.
    with contextlib.redirect_stdout(sys.stderr):
        result = _extract_in_process(argv[1], argv[2] == "1")
    # json.dumps escapes to ASCII, so no console codepage can mangle the text.
    sys.stdout.write(json.dumps(asdict(result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(_child_main(sys.argv))
