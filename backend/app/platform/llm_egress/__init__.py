"""LLM data minimisation: what may leave for a language model, and in what shape.

Every outbound payload (chat, narratives, extraction, embeddings) passes the one choke point,
`app.platform.model_gateway` / `app.platform.embedding_gateway`, which opens a session here:

  policy        the mode (off | masked | raw), per platform and per organisation
  detectors     identifiers by pattern with check digits (IBAN, TCKN, VKN, card, phone, e-mail, plate)
  names         the names the books already hold, matched without case or diacritics
  dictionary    builds an organisation's names from its own tables
  pseudonymizer the reversible placeholder substitution (and its streaming restorer)
  session       one call: mask what goes, restore what comes back, tally what left
  audit         the payload-free row per call, and the 30-day counters

See docs/kvkk/yapay-zeka-veri-akisi.md for what leaves in each mode and the residual risk.
"""
from app.platform.llm_egress.policy import DataMode, PolicyOff, effective_mode
from app.platform.llm_egress.session import (
    CallTally,
    EgressSession,
    begin_call,
    current_tally,
    end_call,
    open_session,
    tallied,
)

__all__ = [
    "CallTally", "DataMode", "EgressSession", "PolicyOff", "begin_call", "current_tally", "effective_mode",
    "end_call", "open_session", "tallied",
]
