"""Accounting software parsers — Logo Tiger, Netsis, Mikro, Paraşüt."""
from app.parsers.accounting.logo_tiger import LogoTigerParser
from app.parsers.accounting.netsis import NetsisParser
from app.parsers.accounting.mikro import MikroParser
from app.parsers.accounting.parasut import ParasutParser

__all__ = ["LogoTigerParser", "NetsisParser", "MikroParser", "ParasutParser"]
