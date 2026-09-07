"""QNB Finansbank statement parser."""
from __future__ import annotations

from app.parsers.banks._shapes import SingleSignedColumnParser


class QNBParser(SingleSignedColumnParser):
    bank_id = "qnb"
    bank_display_name = "QNB Finansbank"
    _MARKERS = [
        "QNB FİNANSBANK", "QNB FINANSBANK", "QNB", "Finansbank A.Ş.", "FINANSBANK",
    ]
