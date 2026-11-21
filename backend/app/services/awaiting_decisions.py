"""What waits for a person's decision, in the two queues that exist, presented together.

Two queues hold money out of every figure until someone answers, and they stay separate (their logic
is not merged):

  rows       extracted rows the system would not book alone (`held_transactions`, screen /bekleyen-kayitlar)
  documents  invoices that may repeat money already in the ledger (`held_documents`, screen /onay)

The radar shows them as one "kararınızı bekleyenler" block with two labelled lines and a link each; the
Monday briefing's closing note names both. This module only counts and words them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

ROWS_PATH = "/bekleyen-kayitlar"
DOCUMENTS_PATH = "/onay"


@dataclass(frozen=True)
class AwaitingLine:
    count: int
    text: str       # the sentence the radar's not-included list also carries: the screen may hide that copy
    path: str       # the frontend route where a person answers


@dataclass(frozen=True)
class AwaitingDecisions:
    rows: AwaitingLine | None
    documents: AwaitingLine | None


def rows_line(waiting: int) -> str:
    return f"{waiting} kayıt incelemenizi bekliyor"


def block(waiting_rows: int, held: Any | None, held_text: str) -> AwaitingDecisions | None:
    """The radar's block (`held` is its HeldDocuments, or None); None when neither queue has anything waiting."""
    rows = AwaitingLine(waiting_rows, rows_line(waiting_rows), ROWS_PATH) if waiting_rows else None
    documents = AwaitingLine(held.count, held_text, getattr(held, "review_path", DOCUMENTS_PATH)) if held else None
    return AwaitingDecisions(rows, documents) if rows or documents else None


def briefing_note(waiting_rows: int, documents_count: int, documents_already_said: bool) -> str:
    """The briefing's closing sentence: both queues, once. Documents are not repeated when the
    headline caveat (`monday_briefing.held_caveat`) already said them."""
    say_documents = documents_count and not documents_already_said
    if waiting_rows and say_documents:
        return (f" Not: {waiting_rows} kayıt incelemenizi bekliyor ve {documents_count} belge kararınızı bekliyor;"
                " bu rakamlara dahil değil.")
    if waiting_rows:
        return f" Not: {waiting_rows} kayıt incelemenizi bekliyor; bu rakamlara dahil değil."
    if say_documents:
        return f" Not: {documents_count} belge kararınızı bekliyor; radara dahil değil."
    return ""


async def closing_note(db: AsyncSession, org_id: str, radar: Any, documents_already_said: bool) -> str:
    from app.services.held_rows import pending_count

    held = getattr(radar, "held_documents", None)
    return briefing_note(await pending_count(db, org_id), held.count if held else 0, documents_already_said)
