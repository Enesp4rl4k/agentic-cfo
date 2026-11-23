"""Child process of `ocr_service.extract_text_from_pdf`: parses one PDF, prints the result as JSON.

Run as `python -m app.services.pdf_worker <path> <force_ocr 0|1>`. It exists so that the parsers
(PyMuPDF, pdfminer, Tesseract) read an untrusted file in a process the caller can kill and survive:
a crash, a hang or a memory blow-up ends this process, not the API worker.
"""
from __future__ import annotations

import contextlib
import json
import sys
from dataclasses import asdict


def main(argv: list[str]) -> int:
    from app.services.ocr_service import _extract_in_process

    # A library may print to stdout (PyMuPDF's `fitz` import does); only the JSON below may reach it.
    with contextlib.redirect_stdout(sys.stderr):
        result = _extract_in_process(argv[1], force_ocr=argv[2] == "1")
    # json.dumps escapes to ASCII, so no console codepage can mangle the text.
    sys.stdout.write(json.dumps(asdict(result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
