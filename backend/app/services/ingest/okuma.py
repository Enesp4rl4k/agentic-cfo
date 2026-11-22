"""Every row the reader was handed is accounted for: booked, held, or skipped AND counted.

The invariant, computed by the ingest step itself and stored in `ingest.summary`:

    read == emitted + summary_skipped + account_skipped + blank + header_repeats      (the readers)
    emitted == accepted + held                                                         (the hold step)

`read` is what the table (or the raw CSV, or a bank's PDF text) handed over as data rows. Every way a
row can leave the readers has a named bucket here; there is no other exit. If the equation does not hold
the upload is marked for review: "N satır hesaba katılamadı". Nothing may disappear unseen.

The buckets, and the only code that fills them:
  blank            table.tabloyu_bul / rows._try_parse_csv   a row with no cell filled
  header_repeats   table.tabloyu_bul                         a page break repeating the header row
  summary_skipped  rows._try_parse_csv                       the WHOLE description is a summary phrase and the
                                                             row has no date or no amount (listed in summary_lines)
  account_skipped  rows._csv_satiri                          a transfer/closing posting of an account-coded ledger
                                                             (the names are in `atlanan`)
  emitted          rows._try_parse_csv / bank parsers        a transaction row: booked or held by the hold step
  continuation     parsers.lines.account_for_lines           a wrapped description line attached to its row
  non_row_lines    parsers.lines.account_for_lines           page header / footer / address / rule
  out_of_scope     services.ingest.feed                      a pulled item (not an upload) whose READABLE date is outside the
                                                             window the sync asked for; an unreadable date is never this
  (text statements: `read` is parsers.lines.read_lines, the physical non-empty lines, independent of every row
  pattern; a money-like line no pattern took is EMITTED as a held "satır okunamadı" row, never dropped)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MAX_LISTED = 25

SUMMED = (
    "read", "blank", "header_repeats", "emitted", "summary_skipped", "account_skipped", "continuation", "non_row_lines",
    "out_of_scope",
)


@dataclass
class ReadLedger:
    read: int = 0
    blank: int = 0
    header_repeats: int = 0
    emitted: int = 0
    summary_skipped: int = 0
    account_skipped: int = 0
    continuation: int = 0       # a wrapped description attached to the row above it
    non_row_lines: int = 0      # a page header, footer, address or rule of a text statement
    out_of_scope: int = 0       # a pulled item with a readable date outside the requested window (services.ingest.feed)
    summary_lines: list[dict[str, str]] = field(default_factory=list)
    # The structured reader failed on this file and another reader took over (never silently).
    reader_failed: bool = False
    # Text statements: was the running balance chain checked? "verified" | "unverified" | None (not a text statement).
    balance_check: str | None = None

    def reset(self) -> None:
        """A reader gave up: the next one starts from nothing (the failure itself is remembered)."""
        failed = self.reader_failed
        self.__init__()  # type: ignore[misc]
        self.reader_failed = failed

    def add(self, other: ReadLedger) -> None:
        """Another reader's counts, added in (every number, the listed lines, the flags)."""
        for name in SUMMED:
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.summary_lines = [*self.summary_lines, *other.summary_lines][:MAX_LISTED]
        self.reader_failed = self.reader_failed or other.reader_failed
        self.balance_check = other.balance_check or self.balance_check

    def absorb(self, account: Any) -> None:
        """Add what `parsers.lines.account_for_lines` found: the physical lines read, and where each went."""
        self.read += account.read
        self.continuation += account.continuation
        self.non_row_lines += account.non_row
        for line in account.summary:
            self.skip_summary(line)

    def skip_summary(self, description: str, date: str = "") -> None:
        self.summary_skipped += 1
        if len(self.summary_lines) < MAX_LISTED:
            self.summary_lines.append({"description": description[:120], "date": date})

    @property
    def touched(self) -> bool:
        return bool(self.read or self.reader_failed)

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in SUMMED} | {
            "summary_lines": list(self.summary_lines), "reader_failed": self.reader_failed,
            "balance_check": self.balance_check,
        }


def merge_counts(a: dict[str, Any] | None, b: dict[str, Any] | None) -> dict[str, Any] | None:
    """Counts of several documents of one analysis, added up."""
    if not a or not b:
        return a or b
    out: dict[str, Any] = {k: int(a.get(k, 0)) + int(b.get(k, 0)) for k in SUMMED}
    out["summary_lines"] = [*a.get("summary_lines", []), *b.get("summary_lines", [])][:MAX_LISTED]
    out["reader_failed"] = bool(a.get("reader_failed") or b.get("reader_failed"))
    checks = {c for c in (a.get("balance_check"), b.get("balance_check")) if c}
    out["balance_check"] = None if not checks else "unverified" if "unverified" in checks else "verified"
    return out


def unaccounted(counts: dict[str, Any] | None) -> int:
    """Rows that left the readers by no named bucket (0 when the invariant holds, or nothing was counted)."""
    if not counts or not counts.get("read"):
        return 0
    gone = counts["read"] - sum(int(counts.get(k, 0)) for k in SUMMED if k != "read")
    held_step = 0
    if "accepted" in counts:
        held_step = counts["emitted"] - int(counts["accepted"]) - int(counts.get("held", 0))
    return abs(gone) + abs(held_step)


def reconcile(counts: dict[str, Any] | None, accepted: int, held: int) -> tuple[dict[str, Any] | None, int]:
    """The counts with the hold step's numbers added, and how many rows are unaccounted for (logged when > 0)."""
    if not counts:
        return None, 0
    done = {**counts, "accepted": accepted, "held": held}
    lost = unaccounted(done)
    done["unaccounted"] = lost
    if lost:
        import logging

        logging.getLogger(__name__).error(
            "ingest row count does not reconcile: %s", {k: v for k, v in done.items() if isinstance(v, int)},
        )
    return done, lost
