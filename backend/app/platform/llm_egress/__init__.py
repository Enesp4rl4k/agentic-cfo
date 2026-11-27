"""LLM data minimisation: what may leave for a language model, and in what shape.

Every outbound payload (chat, narratives, extraction, embeddings) passes the one choke point,
`app.platform.model_gateway` / `app.platform.embedding_gateway`, which opens a session here:

  policy        the mode (off | masked | raw), per platform and per organisation
  figures       amounts, dates, codes, document numbers: classified as data FIRST, never masked
  detectors     identifiers on positive evidence only (checksum + shape + label / unambiguous format)
  names         the names the books already hold, matched on tokens (case, diacritics, suffixes, spacing)
  common_words  ordinary words that are also names: masked alone only where they read as a name
  suffixes      the bounded Turkish suffix grammar a name may carry without an apostrophe
  dictionary    builds an organisation's names from its own tables
  pseudonymizer the reversible placeholder substitution (and its streaming restorer)
  session       one call: mask what goes, restore what comes back, tally what left; FAIL CLOSED
  replies       JSON replies: parsed first, then restored value by value
  refusals      a refused call (fail closed): audit row, counter, operator alert
  system_calls  the (empty) allow-list of tasks that may go without a company
  audit         the payload-free row per call, and the 30-day counters
  tracing       LangSmith / LangGraph traces carry no inputs or outputs, whatever the environment says

See docs/kvkk/yapay-zeka-veri-akisi.md for what leaves in each mode and the residual risk.
"""
from app.platform.llm_egress import tracing  # noqa: F401  (forces trace payloads hidden, at import)
from app.platform.llm_egress.policy import DataMode, EgressRefused, PolicyOff, effective_mode
from app.platform.llm_egress.replies import NOT_JSON, restore_json_reply
from app.platform.llm_egress.session import (
    CallTally,
    EgressSession,
    begin_call,
    current_tally,
    end_call,
    open_session,
    skipped_steps,
    tallied,
)

__all__ = [
    "NOT_JSON", "CallTally", "DataMode", "EgressRefused", "EgressSession", "PolicyOff", "begin_call",
    "current_tally", "effective_mode", "end_call", "open_session", "restore_json_reply", "skipped_steps", "tallied",
]
