"""Read a spreadsheet the way it was exported, not the way a parser would like it.

Exports are not clean tables. A bank's Excel starts with the account holder,
IBAN and period before the header; a Turkish CSV is separated by ";" and
written in Windows-1254; the last row is "TOPLAM". This module finds the table
inside: the delimiter, the header row, the data rows.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.core.turkish import fold

_MAX_BASLIK_ARAMA = 25          # a header is never further down than this
_TOPLAM = ("toplam", "genel toplam", "total", "grand total", "ara toplam")


class OkunamayanDosya(ValueError):
    """The file is not a table this module can read; the message is for the person."""


@dataclass
class Tablo:
    basliklar: list[str]
    satirlar: list[list[Any]]
    sayfa: str | None = None
    baslik_satiri: int = 0          # 0-based row of the header in the original


def anahtar(baslik: str) -> str:
    """A header as compared: folded, units and punctuation removed, spaces collapsed.

    "Brüt Maaş (TL)" → "brut maas", "İşlem_Tarihi" → "islem tarihi".
    """
    s = fold(str(baslik))
    s = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", s)      # (TL), [adet]
    s = re.sub(r"[₺$€%#*:]", " ", s)
    s = re.sub(r"[_\-./\\]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _metin_coz(veri: bytes) -> str:
    for enc in ("utf-8-sig", "cp1254"):
        try:
            return veri.decode(enc)
        except UnicodeDecodeError:
            continue
    return veri.decode("latin-1")


def _ayirici(metin: str) -> str:
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


def satirlari_oku(veri: bytes, uzanti: str) -> list[tuple[str | None, list[list[Any]]]]:
    """Every sheet's rows, as (sheet name, rows). CSV is a single unnamed sheet."""
    uzanti = uzanti.lower().lstrip(".")
    if uzanti == "xls":
        raise OkunamayanDosya(
            "Bu eski Excel biçimi (.xls) okunamıyor. Dosyayı Excel'de açıp "
            "'Farklı Kaydet → Excel Çalışma Kitabı (.xlsx)' ile kaydedip tekrar yükleyin."
        )
    if uzanti == "xlsx":
        import openpyxl

        try:
            wb = openpyxl.load_workbook(io.BytesIO(veri), read_only=True, data_only=True)
        except Exception as exc:
            raise OkunamayanDosya("Excel dosyası açılamadı; bozuk ya da parola korumalı olabilir.") from exc
        try:
            out = []
            for ws in wb.worksheets:
                rows = [list(r) for r in ws.iter_rows(values_only=True)]
                out.append((ws.title, rows))
            return out
        finally:
            wb.close()
    if uzanti in ("csv", "txt"):
        metin = _metin_coz(veri)
        reader = csv.reader(io.StringIO(metin), delimiter=_ayirici(metin))
        return [(None, [list(r) for r in reader])]
    raise OkunamayanDosya(f".{uzanti} bir tablo dosyası değil.")


def bos(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def tabloyu_bul(rows: list[list[Any]], bilinen: set[str], sayfa: str | None = None) -> Tablo | None:
    """The header row is the one naming the most known columns, among the first rows.

    Returns None when no row names at least two known columns — then this is
    not a table any schema describes, and nothing is guessed.
    """
    best_i, best_n = -1, 1
    for i, row in enumerate(rows[:_MAX_BASLIK_ARAMA]):
        n = sum(1 for c in row if not bos(c) and anahtar(str(c)) in bilinen)
        if n > best_n:
            best_i, best_n = i, n
    if best_i < 0:
        return None
    header = ["" if bos(c) else str(c).strip() for c in rows[best_i]]
    while header and not header[-1]:
        header.pop()
    width = len(header)
    data: list[list[Any]] = []
    for row in rows[best_i + 1:]:
        row = (list(row) + [None] * width)[:width]
        dolu = [c for c in row if not bos(c)]
        if not dolu:
            continue
        # Totals and sums at the foot of an export are not records.
        if isinstance(dolu[0], str) and anahtar(dolu[0]).startswith(_TOPLAM):
            continue
        data.append(row)
    return Tablo(basliklar=header, satirlar=data, sayfa=sayfa, baslik_satiri=best_i)


# ── Values ──────────────────────────────────────────────────────────────────

def sayi(v: Any) -> float | None:
    """A number as written in Turkish or English: "45.000,00", "1,234.5", "%12", "(1.500)"."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if bos(v):
        return None
    t = str(v).strip()
    negatif = t.startswith("-") or t.endswith("-") or (t.startswith("(") and t.endswith(")"))
    s = re.sub(r"[^\d,.]", "", t)
    if not s or not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        # "1,500" is fifteen hundred; "12,5" is twelve and a half.
        s = s.replace(",", "") if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3) else s.replace(",", ".")
    elif s.count(".") > 1 or (s.count(".") == 1 and len(s.split(".")[1]) == 3 and len(s.split(".")[0]) <= 3
                              and not isinstance(v, float)):
        # "45.000" in a Turkish export is forty-five thousand.
        s = s.replace(".", "")
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if negatif else n


_TARIH_BICIMLERI = ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y/%m/%d", "%d.%m.%y",
                    "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                    "%d/%m/%Y %H:%M", "%Y-%m")


def tarih(v: Any) -> str | None:
    """ISO date (or date-time when a time was given). Day first, as Turkish dates are written."""
    if isinstance(v, datetime):
        return v.isoformat() if (v.hour or v.minute or v.second) else v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if bos(v):
        return None
    t = str(v).strip()
    for fmt in _TARIH_BICIMLERI:
        try:
            d = datetime.strptime(t, fmt)
        except ValueError:
            continue
        return d.isoformat() if (d.hour or d.minute) else d.date().isoformat()
    return None
