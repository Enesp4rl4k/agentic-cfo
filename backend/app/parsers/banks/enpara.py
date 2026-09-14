"""Enpara.com statement parser."""
from __future__ import annotations

from app.parsers.banks._shapes import SingleSignedColumnParser


class EnparaParser(SingleSignedColumnParser):
    bank_id = "enpara"
    bank_display_name = "Enpara.com"
    _MARKERS = ["ENPARA.COM", "Enpara.com", "ENPARA", "Enpara"]
