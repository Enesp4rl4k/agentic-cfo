"""Snapshot what the PDF parsers extract from a fixed synthetic corpus, to diff two library versions.

Use it when pdfminer.six, pdfplumber, PyMuPDF or Pillow is bumped (docs/ops/dependency-pinning.md):

    python scripts/pdf_extraction_snapshot.py gen     corpus/            # once; the same files for both runs
    python scripts/pdf_extraction_snapshot.py extract corpus/ old.json   # in the old environment
    python scripts/pdf_extraction_snapshot.py extract corpus/ new.json   # in the new environment
    diff old.json new.json                                               # empty = nothing moved

The corpus is generated (reportlab, PyMuPDF), never downloaded: grid and gridless bank statements with Turkish
text, an invoice, a sparse page that sends the pipeline to its pdfplumber strategy, rotated text, a TrueType
font with a ToUnicode CMap, and a predefined CJK CMap (the path pdfminer's CMap loader takes). A real statement
from a bank is still missing from the repo; this does not replace one.

For each file it records pdfplumber's text, tables and word boxes per page, and the result of the whole
`ocr_service` pipeline (text, strategy, confidence).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

DESCRIPTIONS = [
    "ESKİ MAHALLE ŞİRKETİ ÖĞÜT İŞ ÇÖZÜM",
    "KİRA ÖDEMESİ - ÇANKAYA ŞUBESİ",
    "HAVALE GELEN - ÜRÜN SATIŞI",
    "POS KOMİSYON KESİNTİSİ",
    "SGK PRİM ÖDEMESİ",
    "MAAŞ ÖDEMESİ ARALIK",
]


def _rows(n: int) -> list[list[str]]:
    rows = []
    balance = 125_000.0
    for i in range(n):
        amount = (i * 7919 % 9000) + 150.55
        sign = -1 if i % 3 else 1
        balance += sign * amount
        fmt = lambda v: f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")  # noqa: E731
        rows.append([f"{(i % 28) + 1:02d}.03.2026", DESCRIPTIONS[i % len(DESCRIPTIONS)], fmt(sign * amount), fmt(balance)])
    return rows


def _ttf() -> str | None:
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"):
        if Path(p).exists():
            return p
    return None


def generate(out: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

    out.mkdir(parents=True, exist_ok=True)
    ttf = _ttf()
    font = "Helvetica"
    if ttf:
        pdfmetrics.registerFont(TTFont("Corp", ttf))
        font = "Corp"

    # 1. grid statement, 3 pages
    doc = SimpleDocTemplate(str(out / "01_grid_statement.pdf"), pagesize=A4, invariant=True)
    table = Table([["Tarih", "Açıklama", "Tutar", "Bakiye"], *_rows(90)], repeatRows=1)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("FONT", (0, 0), (-1, -1), font, 8)]))
    doc.build([Paragraph("HESAP EKSTRESİ", getSampleStyleSheet()["Title"]), table])

    # 2. gridless statement: text columns only
    c = canvas.Canvas(str(out / "02_gridless_statement.pdf"), pagesize=A4, invariant=True)
    c.setFont(font, 8)
    y = 800
    for row in _rows(45):
        c.drawString(40, y, row[0])
        c.drawString(110, y, row[1])
        c.drawRightString(470, y, row[2])
        c.drawRightString(550, y, row[3])
        y -= 14
    c.save()

    # 3. invoice
    c = canvas.Canvas(str(out / "03_invoice.pdf"), pagesize=A4, invariant=True)
    c.setFont(font, 12)
    c.drawString(40, 800, "E-ARŞİV FATURA   Fatura No: ABC2026000001234   Tarih: 05.03.2026")
    c.setFont(font, 9)
    c.drawString(40, 780, "Satıcı VKN: 1234567890   Alıcı VKN: 0987654321")
    for i, (name, qty, price) in enumerate([("Danışmanlık hizmeti", 3, "1.500,00"), ("Yazılım lisansı", 1, "8.250,50")]):
        c.drawString(40, 740 - i * 16, name)
        c.drawRightString(380, 740 - i * 16, str(qty))
        c.drawRightString(480, 740 - i * 16, price)
    c.drawRightString(480, 680, "Ara Toplam: 12.750,50 TL")
    c.drawRightString(480, 664, "KDV (%20): 2.550,10 TL")
    c.drawRightString(480, 648, "Genel Toplam: 15.300,60 TL")
    c.save()

    # 4. sparse page (below the native-text threshold: the pipeline falls to pdfplumber, then OCR if installed)
    c = canvas.Canvas(str(out / "04_sparse.pdf"), pagesize=A4, invariant=True)
    c.setFont(font, 10)
    c.drawString(40, 800, "Toplam 1.250,00 TL")
    c.save()

    # 5. rotated text
    c = canvas.Canvas(str(out / "05_rotated.pdf"), pagesize=A4, invariant=True)
    c.setFont(font, 10)
    c.rotate(90)
    for i in range(12):
        c.drawString(40, -60 - i * 16, f"Satır {i} 12.345,67 TL gelen havale")
    c.save()

    # 6. predefined CJK CMap: pdfminer's CMap loader reads its packaged cmap data for this
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))
    c = canvas.Canvas(str(out / "06_cjk_cmap.pdf"), pagesize=A4, invariant=True)
    c.setFont("HeiseiMin-W3", 12)
    c.drawString(40, 800, "請求書 合計 15,300 円 " * 3)
    c.save()

    # 7. PyMuPDF text, multi page, mixed font sizes
    import pymupdf

    d = pymupdf.open()
    for p in range(3):
        page = d.new_page()
        y = 60
        for row in _rows(30):
            page.insert_text((40, y), "  ".join(row), fontsize=9 if p % 2 else 11)
            y += 22
    d.save(str(out / "07_pymupdf_text.pdf"))


def _round(v: float) -> float:
    return round(float(v), 1)


def extract(corpus: Path, target: Path) -> None:
    import importlib.metadata as md

    import pdfplumber

    from app.services import ocr_service

    snapshot: dict[str, object] = {}
    for pdf in sorted(corpus.glob("*.pdf")):
        entry: dict[str, object] = {}
        pages = []
        with pdfplumber.open(str(pdf)) as doc:
            for page in doc.pages:
                pages.append({
                    "text": page.extract_text() or "",
                    "tables": page.extract_tables(),
                    "words": [[w["text"], _round(w["x0"]), _round(w["top"])] for w in page.extract_words()],
                })
        entry["pdfplumber_pages"] = pages
        result = ocr_service._extract_in_process(str(pdf))
        entry["pipeline"] = {
            "strategy": result.strategy_used,
            "confidence": result.confidence,
            "page_count": result.page_count,
            "text": result.text,
            "per_page": [[p.strategy, p.confidence, p.has_tables] for p in result.page_results],
        }
        snapshot[pdf.name] = entry
    versions = {n: md.version(n) for n in ("pdfplumber", "pdfminer.six", "pillow", "pymupdf")}
    target.write_text(json.dumps({"files": snapshot}, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    # versions go to stdout, not into the file, so the two snapshots diff clean
    print(json.dumps(versions))


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "gen":
        generate(Path(sys.argv[2]))
    elif mode == "extract":
        extract(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        raise SystemExit(__doc__)
