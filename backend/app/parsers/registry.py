"""
Parser registry — auto-detects which bank parser to use.

Usage (the upload entry point, `app.agents.data_ingestion._belgeyi_oku`):
    parser_cls = ParserRegistry.detect(text)

The registry tries each registered parser's can_parse() heuristic in order.
First match wins; None when nothing matches, and the caller falls through to the table
reader (`app.services.ingest.rows`) and the LLM extraction in data_ingestion. There is no
generic parser here: a second CSV/LLM implementation was reachable from nothing, and its
direction logic never ran.
"""
from __future__ import annotations

import logging

from app.parsers.base import BankParser

logger = logging.getLogger(__name__)

# Populated by register()
_REGISTRY: list[type[BankParser]] = []


def register(cls: type[BankParser]) -> type[BankParser]:
    """Decorator — register a parser class."""
    _REGISTRY.append(cls)
    return cls


def _ensure_parsers_registered() -> None:
    """Import all parsers (bank + accounting) and register them if not already done."""
    if _REGISTRY:
        return  # already populated

    # ── Bank statement parsers ────────────────────────────────────────────────
    # ── Accounting software parsers ───────────────────────────────────────────
    from app.parsers.accounting.logo_tiger import LogoTigerParser
    from app.parsers.accounting.mikro import MikroParser
    from app.parsers.accounting.netsis import NetsisParser
    from app.parsers.accounting.parasut import ParasutParser
    from app.parsers.banks.akbank import AkbankParser
    from app.parsers.banks.enpara import EnparaParser
    from app.parsers.banks.garanti import GarantiParser
    from app.parsers.banks.isbank import IsBankParser
    from app.parsers.banks.qnb import QNBParser
    from app.parsers.banks.yapkredi import YapiKrediParser
    from app.parsers.banks.ziraat import ZiraatParser

    # ── Invoice parsers ───────────────────────────────────────────────────────
    from app.parsers.invoice import InvoiceBatchParser, TurkishInvoiceParser

    all_parsers = (
        # Invoice batch first — most specific
        InvoiceBatchParser,
        # Bank parsers before accounting ones: a bank's name is a strong marker,
        # while the accounting markers ("BORÇ", "ALACAK", "Hesap Hareketleri",
        # "GİRİŞ") appear on bank statements too and used to claim them.
        AkbankParser,
        EnparaParser,
        GarantiParser,
        IsBankParser,
        QNBParser,
        YapiKrediParser,
        ZiraatParser,
        # Accounting parsers
        LogoTigerParser,
        NetsisParser,
        MikroParser,
        ParasutParser,
        # Single invoice parser — last (avoid false positives)
        TurkishInvoiceParser,
    )

    for cls in all_parsers:
        if cls not in _REGISTRY:
            _REGISTRY.append(cls)


class ParserRegistry:
    @staticmethod
    def detect(text: str) -> type[BankParser] | None:
        """Return the first parser class whose can_parse() returns True."""
        _ensure_parsers_registered()
        for parser_cls in _REGISTRY:
            try:
                if parser_cls.can_parse(text):
                    logger.info("Detected bank: %s", parser_cls.bank_display_name)
                    return parser_cls
            except Exception:
                continue
        return None
