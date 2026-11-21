"""The one way an e-mail address is written and looked up.

A mailbox is not case-sensitive in practice, and every provider we meet treats
`Ada@Example.com` and `ada@example.com` as one inbox. Compared exactly, they were
two accounts (register, login and invitations each guessed differently), and an
invitation addressed to either one could not find the right account.

`normalize_email` is: Unicode NFKC, then strip, then lower-case.

- NFKC because compatibility forms (full-width letters, ligatures) look identical to
  a person and are different strings to a database: the same lookalike-duplicate
  problem as case, and `email-validator` does not remove them.
- Plus-addresses and dots are NOT touched. `ada+invoices@x.com` and `a.da@x.com` are
  distinct mailboxes on many providers; folding them would hand one person's
  invitation to another.

Writers: the `email` columns normalise on assignment (`@validates`), so a site that
forgets cannot store a raw spelling. Readers: every lookup passes its input through
this function; `tests/test_email_lookups.py` fails on a query that compares an e-mail
column with anything else.
"""
from __future__ import annotations

import unicodedata


def normalize_email(email: str) -> str:
    return unicodedata.normalize("NFKC", email).strip().lower()
