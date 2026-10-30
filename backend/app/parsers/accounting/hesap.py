"""Direction of a posting in an accounting export (Logo, Netsis, Mikro).

The account decides (app.core.tdhp). These parsers used to read 6xx as expense
and 7xx as revenue — the Tekdüzen Hesap Planı has 60x as sales and 7xx as cost
accounts — so a coded export came out with its direction guessed wrong.
"""
from __future__ import annotations

from app.core import tdhp


def hareket(debit: int, credit: int, account_code: str) -> tuple[str, int] | None:
    """(type, amount in kuruş); None for a transfer or closing posting, which is not read.

    A correction on an income-statement account keeps its negative sign. With
    no code, or one the map does not know, the side with the larger amount wins.
    """
    h = tdhp.hesap(account_code)
    if h is not None:
        return tdhp.hareket(h, debit, credit)
    net = credit - debit
    return ("income", net) if net > 0 else ("expense", -net)
