"""Measure what a PDF parser child really uses (Linux): peak address space (VmPeak) and resident set (VmHWM).

Used by `test_parser_memory_measure.py` (CI) and runnable by hand:
    PYTHONPATH=. python tests/parser_memory_probe.py text 300
    PYTHONPATH=. python tests/parser_memory_probe.py scan 10
    PYTHONPATH=. python tests/parser_memory_probe.py sparse 300   # pages thin enough to go through pdfplumber

The PDFs are generated here with PyMuPDF (benign): a statement-like text document with ruled tables, and a
scanned-style document (full-colour page images, no text layer) that has to go through Tesseract at the
product's OCR DPI. The child is started exactly as `pdf_isolation` starts it (environment whitelist, own
session) but with generous limits, so the numbers are what it NEEDS, not what it was allowed.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROW_TEXT = ("HAVALE GELEN ODEME", "EFT GIDEN KIRA ODEMESI", "POS KOMISYON KESINTISI", "FATURA ODEMESI ELEKTRIK", "MAAS ODEMESI PERSONEL")


def statement_pdf(path: Path, pages: int, rows: int = 42) -> Path:
    """A statement-like document: a ruled table of date / description / debit / credit / balance on every page."""
    import pymupdf

    doc = pymupdf.open()
    cols = (40, 110, 330, 410, 490, 560)
    for n in range(pages):
        page = doc.new_page()
        shape = page.new_shape()   # one content stream per page, not one per cell (a real statement is not 60 000 streams)
        shape.insert_text((40, 40), f"HESAP EKSTRESI sayfa {n + 1} / {pages}   IBAN TR00 0000 0000 0000 0000 0000 00", fontsize=9)
        top, step = 60, 17
        for r in range(rows + 1):
            shape.draw_line((cols[0], top + r * step), (cols[-1], top + r * step))
        for c in cols:
            shape.draw_line((c, top), (c, top + rows * step))
        shape.finish(width=0.4)
        for r in range(rows):
            y = top + r * step + 12
            k = n * rows + r
            cells = (f"{1 + k % 28:02d}.{1 + (k // 28) % 12:02d}.2026", f"{ROW_TEXT[k % 5]} REF{k:07d}", f"{(k * 37) % 9000 + 10:,}.00",
                     f"{(k * 53) % 7000:,}.00", f"{100000 + k * 11:,}.00")
            for c, text in zip(cols, cells, strict=False):
                shape.insert_text((c + 3, y), text, fontsize=7.5)
        shape.commit()
    doc.save(str(path), deflate=True)   # compressed, as a real statement is: 300 pages stay under the 10 MB upload cap
    doc.close()
    return path


def scanned_pdf(path: Path, pages: int, dpi: int = 300) -> Path:
    """Full-colour A4 page images without a text layer: each page is OCR work at `dpi` (the product renders at 300)."""
    import pymupdf

    src = statement_pdf(path.with_suffix(".src.pdf"), 1, rows=38)
    pix = pymupdf.open(str(src))[0].get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB)
    jpeg = pix.tobytes("jpeg")
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page(width=595, height=842).insert_image(pymupdf.Rect(0, 0, 595, 842), stream=jpeg)
    doc.save(str(path))
    doc.close()
    src.unlink()
    return path


def _status_kb(pid: int) -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        with open(f"/proc/{pid}/status", encoding="ascii") as handle:
            for line in handle:
                key, _, value = line.partition(":")
                if key in ("VmPeak", "VmHWM", "Name"):
                    out[key] = value.strip() if key == "Name" else int(value.split()[0])
    except OSError:
        pass
    return out


def _descendants(root: int) -> list[int]:
    children: dict[int, list[int]] = {}
    for entry in os.listdir("/proc"):
        if entry.isdigit():
            try:
                with open(f"/proc/{entry}/stat", encoding="ascii") as handle:
                    ppid = int(handle.read().rsplit(")", 1)[1].split()[1])
            except (OSError, ValueError, IndexError):
                continue
            children.setdefault(ppid, []).append(int(entry))
    found, todo = [], [root]
    while todo:
        for child in children.get(todo.pop(), []):
            found.append(child)
            todo.append(child)
    return found


def measure(pdf: Path, *, force_ocr: bool = False, mem_mb: int = 16384, timeout_s: int = 1500) -> dict[str, object]:
    """Run the child on `pdf`; return its own peaks, the largest descendant's peaks (sampled) and the outcome."""
    from app.services.pdf_isolation import _WORKER_ENV_KEEP

    env = {k: v for k, v in os.environ.items() if k in _WORKER_ENV_KEEP}
    env["PYTHONPATH"] = os.pathsep.join([str(BACKEND), os.environ.get("PYTHONPATH", "")]).strip(os.pathsep)
    cmd = [sys.executable, "-m", "app.services.pdf_isolation", str(pdf), "1" if force_ocr else "0", str(mem_mb), str(timeout_s * 2), "60", "500"]
    started = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(BACKEND), env=env, start_new_session=True)
    seen: dict[str, dict[str, int]] = {}
    stop = threading.Event()

    def sample() -> None:
        while not stop.is_set():
            for pid in _descendants(proc.pid):
                status = _status_kb(pid)
                name = str(status.get("Name", "?"))
                best = seen.setdefault(name, {"VmPeak": 0, "VmHWM": 0})
                for key in ("VmPeak", "VmHWM"):
                    best[key] = max(best[key], int(status.get(key, 0)))
            time.sleep(0.05)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    try:
        out, err = proc.communicate(timeout=timeout_s)
    finally:
        stop.set()
        sampler.join(timeout=5)
    peak = [line for line in err.decode("utf-8", "replace").splitlines() if line.startswith("@@PEAK@@")]
    vmpeak, vmhwm, grandchild_rss = (int(x) for x in peak[-1].split()[1:4]) if peak else (0, 0, 0)
    return {
        "exit": proc.returncode, "seconds": round(time.monotonic() - started, 1), "stdout_bytes": len(out),
        "child_vmpeak_mb": vmpeak // 1024, "child_vmhwm_mb": vmhwm // 1024, "descendant_rss_mb": grandchild_rss // 1024,
        "descendants": {n: {k: v // 1024 for k, v in d.items()} for n, d in seen.items()},
        "stderr_tail": err.decode("utf-8", "replace")[-400:],
    }


if __name__ == "__main__":
    import tempfile

    kind, count = sys.argv[1], int(sys.argv[2])
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{kind}.pdf"
        target = scanned_pdf(path, count) if kind == "scan" else statement_pdf(path, count, rows=2 if kind == "sparse" else 42)
        print(kind, count, "pages, file", target.stat().st_size // 1024, "KB")
        print(measure(target))
