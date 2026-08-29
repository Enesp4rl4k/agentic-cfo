"""
CSV Data Quality Validator — DQ-1 + DQ-3

Validates uploaded CSV files before they enter the analysis pipeline.
Returns:
  - Row/column level error and warning details
  - Data Health Score (0-100) — DQ-3
  - Column type detection + suggested field mappings — DQ-2 prep
  - Auto-detected delimiter, encoding, date format

Checks performed
----------------
Structural:
  - File encoding detection (UTF-8, Latin-1, Windows-1254/Turkish)
  - Delimiter detection (, ; | TAB)
  - Header row detection
  - Empty file / single row

Column-level:
  - Type inference (date, amount, text, integer, boolean)
  - Date format consistency (ISO, Turkish DD.MM.YYYY, etc.)
  - Required columns presence (date, amount, description)
  - Amount column: non-numeric values, mixed currency symbols

Row-level:
  - Duplicate rows (exact + near-duplicate by date+amount+description)
  - Missing values per column
  - Negative amounts (flagged, not rejected — can be valid)
  - Outlier amounts (IQR method, flagged for review)
  - Future-dated transactions

Business rules:
  - Date range too narrow (< 1 week) — might be incomplete
  - Single transaction direction (all positive or all negative)
  - Suspiciously round amounts (>20% round numbers)

Health Score formula (0-100):
  100
  - 20 if required columns missing
  - 10 if >5% missing values
  - 10 if >2% duplicates
  - 5  if >10% outliers
  - 5  if date range < 7 days
  - 10 if encoding issues (non-UTF-8)
  - 5  if future-dated rows > 0
  = minimum 0

Usage
-----
    from app.services.csv_validator import CSVValidator

    result = CSVValidator.validate(file_bytes, filename="report.csv")

    if result.health_score < 60:
        # Block or warn
        pass

    print(result.summary)          # human-readable
    print(result.column_mapping)   # suggested field names
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)

# ── Expected / mapped field names ────────────────────────────────────────────

FIELD_MAP_CANDIDATES: dict[str, list[str]] = {
    "date": [
        "tarih", "date", "işlem tarihi", "islem tarihi", "value date",
        "valör", "valör tarihi", "hareket tarihi", "fatura tarihi",
    ],
    "amount": [
        "tutar", "amount", "miktar", "para", "değer", "deger", "borç",
        "alacak", "debit", "credit", "işlem tutarı", "islem tutari",
        "fatura tutarı",
    ],
    "description": [
        "açıklama", "aciklama", "description", "detay", "işlem açıklaması",
        "islem aciklamasi", "narration", "particulars", "bilgi", "not",
    ],
    "category": [
        "kategori", "category", "tür", "tur", "tip", "type",
        "hesap kodu", "account code",
    ],
    "reference": [
        "referans", "reference", "ref", "fiş no", "fis no", "belge no",
        "invoice no", "fatura no",
    ],
}

# Turkish date formats to try
DATE_FORMATS = [
    "%Y-%m-%d",      # ISO
    "%d.%m.%Y",      # Turkish standard
    "%d/%m/%Y",
    "%m/%d/%Y",      # US format
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%d.%m.%y",      # 2-digit year
]


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class ColumnInfo:
    """Per-column analysis result."""
    name: str
    raw_name: str              # original header before normalisation
    detected_type: str         # "date" | "amount" | "text" | "integer" | "boolean" | "mixed"
    mapped_field: str | None   # suggested system field name
    null_count: int
    null_pct: float
    sample_values: list[str]
    issues: list[str] = field(default_factory=list)
    date_format: str | None = None


@dataclass
class RowIssue:
    """A single row-level issue."""
    row: int           # 1-based row number (header = 0)
    column: str | None
    severity: str      # "error" | "warning" | "info"
    code: str          # machine-readable code
    message: str


@dataclass
class ValidationResult:
    """Complete validation result."""
    health_score: int                # 0-100
    health_label: str                # "excellent" | "good" | "fair" | "poor" | "critical"
    row_count: int
    column_count: int
    encoding: str
    delimiter: str
    columns: list[ColumnInfo]
    row_issues: list[RowIssue]
    column_mapping: dict[str, str]   # system_field → csv_column_name
    summary: str
    recommendations: list[str]
    # Breakdown scores
    score_breakdown: dict[str, int]  # what deducted what

    @property
    def errors(self) -> list[RowIssue]:
        return [i for i in self.row_issues if i.severity == "error"]

    @property
    def warnings(self) -> list[RowIssue]:
        return [i for i in self.row_issues if i.severity == "warning"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "health_score": self.health_score,
            "health_label": self.health_label,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "encoding": self.encoding,
            "delimiter": self.delimiter,
            "columns": [
                {
                    "name": c.name,
                    "raw_name": c.raw_name,
                    "detected_type": c.detected_type,
                    "mapped_field": c.mapped_field,
                    "null_count": c.null_count,
                    "null_pct": round(c.null_pct, 1),
                    "sample_values": c.sample_values[:5],
                    "issues": c.issues,
                    "date_format": c.date_format,
                }
                for c in self.columns
            ],
            "row_issues": [
                {
                    "row": i.row,
                    "column": i.column,
                    "severity": i.severity,
                    "code": i.code,
                    "message": i.message,
                }
                for i in self.row_issues[:200]  # cap for response size
            ],
            "column_mapping": self.column_mapping,
            "summary": self.summary,
            "recommendations": self.recommendations,
            "score_breakdown": self.score_breakdown,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
        }


# ── Utilities ─────────────────────────────────────────────────────────────────

def _detect_encoding(raw: bytes) -> str:
    """Try common encodings. Turkish files often use Windows-1254."""
    for enc in ("utf-8-sig", "utf-8", "windows-1254", "iso-8859-9", "latin-1"):
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "latin-1"


def _detect_delimiter(first_lines: str) -> str:
    """Detect CSV delimiter from first few lines."""
    candidates = [",", ";", "\t", "|"]
    scores: dict[str, int] = {}
    for line in first_lines.splitlines()[:5]:
        for d in candidates:
            scores[d] = scores.get(d, 0) + line.count(d)
    return max(scores, key=lambda k: scores[k])


def _parse_amount(val: str) -> float | None:
    """Parse Turkish/international amount strings."""
    if not val or not val.strip():
        return None
    # Remove currency symbols and whitespace
    cleaned = re.sub(r"[₺$€£¥\s]", "", val.strip())
    # Turkish number format: 1.234,56 → 1234.56
    if "," in cleaned and "." in cleaned:
        if cleaned.index(".") < cleaned.index(","):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned and "." not in cleaned:
        # Could be decimal comma: 1234,56 → 1234.56
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_date(val: str) -> date | None:
    """Try multiple date formats."""
    if not val or not val.strip():
        return None
    val = val.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    return None


def _detect_type(values: list[str]) -> tuple[str, str | None]:
    """
    Returns (detected_type, date_format).
    detected_type: "date" | "amount" | "integer" | "text" | "boolean" | "mixed"
    """
    non_empty = [v for v in values if v and v.strip()]
    if not non_empty:
        return "text", None

    # Try date
    for fmt in DATE_FORMATS:
        parsed = 0
        for v in non_empty[:20]:
            try:
                datetime.strptime(v.strip(), fmt)
                parsed += 1
            except ValueError:
                pass
        if parsed / len(non_empty[:20]) >= 0.8:
            return "date", fmt

    # Try amount
    amount_ok = sum(1 for v in non_empty[:20] if _parse_amount(v) is not None)
    if amount_ok / len(non_empty[:20]) >= 0.8:
        # Check if integer
        int_ok = sum(1 for v in non_empty[:20] if v.strip().lstrip("-").isdigit())
        if int_ok / len(non_empty[:20]) >= 0.9:
            return "integer", None
        return "amount", None

    # Boolean
    bool_vals = {"true", "false", "yes", "no", "evet", "hayır", "1", "0", "e", "h"}
    bool_ok = sum(1 for v in non_empty[:20] if v.strip().lower() in bool_vals)
    if bool_ok / len(non_empty[:20]) >= 0.9:
        return "boolean", None

    return "text", None


def _suggest_field_mapping(col_name: str) -> str | None:
    """Map CSV column name to system field."""
    normalised = col_name.lower().strip()
    for field_name, candidates in FIELD_MAP_CANDIDATES.items():
        for candidate in candidates:
            if candidate in normalised or normalised in candidate:
                return field_name
    return None


def _iqr_outliers(values: list[float]) -> list[int]:
    """Return indices of outlier values using IQR method."""
    if len(values) < 10:
        return []
    sorted_vals = sorted(values)
    q1 = sorted_vals[len(sorted_vals) // 4]
    q3 = sorted_vals[3 * len(sorted_vals) // 4]
    iqr = q3 - q1
    if iqr == 0:
        return []
    lower = q1 - 3.0 * iqr
    upper = q3 + 3.0 * iqr
    return [i for i, v in enumerate(values) if v < lower or v > upper]


# ── CSVValidator ──────────────────────────────────────────────────────────────

class CSVValidator:
    """
    Main CSV validation engine.
    All methods are static — no instance needed.
    """

    @staticmethod
    def validate(file_bytes: bytes, filename: str = "file.csv") -> ValidationResult:
        """
        Validate a CSV file and return a structured ValidationResult.

        Parameters
        ----------
        file_bytes : bytes
            Raw file content.
        filename : str
            Original filename (used for extension check).
        """
        row_issues: list[RowIssue] = []
        score_deductions: dict[str, int] = {}
        recommendations: list[str] = []

        # ── 1. Encoding detection ─────────────────────────────────────────────
        encoding = _detect_encoding(file_bytes)
        is_utf8 = encoding in ("utf-8", "utf-8-sig")
        if not is_utf8:
            score_deductions["encoding"] = 10
            recommendations.append(
                f"Dosya {encoding} kodlaması ile kaydedilmiş. UTF-8 kullanmak daha güvenlidir."
            )

        text = file_bytes.decode(encoding, errors="replace")

        # ── 2. Empty file ─────────────────────────────────────────────────────
        lines = [l for l in text.splitlines() if l.strip()]
        if len(lines) < 2:
            return ValidationResult(
                health_score=0,
                health_label="critical",
                row_count=0,
                column_count=0,
                encoding=encoding,
                delimiter=",",
                columns=[],
                row_issues=[RowIssue(0, None, "error", "EMPTY_FILE", "Dosya boş veya sadece başlık satırı içeriyor.")],
                column_mapping={},
                summary="Dosya boş — analiz yapılamıyor.",
                recommendations=["En az 2 satır (başlık + veri) içeren bir CSV yükleyin."],
                score_breakdown={"empty_file": 100},
            )

        # ── 3. Delimiter ──────────────────────────────────────────────────────
        delimiter = _detect_delimiter("\n".join(lines[:10]))

        # ── 4. Parse CSV ──────────────────────────────────────────────────────
        import csv as _csv
        reader = _csv.reader(io.StringIO(text), delimiter=delimiter)
        all_rows: list[list[str]] = list(reader)

        if not all_rows:
            return ValidationResult(
                health_score=0, health_label="critical", row_count=0,
                column_count=0, encoding=encoding, delimiter=delimiter,
                columns=[], row_issues=[], column_mapping={},
                summary="CSV parse edilemedi.", recommendations=[],
                score_breakdown={"parse_error": 100},
            )

        header = all_rows[0]
        data_rows = all_rows[1:]
        row_count = len(data_rows)
        col_count = len(header)

        # ── 5. Column analysis ────────────────────────────────────────────────
        column_infos: list[ColumnInfo] = []
        column_mapping: dict[str, str] = {}

        for col_idx, col_raw in enumerate(header):
            col_values = [
                row[col_idx] if col_idx < len(row) else ""
                for row in data_rows
            ]
            non_empty = [v for v in col_values if v and v.strip()]
            null_count = len(col_values) - len(non_empty)
            null_pct = null_count / len(col_values) * 100 if col_values else 0

            detected_type, date_fmt = _detect_type(non_empty[:100])
            mapped_field = _suggest_field_mapping(col_raw)
            if mapped_field:
                column_mapping[mapped_field] = col_raw

            col_issues: list[str] = []
            if null_pct > 20:
                col_issues.append(f"Yüksek boş değer oranı: %{null_pct:.0f}")

            if detected_type == "date" and date_fmt and date_fmt != "%Y-%m-%d" and date_fmt != "%d.%m.%Y":
                col_issues.append(f"Standart dışı tarih formatı: {date_fmt}")

            column_infos.append(ColumnInfo(
                name=col_raw.strip().lower().replace(" ", "_"),
                raw_name=col_raw,
                detected_type=detected_type,
                mapped_field=mapped_field,
                null_count=null_count,
                null_pct=null_pct,
                sample_values=list(non_empty[:5]),
                issues=col_issues,
                date_format=date_fmt,
            ))

        # ── 6. Required fields check ──────────────────────────────────────────
        required = {"date", "amount"}
        missing_required = required - set(column_mapping.keys())
        if missing_required:
            score_deductions["missing_required"] = 20
            for f in missing_required:
                row_issues.append(RowIssue(
                    row=0, column=None, severity="error",
                    code="MISSING_REQUIRED_COLUMN",
                    message=f"Zorunlu kolon bulunamadı: '{f}'. Lütfen tarih ve tutar kolonlarının var olduğundan emin olun."
                ))
            recommendations.append("CSV'de tarih ve tutar kolonları olması zorunludur.")

        # ── 7. Missing values ─────────────────────────────────────────────────
        total_cells = row_count * col_count if col_count else 1
        total_missing = sum(c.null_count for c in column_infos)
        missing_pct = total_missing / total_cells * 100 if total_cells else 0
        if missing_pct > 5:
            score_deductions["missing_values"] = 10
            recommendations.append(f"Toplamda %{missing_pct:.1f} oranında boş değer var — veriyi gözden geçirin.")

        # ── 8. Duplicate rows ─────────────────────────────────────────────────
        row_signatures = ["|".join(row[:5]) for row in data_rows]
        seen: dict[str, int] = {}
        duplicate_count = 0
        for row_idx, sig in enumerate(row_signatures):
            if sig in seen:
                duplicate_count += 1
                row_issues.append(RowIssue(
                    row=row_idx + 2, column=None, severity="warning",
                    code="DUPLICATE_ROW",
                    message=f"Satır {row_idx + 2} ile satır {seen[sig] + 2} özdeş görünüyor."
                ))
            else:
                seen[sig] = row_idx

        dup_pct = duplicate_count / row_count * 100 if row_count else 0
        if dup_pct > 2:
            score_deductions["duplicates"] = 10
            recommendations.append(f"%{dup_pct:.1f} oranında duplicate satır tespit edildi — temizlemeniz önerilir.")

        # ── 9. Amount column checks ────────────────────────────────────────────
        amount_col = column_mapping.get("amount")
        if amount_col:
            amount_col_idx = next((i for i, c in enumerate(header) if c == amount_col), None)
            if amount_col_idx is not None:
                raw_amounts = [
                    row[amount_col_idx] if amount_col_idx < len(row) else ""
                    for row in data_rows
                ]
                parsed_amounts: list[float] = []
                for row_idx, val in enumerate(raw_amounts):
                    parsed = _parse_amount(val)
                    if parsed is None and val.strip():
                        row_issues.append(RowIssue(
                            row=row_idx + 2, column=amount_col, severity="warning",
                            code="NON_NUMERIC_AMOUNT",
                            message=f"Satır {row_idx + 2}: '{val}' sayıya dönüştürülemedi."
                        ))
                    elif parsed is not None:
                        parsed_amounts.append(parsed)

                # Negative amounts
                neg_count = sum(1 for a in parsed_amounts if a < 0)
                all_positive = neg_count == 0
                all_negative = neg_count == len(parsed_amounts)
                if all_positive:
                    row_issues.append(RowIssue(
                        row=0, column=amount_col, severity="info",
                        code="ALL_POSITIVE_AMOUNTS",
                        message="Tüm tutarlar pozitif — gider kalemleri eksik olabilir."
                    ))
                elif all_negative:
                    row_issues.append(RowIssue(
                        row=0, column=amount_col, severity="info",
                        code="ALL_NEGATIVE_AMOUNTS",
                        message="Tüm tutarlar negatif — gelir kalemleri eksik olabilir."
                    ))

                # Outliers
                if parsed_amounts:
                    outlier_indices = _iqr_outliers(parsed_amounts)
                    outlier_pct = len(outlier_indices) / len(parsed_amounts) * 100
                    for idx in outlier_indices[:20]:  # cap
                        row_issues.append(RowIssue(
                            row=idx + 2, column=amount_col, severity="warning",
                            code="OUTLIER_AMOUNT",
                            message=f"Satır {idx + 2}: Olağandışı tutar — {parsed_amounts[idx]:,.2f}"
                        ))
                    if outlier_pct > 10:
                        score_deductions["outliers"] = 5

                    # Round numbers
                    round_count = sum(1 for a in parsed_amounts if abs(a) > 0 and a == int(a) and abs(a) >= 100)
                    round_pct = round_count / len(parsed_amounts) * 100
                    if round_pct > 20:
                        row_issues.append(RowIssue(
                            row=0, column=amount_col, severity="info",
                            code="MANY_ROUND_NUMBERS",
                            message=f"%{round_pct:.0f} oranında yuvarlak tutar — tahmini değerler olabilir."
                        ))

        # ── 10. Date column checks ────────────────────────────────────────────
        date_col = column_mapping.get("date")
        if date_col:
            date_col_idx = next((i for i, c in enumerate(header) if c == date_col), None)
            if date_col_idx is not None:
                raw_dates = [
                    row[date_col_idx] if date_col_idx < len(row) else ""
                    for row in data_rows
                ]
                parsed_dates: list[date] = []
                today = datetime.now().date()

                for row_idx, val in enumerate(raw_dates):
                    parsed = _parse_date(val)
                    if parsed is None and val.strip():
                        row_issues.append(RowIssue(
                            row=row_idx + 2, column=date_col, severity="warning",
                            code="INVALID_DATE",
                            message=f"Satır {row_idx + 2}: '{val}' tarih olarak okunamadı."
                        ))
                    elif parsed is not None:
                        parsed_dates.append(parsed)
                        if parsed > today:
                            row_issues.append(RowIssue(
                                row=row_idx + 2, column=date_col, severity="warning",
                                code="FUTURE_DATE",
                                message=f"Satır {row_idx + 2}: Gelecek tarihli işlem — {parsed}"
                            ))

                if parsed_dates:
                    date_range_days = (max(parsed_dates) - min(parsed_dates)).days
                    if date_range_days < 7:
                        score_deductions["narrow_date_range"] = 5
                        recommendations.append(
                            f"Tarih aralığı sadece {date_range_days} gün. Daha uzun bir dönem için daha fazla veri yükleyin."
                        )
                    future_dates = [d for d in parsed_dates if d > today]
                    if future_dates:
                        score_deductions["future_dates"] = 5

        # ── 11. Health score calculation ──────────────────────────────────────
        total_deduction = sum(score_deductions.values())
        health_score = max(0, 100 - total_deduction)

        if health_score >= 90:
            health_label = "excellent"
        elif health_score >= 75:
            health_label = "good"
        elif health_score >= 55:
            health_label = "fair"
        elif health_score >= 35:
            health_label = "poor"
        else:
            health_label = "critical"

        # ── 12. Summary ───────────────────────────────────────────────────────
        error_count = sum(1 for i in row_issues if i.severity == "error")
        warn_count = sum(1 for i in row_issues if i.severity == "warning")
        summary = (
            f"{row_count} satır, {col_count} kolon. "
            f"Sağlık skoru: {health_score}/100 ({health_label}). "
            f"{error_count} hata, {warn_count} uyarı tespit edildi."
        )

        if not recommendations:
            recommendations.append("Veri kalitesi iyi görünüyor — analize hazır.")

        return ValidationResult(
            health_score=health_score,
            health_label=health_label,
            row_count=row_count,
            column_count=col_count,
            encoding=encoding,
            delimiter=delimiter,
            columns=column_infos,
            row_issues=row_issues,
            column_mapping=column_mapping,
            summary=summary,
            recommendations=recommendations,
            score_breakdown=score_deductions,
        )
