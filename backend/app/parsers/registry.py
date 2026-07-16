"""
Parser registry — auto-detects which bank parser to use.

Usage:
    statement = ParserRegistry.parse(text, file_path)

The registry tries each registered parser's can_parse() heuristic in order.
First match wins. Falls back to GenericParser (LLM-based) if nothing matches.
"""
from __future__ import annotations

import logging
from typing import Type

from app.parsers.base import BankParser, ParsedStatement

logger = logging.getLogger(__name__)

# Populated by register()
_REGISTRY: list[Type[BankParser]] = []


def register(cls: Type[BankParser]) -> Type[BankParser]:
    """Decorator — register a parser class."""
    _REGISTRY.append(cls)
    return cls


def _ensure_parsers_registered() -> None:
    """Import all bank parsers and register them if not already done."""
    if _REGISTRY:
        return  # already populated
    from app.parsers.banks.akbank import AkbankParser
    from app.parsers.banks.garanti import GarantiParser
    from app.parsers.banks.isbank import IsBankParser
    from app.parsers.banks.ziraat import ZiraatParser

    for cls in (AkbankParser, GarantiParser, IsBankParser, ZiraatParser):
        if cls not in _REGISTRY:
            _REGISTRY.append(cls)


class ParserRegistry:
    @staticmethod
    def detect(text: str) -> Type[BankParser] | None:
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

    @staticmethod
    def parse(text: str, file_path: str = "") -> ParsedStatement:
        """
        Auto-detect parser and parse the statement.
        Falls back to GenericParser if no bank matches.
        """
        # Import here to avoid circular imports
        from app.parsers.banks.generic import GenericParser

        parser_cls = ParserRegistry.detect(text)
        if parser_cls is None:
            logger.warning("No bank-specific parser matched — using GenericParser (LLM fallback)")
            parser_cls = GenericParser

        parser = parser_cls()
        return parser.parse(text, file_path)
