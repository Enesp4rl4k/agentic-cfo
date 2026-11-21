"""The one door a text statement walks through, whoever the caller is.

RULE B. Every caller that turns a text file or feed into rows (the upload pipeline, the Logo and Mikro ERP
connectors, anything added later) calls `read_text_statement` and nothing else: the parser's own `parse` is never
called outside this module (tests/test_text_lines_invariant.py checks that). That gives every caller the same
things, so none of them can drop a row quietly:

  - every physical line is accounted for (`app.parsers.lines`): a line that may carry money and that no pattern
    took is HELD with its raw text, a row with a number the pattern did not account for is held ("tutar belirsiz");
  - the counts (`ReadLedger`) and the reconcile invariant (`okuma.reconcile`), so a caller can say "N satır
    hesaba katılamadı" instead of "success";
  - rows in the pipeline's own shape, with an unknown direction as None (held), never a default.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.parsers.base import BankParser, ParsedStatement
from app.parsers.lines import account_for_lines
from app.services.ingest.okuma import ReadLedger, reconcile
from app.services.ingest.rows import _pdf_yonu, _statement_to_transactions


@dataclass
class DoorRead:
    statement: ParsedStatement
    rows: list[dict[str, Any]]            # the pipeline's rows, aligned 1:1 with `statement.transactions`
    ledger: ReadLedger
    balance_check: str

    @property
    def unaccounted(self) -> int:
        """Rows the readers lost (0 when the invariant holds); the hold step is the caller's."""
        _, lost = reconcile(self.ledger.as_dict(), len(self.rows), 0)
        return lost

    @property
    def flagged(self) -> int:
        """Rows that will wait for a person for what the reader itself found wrong with them."""
        keys = ("line_unreadable", "amount_uncertain", "zero_amount")
        return sum(1 for r in self.rows if any(r.get(k) for k in keys) or not r.get("type") or r.get("transaction_date") is None)


def read_text_statement(
    parser: BankParser, text: str, file_path: str = "", *, bank_name: str | None = None, ambiguous: bool = False,
) -> DoorRead:
    """Parse `text` with `parser` and account for every line of it."""
    statement = parser.parse(text, file_path)
    account = account_for_lines(text, statement.transactions)
    statement.transactions = account.transactions
    ledger = ReadLedger()
    ledger.absorb(account)
    rows = _statement_to_transactions(statement)
    ledger.emitted = len(rows)
    ledger.balance_check = _pdf_yonu(rows, bank_name or parser.bank_display_name, text, ambiguous)
    return DoorRead(statement, rows, ledger, ledger.balance_check or "unverified")


def read_document(parser: BankParser, text: str, file_path: str = "", *, ambiguous: bool = False) -> DoorRead:
    """A single document (an invoice) is not a statement of lines: parsed and converted, no line accounting."""
    statement = parser.parse(text, file_path)
    rows = _statement_to_transactions(statement)
    status = _pdf_yonu(rows, parser.bank_display_name, text, ambiguous)
    return DoorRead(statement, rows, ReadLedger(), status)


def connector_rows(door: DoorRead, source: str) -> list[dict[str, Any]]:
    """The door's rows in the shape a connector hands to `ekle.islemleri_ekle`.

    Nothing is dropped and nothing is defaulted: an unknown direction is None, an unreadable date is None, an
    amount the reader could not stand behind is None and the raw line stands in for the description, so the row
    reaches /bekleyen-kayitlar with what the file said.
    """
    out: list[dict[str, Any]] = []
    for tx, row in zip(door.statement.transactions, door.rows, strict=True):
        unsure = bool(row.get("line_unreadable") or row.get("amount_uncertain"))
        out.append({
            "date": row.get("transaction_date"),
            "amount_cents": None if unsure or row.get("zero_amount") else row["amount_cents"],
            "type": row.get("type"),
            "description": (tx.raw_row if unsure else row["description"]) or "",
            "category": row.get("category"),
            "account_code": row.get("account_code"),
            "source": source,
            "reference": tx.reference or "",
        })
    return out


def sync_outcome(door: DoorRead) -> dict[str, Any]:
    """What a connector reports for a text pull: the counts, and whether it may say "success"."""
    counts, lost = reconcile(door.ledger.as_dict(), len(door.rows), 0)
    return {
        "ok": lost == 0, "status": "needs_review" if lost else "success", "unaccounted": lost,
        "held_candidates": door.flagged, "counts": counts,
        "skipped": door.ledger.summary_skipped + door.ledger.account_skipped,
    }
