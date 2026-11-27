"""Tasks that may call a model in `masked` mode WITHOUT a company (pattern masking only).

Everything else fails closed when no company is known (`session.open_session`). An entry is allowed only for
a call that by construction carries no tenant data (no company's books, documents, chat or names), and each
entry says why. `tests/test_llm_egress_fail_closed.py` requires a reason of real length for every entry and
that every entry names a task some call site really uses.

Empty on purpose: the review of every call site (the 49 in tests/test_llm_egress_matrix.py) found none that
runs without a company and carries no tenant data. The morning brief, the embedding back-fill and the
semantic rebuild are system jobs, but each runs per company and passes that company explicitly.
"""
from __future__ import annotations

SYSTEM_CALLS: dict[str, str] = {}
