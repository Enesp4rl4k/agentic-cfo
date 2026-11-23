"""Limits and isolation for parsing an uploaded PDF (untrusted input to PyMuPDF, pdfminer and Tesseract).

EVERY parser of an uploaded PDF's bytes runs in the child process of this module
(`python -m app.services.pdf_isolation <path> <force_ocr> <mem_mb> <cpu_s> <ocr_s> <max_pages>`):
page text, tables, OCR render and Tesseract, and the e-Belge attachment (`pdf_embedded`). The parent
(API or arq worker) only reads bytes from a pipe. The parent:

* refuses a file over the upload size cap before starting anything;
* starts the child in its own process group (session), with an environment that holds no secrets,
  and bounded by `RLIMIT_AS` / `RLIMIT_CPU` set by the child on itself (Linux), which also makes itself the
  preferred OOM victim; the parent enforces `PARSE_CHILD_RSS_MB` on the group's resident memory (`parser_guard`);
* runs at most `PDF_PARSE_CONCURRENCY` children at a time PER PROCESS (a waiter is refused as "busy" after
  `PARSE_QUEUE_WAIT_SECONDS`; the real bound is that times the processes, docs/ops/parser-sizing.md);
* reads the child's stdout and stderr with a cap while they arrive (fixed-size reads; over the cap: kill);
* kills the child's whole process group when the deadline passes (a Tesseract grandchild dies with it).
  Deadline: `PDF_PARSE_TIMEOUT_SECONDS`, plus `PDF_OCR_SECONDS_PER_PAGE` for each page the child reports
  it started to OCR, so a long scanned statement is not refused for being long.

Every refusal, crash, timeout and unreadable output is a result with strategy "failed", no text and a
`refusal` code in its metadata; `_read_pdf` raises it as `PdfOkunamadi`, whose text says which limit was
hit and what to do (Turkish, then English, the repo's convention for operator and user texts).
Never an empty success.

`run_worker` is the one mechanism for every parser child: `sheet_isolation` (.xlsx, CSV) uses it too.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.services import parser_guard

logger = logging.getLogger(__name__)

# A page rendered for OCR may not exceed this many pixels (a 14400 x 14400 pt page at 300 dpi would be a
# 3.4-gigapixel bitmap); also the decompression-bomb ceiling set on Pillow for that render.
MAX_RENDER_PIXELS = 60_000_000
# Tests that patch parser internals switch the child process off; production leaves it on.
ISOLATE_PARSER = True
# Overridable in tests: the argv prefix of the child (the path, flag and limits are appended).
_WORKER_COMMAND: list[str] | None = None
_STDOUT_LIMIT = 64 * 1024 * 1024
_STDERR_KEEP = 2000
_STDERR_LINE_CAP = 4096          # a stderr line is held at most this long while it has no newline
_STDERR_TOTAL_LIMIT = 16 * 1024 * 1024
_OCR_MARK = "@@OCR@@"
_MEM_MARK = "@@MEM@@"      # the child hit its memory limit (a MemoryError reached the top)
_RSS_POLL_SECONDS = 0.25
_PEAK_MARK = "@@PEAK@@"    # "<VmPeak kB> <VmHWM kB> <largest descendant RSS kB>": the child's own peaks at exit
NEWLINE = bytes([10])
# The child parses attacker-controlled bytes: it gets no secrets (no CMAP_PATH, no keys), only what a parser needs.
_WORKER_ENV_KEEP = (
    "PATH", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "HOME", "LANG", "LC_ALL", "TESSDATA_PREFIX",
    "VIRTUAL_ENV", "LD_LIBRARY_PATH", "OMP_THREAD_LIMIT",
)

# What the child was told (set by `_child_main`); None in the parent and when isolation is off.
_child_limits: dict[str, int] = {}

_TEXTS: dict[str, tuple[str, str]] = {
    "pdf_too_large": (
        "PDF okunamadı: dosya {size_mb} MB, sınır {limit_mb} MB (MAX_UPLOAD_SIZE_MB). "
        "Ekstreyi daha kısa dönemlere bölüp yükleyin.",
        "The PDF could not be read: the file is {size_mb} MB, the limit is {limit_mb} MB. "
        "Split the statement into shorter periods and upload them separately.",
    ),
    "pdf_too_many_pages": (
        "PDF okunamadı: {pages} sayfa var, sınır {limit} sayfa (PDF_MAX_PAGES). "
        "Ekstreyi daha kısa dönemlere bölüp yükleyin.",
        "The PDF could not be read: it has {pages} pages, the limit is {limit}. "
        "Split the statement into shorter periods and upload them separately.",
    ),
    "pdf_timeout": (
        "PDF okunamadı: okuma {seconds} saniyelik sınırı aştı (PDF_PARSE_TIMEOUT_SECONDS). Dosya çok karmaşık "
        "ya da bozuk olabilir; ekstreyi daha kısa dönemlere bölüp yükleyin.",
        "The PDF could not be read: reading exceeded the {seconds} second limit. The file may be very complex "
        "or damaged; split the statement into shorter periods and upload them separately.",
    ),
    "pdf_output_too_large": (
        "PDF okunamadı: dosyadan çıkan metin beklenenden çok büyük. Ekstreyi daha kısa dönemlere bölüp yükleyin.",
        "The PDF could not be read: the text it produces is far larger than expected. "
        "Split the statement into shorter periods and upload them separately.",
    ),
    "pdf_busy": (
        "PDF okunamadı: sistem yoğun, {seconds} saniye içinde boş bir okuyucu bulunamadı. "
        "Sistem yoğun, tekrar deneyin: birkaç dakika sonra aynı dosyayı yeniden yükleyin.",
        "The PDF could not be read: the system is busy and no free reader became available within {seconds} seconds. "
        "Try again in a few minutes by uploading the same file again.",
    ),
    "pdf_memory": (
        "PDF okunamadı: dosya bellek sınırını aştı{where_tr} (PDF_CHILD_MEMORY_MB); "
        "daha kısa dönemlere bölüp yükleyin.",
        "The PDF could not be read: the file exceeded the memory limit{where_en}; "
        "split the statement into shorter periods and upload them separately.",
    ),
    "pdf_unreadable": (
        "PDF okunamadı: dosya bozuk, şifreli ya da desteklenmeyen bir biçimde olabilir. Dosyayı kaynağından "
        "yeniden indirin ya da PDF olarak yeniden kaydedip yükleyin.",
        "The PDF could not be read: it may be damaged, encrypted or in an unsupported form. "
        "Download it again from its source, or re-save it as a PDF, and upload it again.",
    ),
}


_DEFAULT_PARAMS = {"where_tr": "", "where_en": ""}


class PdfOkunamadi(Exception):
    """The PDF was refused or could not be parsed safely. `user_text` is shown to the user."""

    def __init__(self, code: str, **params: Any) -> None:
        self.code = code if code in _TEXTS else "pdf_unreadable"
        self.params = params
        super().__init__(self.tr)

    @property
    def tr(self) -> str:
        return _TEXTS[self.code][0].format(**{**_DEFAULT_PARAMS, **self.params})

    @property
    def en(self) -> str:
        return _TEXTS[self.code][1].format(**{**_DEFAULT_PARAMS, **self.params})

    @property
    def user_text(self) -> str:
        return f"{self.tr}\n{self.en}"


def memory_pages(first: int, last: int) -> dict[str, str]:
    """The `pdf_memory` refusal's parameters naming the pages that were not read (1-based)."""
    span = str(first) if first == last else f"{first}-{last}"
    return {"where_tr": f" (sayfa {span} okunamadı)", "where_en": f" (page {span} was not read)"}


def ingest_hata_metni(exc: BaseException) -> str:
    """The run's failure text for an exception: a refused PDF or spreadsheet reads as a sentence, anything else as before."""
    # a refused spreadsheet reads as a sentence too
    from app.services.sheet_isolation import SheetOkunamadi

    return exc.user_text if isinstance(exc, (PdfOkunamadi, SheetOkunamadi)) else f"Ingestion error: {exc}"


def refused(file_path: str, code: str, **params: Any) -> Any:
    from app.services.ocr_service import OCRResult

    error = PdfOkunamadi(code, **params)
    return OCRResult(
        text="", confidence=0.0, strategy_used="failed", page_count=0, page_results=[], file_path=file_path,
        warnings=[error.tr], metadata={"refusal": {"code": error.code, "params": params}},
    )


def raise_if_refused(result: Any) -> None:
    """A failed result becomes the exception the ingest reader raises (never a bare empty text)."""
    if result.strategy_used == "failed" and not result.text.strip():
        refusal = (result.metadata or {}).get("refusal") or {}
        raise PdfOkunamadi(refusal.get("code", "pdf_unreadable"), **refusal.get("params", {}))


# ── Limits as the child sees them ────────────────────────────────────────────────────────────

def max_pages() -> int:
    from app.config import get_settings

    return _child_limits.get("max_pages") or get_settings().pdf_max_pages


def ocr_timeout() -> int:
    from app.config import get_settings

    return _child_limits.get("ocr_s") or get_settings().pdf_ocr_seconds_per_page


def ocr_started() -> None:
    """Child side: tell the parent a page is going to OCR, which extends its deadline by one page budget."""
    if _child_limits:
        sys.stderr.write(_OCR_MARK + "\n")
        sys.stderr.flush()


# ── Parent side ──────────────────────────────────────────────────────────────────────────────

_slots: tuple[int, threading.BoundedSemaphore] | None = None
_slots_lock = threading.Lock()


class ParserBusy(Exception):
    """No parser slot became free within `PARSE_QUEUE_WAIT_SECONDS`."""


@contextlib.contextmanager
def _slot() -> Iterator[None]:
    """At most PDF_PARSE_CONCURRENCY children at once IN THIS PROCESS (PDF and spreadsheet children share
    the slots); a waiter gives up after PARSE_QUEUE_WAIT_SECONDS with `ParserBusy`, never hangs."""
    global _slots
    from app.config import get_settings

    s = get_settings()
    size = max(1, s.pdf_parse_concurrency)
    with _slots_lock:
        if _slots is None or _slots[0] != size:
            _slots = (size, threading.BoundedSemaphore(size))
        sem = _slots[1]
    if not sem.acquire(timeout=max(0, s.parse_queue_wait_seconds)):
        raise ParserBusy
    try:
        yield
    finally:
        sem.release()


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    """Kill the child and everything it started: its own process group, never anything by name."""
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)  # the child is its own group leader (start_new_session)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass
    with contextlib.suppress(Exception):
        proc.wait(timeout=10)


def _command(file_path: str, force_ocr: bool) -> list[str]:
    from app.config import get_settings

    s = get_settings()
    base = _WORKER_COMMAND or [sys.executable, "-m", "app.services.pdf_isolation"]
    cpu = 2 * s.pdf_parse_timeout_seconds
    return [
        *base, file_path, "1" if force_ocr else "0",
        str(s.pdf_child_memory_mb), str(cpu), str(s.pdf_ocr_seconds_per_page), str(s.pdf_max_pages),
    ]


def split_stderr(pending: bytes, chunk: bytes) -> tuple[list[bytes], bytes]:
    """Complete lines (each cut at `_STDERR_LINE_CAP`) and the unfinished rest, which never exceeds the cap:
    a child that writes without a newline cannot grow the parent's buffer."""
    *lines, rest = (pending + chunk).split(NEWLINE)
    lines = [line[:_STDERR_LINE_CAP] for line in lines]
    if len(rest) > _STDERR_LINE_CAP:
        lines.append(rest[:_STDERR_LINE_CAP])
        rest = b""
    return lines, rest


@dataclass
class ChildOutcome:
    """How a supervised child ended. `out` is its stdout, only when status is "ok"."""

    status: str   # ok | busy | overflow | timeout | memory | failed
    out: bytes = b""


def child_environment(backend_dir: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _WORKER_ENV_KEEP}
    env["PYTHONPATH"] = str(backend_dir)
    return env


def run_worker(argv: list[str], *, timeout_s: int, ocr_extra_s: int = 0, stdin_data: bytes | None = None,
               stdout_limit: int | None = None, label: str = "") -> ChildOutcome:
    """THE way a parser child is run (PDF and spreadsheet alike): a slot (or `busy`), a whitelisted environment,
    its own process group, a capped stdout and stderr, a deadline that kills the group. Never raises for a
    child's failure; the caller turns the outcome into its own visible refusal."""
    backend_dir = Path(__file__).resolve().parents[2]
    kwargs: dict[str, Any] = {}
    if os.name == "posix":
        kwargs["start_new_session"] = True
    else:  # pragma: no cover - dev boxes only
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        with _slot():
            return _supervise(argv, timeout_s, ocr_extra_s, stdin_data, stdout_limit or _STDOUT_LIMIT, label, backend_dir, kwargs)
    except ParserBusy:
        logger.warning("Parser slots busy; %s refused after the queue wait", label)
        return ChildOutcome("busy")
    except OSError as exc:
        logger.error("Parser worker could not be started: %s", exc)
        return ChildOutcome("failed")


def _run_child(file_path: str, force_ocr: bool) -> Any:
    from app.config import get_settings

    s = get_settings()
    outcome = run_worker(_command(file_path, force_ocr), timeout_s=s.pdf_parse_timeout_seconds,
                         ocr_extra_s=s.pdf_ocr_seconds_per_page, label=Path(file_path).name)
    if outcome.status == "busy":
        return refused(file_path, "pdf_busy", seconds=s.parse_queue_wait_seconds)
    if outcome.status == "memory":
        return refused(file_path, "pdf_memory")
    if outcome.status == "overflow":
        return refused(file_path, "pdf_output_too_large")
    if outcome.status == "timeout":
        return refused(file_path, "pdf_timeout", seconds=s.pdf_parse_timeout_seconds)
    if outcome.status != "ok":
        return refused(file_path, "pdf_unreadable")
    try:
        return _from_payload(json.loads(outcome.out.decode("utf-8")))
    except Exception:
        logger.warning("PDF worker returned unreadable output for %s", Path(file_path).name)
        return refused(file_path, "pdf_unreadable")


def _supervise(argv: list[str], timeout_s: int, ocr_extra_s: int, stdin_data: bytes | None, stdout_limit: int,
               label: str, backend_dir: Path, kwargs: dict[str, Any]) -> ChildOutcome:
    from app.config import get_settings

    proc = subprocess.Popen(
        argv, stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(backend_dir),
        env=child_environment(backend_dir), **kwargs,
    )
    out = bytearray()
    err = bytearray()
    state: dict[str, Any] = {"ocr": 0, "overflow": False, "memory": False}

    def read_stdout() -> None:
        assert proc.stdout is not None
        while chunk := proc.stdout.read(65536):
            if len(out) + len(chunk) > stdout_limit:
                state["overflow"] = True  # not buffered: the supervisor kills the group
                return
            out.extend(chunk)

    def note_line(line: bytes) -> None:
        stripped = line.strip()
        if stripped == _OCR_MARK.encode():
            state["ocr"] += 1
        elif stripped == _MEM_MARK.encode():
            state["memory"] = True
        elif stripped.startswith(_PEAK_MARK.encode()):
            logger.info("parser child peaks (kB: VmPeak VmHWM descendant-RSS): %s", stripped[len(_PEAK_MARK):].decode("ascii", "replace").strip())
        else:
            err.extend(line[:500])
            del err[:-_STDERR_KEEP]

    def read_stderr() -> None:
        # Fixed-size reads, never readline(): a child that writes without a newline cannot grow this buffer.
        assert proc.stderr is not None
        pending = b""
        total = 0
        while chunk := proc.stderr.read1(65536):
            total += len(chunk)
            if total > _STDERR_TOTAL_LIMIT:
                state["overflow"] = True
                return
            lines, pending = split_stderr(pending, chunk)
            for line in lines:
                note_line(line)

    def feed_stdin() -> None:
        assert proc.stdin is not None and stdin_data is not None
        try:
            proc.stdin.write(stdin_data)
        except OSError:  # the child exited or was killed first
            pass
        finally:
            with contextlib.suppress(OSError):
                proc.stdin.close()

    threads = [threading.Thread(target=read_stdout, daemon=True), threading.Thread(target=read_stderr, daemon=True)]
    if stdin_data is not None:
        threads.append(threading.Thread(target=feed_stdin, daemon=True))
    for t in threads:
        t.start()
    started = time.monotonic()
    timed_out = False
    rss_mb, next_look = get_settings().parse_child_rss_mb, started
    while True:
        try:
            proc.wait(timeout=0.1)
            break
        except subprocess.TimeoutExpired:
            if time.monotonic() >= next_look:   # the child and its Tesseract, resident, a few times a second
                next_look = time.monotonic() + _RSS_POLL_SECONDS
                if (used := parser_guard.over_budget(proc.pid, rss_mb)) is not None:
                    logger.warning("Parser child group used %d MB resident, over PARSE_CHILD_RSS_MB %d; killed: %s", used, rss_mb, label)
                    state["memory"] = True
                    _kill_group(proc)
                    break
            budget = timeout_s + ocr_extra_s * state["ocr"]
            if state["overflow"] or time.monotonic() - started > budget:
                timed_out = not state["overflow"]
                _kill_group(proc)
                break
    for t in threads:
        t.join(timeout=5)
    if state["overflow"]:
        return ChildOutcome("overflow")
    if timed_out:
        logger.warning("Parser child exceeded its budget and its group was killed: %s", label)
        return ChildOutcome("timeout")
    killed = os.name == "posix" and proc.returncode == -signal.SIGKILL   # the kernel's OOM killer, or a limit
    if state["memory"] or killed:
        logger.warning("Parser child ended by a memory limit (exit %s): %s", proc.returncode, label)
        return ChildOutcome("memory")
    if proc.returncode != 0 or not out:
        logger.warning("Parser worker failed (exit %s): %s", proc.returncode, err.decode("utf-8", "replace"))
        return ChildOutcome("failed")
    return ChildOutcome("ok", bytes(out))


def _from_payload(payload: dict[str, Any]) -> Any:
    from app.services.ocr_service import OCRResult, PageResult

    pages = [PageResult(**p) for p in payload.pop("page_results", [])]
    return OCRResult(page_results=pages, **payload)


# A parse is asked for twice per upload (text, then the attachment): the second asks the cache, not a new child.
_cache: OrderedDict[tuple[Any, ...], Any] = OrderedDict()
_cache_lock = threading.Lock()


def guarded_extract(file_path: str, force_ocr: bool = False) -> Any:
    """Size cap, then the parse in the child (or in this process only when isolation is off, or the file is absent)."""
    path = Path(file_path)
    if not path.exists():
        return parse_here(file_path, force_ocr)
    from app.config import get_settings

    s = get_settings()
    st = path.stat()
    limit = s.max_upload_size_mb * 1024 * 1024
    if st.st_size > limit:
        return refused(file_path, "pdf_too_large", size_mb=f"{st.st_size / 1024 / 1024:.1f}", limit_mb=s.max_upload_size_mb)
    if not ISOLATE_PARSER:
        return parse_here(file_path, force_ocr)
    key = (str(path.resolve()), st.st_size, st.st_mtime_ns, force_ocr, s.pdf_max_pages)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    result = _run_child(file_path, force_ocr)
    if result.strategy_used != "failed" or result.text.strip() or result.embedded_xml:
        with _cache_lock:
            _cache[key] = result
            while len(_cache) > 4:
                _cache.popitem(last=False)
    return result


_ATTACHMENT_NOTE = (
    "PDF'in eki okunamadı; metinden okundu",
    "The PDF's attachment could not be read; the data was read from the page text instead",
)
_ATTACHMENT_NOTE_PARTIAL = (
    "PDF'in bir eki okunamadı; öteki ekten okundu",
    "One attachment of the PDF could not be read; the data was read from another attachment",
)
_REASONS = {
    "unsupported_filter": ("desteklenmeyen sıkıştırma", "unsupported compression"),
    "too_large": ("boyut sınırı aşıldı", "over the size limit"),
    "unreadable": ("bozuk", "damaged"),
    "encrypted": ("şifreli", "encrypted"),
    "unsafe_xml": ("güvenli olmayan XML", "unsafe XML"),
}


def cached_result(file_path: str) -> Any | None:
    """The parse already made for this file, if any. Never starts a child (safe to call from async code)."""
    path = Path(file_path)
    if not path.exists():
        return None
    from app.config import get_settings

    st = path.stat()
    key = (str(path.resolve()), st.st_size, st.st_mtime_ns, False, get_settings().pdf_max_pages)
    with _cache_lock:
        return _cache.get(key)


def attachment_note(file_path: str) -> tuple[str, bool] | None:
    """(Turkish then English note, hold) when the PDF declared attachments that were not read; None when nothing
    was lost. `hold` is True only when an unread attachment is an e-Belge CANDIDATE (XML by name, MIME or
    content): a hold is for data integrity, an encrypted PDF or an unknown attachment gets the note alone."""
    result = cached_result(file_path)
    unread = (result.metadata or {}).get("attachments_unread") if result is not None else None
    if not unread:
        return None
    tr, en = (_ATTACHMENT_NOTE_PARTIAL if result.embedded_xml else _ATTACHMENT_NOTE)
    reasons = sorted({r["reason"] for r in unread})
    why_tr = ", ".join(_REASONS.get(r, (r, r))[0] for r in reasons)
    why_en = ", ".join(_REASONS.get(r, (r, r))[1] for r in reasons)
    return f"{tr} ({why_tr}). {en} ({why_en}).", any(r.get("candidate") for r in unread)


def pages_note(file_path: str) -> tuple[str, bool] | None:
    """(Turkish then English note, hold) for pages that yielded no text; the hold rule is `page_gap.note`."""
    from app.services import page_gap

    result = cached_result(file_path)
    return page_gap.note((result.metadata or {}) if result is not None else {})


def apply_pdf_notes(result: Any, file_path: str) -> None:
    """Put what the PDF read did not get on an ingestion result: an unread attachment, text-less pages. Held only
    where data is missing (an e-Belge candidate attachment, a page with evidence of lost rows). Never a silent fallback."""
    notes: list[str] = []
    hold = False
    for found in (attachment_note(file_path), pages_note(file_path)):
        if found:
            notes.append(found[0])
            hold = hold or found[1]
    if notes:
        result.detail = f"{result.detail or ''} [{' | '.join(notes)}]".strip()
        result.needs_review = bool(result.needs_review) or hold


# ── Child side ───────────────────────────────────────────────────────────────────────────────

def parse_here(file_path: str, force_ocr: bool = False) -> Any:
    """Parse in THIS process: text and OCR, then the e-Belge attachment. Runs in the child; in the parent
    only when isolation is off (tests) or the file does not exist."""
    from app.services import ocr_service, pdf_embedded

    result = ocr_service._extract_in_process(file_path, force_ocr)
    if "refusal" not in (result.metadata or {}) and Path(file_path).exists():
        scan = pdf_embedded.scan_attachments(file_path)
        result.embedded_xml = scan.found
        if scan.unread:
            result.metadata = {**(result.metadata or {}), "attachments_unread": scan.unread}
    return result


def report_peak() -> None:
    """Child side: write this process's peak address space, peak resident set and the largest descendant's
    resident set (Tesseract) to stderr, where the parent logs them. Linux only; silent elsewhere."""
    try:
        import resource

        peaks = {"VmPeak": 0, "VmHWM": 0}
        with open("/proc/self/status", encoding="ascii") as status:
            for line in status:
                key, _, value = line.partition(":")
                if key in peaks:
                    peaks[key] = int(value.split()[0])
        grandchild = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        sys.stderr.write(f"{_PEAK_MARK} {peaks['VmPeak']} {peaks['VmHWM']} {grandchild}" + chr(10))
    except (OSError, ImportError, ValueError):
        return


def _apply_limits(mem_mb: int, cpu_s: int) -> None:
    parser_guard.prefer_oom_victim()   # first, before any untrusted byte: the OOM killer takes the parser, not the API
    try:
        import resource
    except ImportError:  # Windows
        return
    for which, value in ((resource.RLIMIT_AS, mem_mb * 1024 * 1024), (resource.RLIMIT_CPU, cpu_s)):
        with contextlib.suppress(ValueError, OSError):
            resource.setrlimit(which, (value, value))


def _child_main(argv: list[str]) -> int:
    path, force, mem_mb, cpu_s, ocr_s, pages = argv[1], argv[2] == "1", *map(int, argv[3:7])
    _apply_limits(mem_mb, cpu_s)
    _child_limits.update(ocr_s=ocr_s, max_pages=pages)
    # A library may print to stdout (PyMuPDF's `fitz` import does); only the JSON below may reach it.
    try:
        with contextlib.redirect_stdout(sys.stderr):
            result = parse_here(path, force)
    except MemoryError:   # said, not swallowed: the parent turns this into the "memory limit" refusal
        sys.stderr.write(_MEM_MARK + chr(10))
        return 3
    report_peak()
    # json.dumps escapes to ASCII, so no console codepage can mangle the text.
    sys.stdout.write(json.dumps(asdict(result)))
    return 0


if __name__ == "__main__":
    # Run the canonical module, not this `__main__` copy: ocr_service reads the limits from the former.
    from app.services import pdf_isolation

    raise SystemExit(pdf_isolation._child_main(sys.argv))
