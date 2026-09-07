"""Yapı Kredi statement parser."""
from __future__ import annotations

from app.parsers.banks._shapes import SingleSignedColumnParser


class YapiKrediParser(SingleSignedColumnParser):
    bank_id = "yapkredi"
    bank_display_name = "Yapı ve Kredi Bankası"
    _MARKERS = ["YAPI VE KREDİ", "YAPI KREDİ", "Yapi Kredi", "YapiKredi", "YKB"]
