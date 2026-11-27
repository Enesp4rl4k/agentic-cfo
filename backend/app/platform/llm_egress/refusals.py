"""Masked mode refused a call (fail closed): record it where people look.

A refusal means the AI step did not run and nothing left; the caller shows its deterministic result, as in
`off`. It is never silent:

* an `llm_call_logs` row (ok = false, error = "egress_refused:<reason>", bytes_out = 0): the owner's privacy
  card counts these for 30 days, and the operator check (`ops_watch._llm_egress_refusals`) alerts on them;
* an in-process counter (`counts()`), shown by `/ready` to an operator;
* a warning in the log with the reason and the task, never a payload.

Reasons: `no_organisation_context` (no company known for this call) and `dictionary_unavailable` (the
company's names could not be read completely).
"""
from __future__ import annotations

import logging
from collections import Counter

from app.platform.llm_egress.policy import EgressRefused

logger = logging.getLogger(__name__)

REASONS = ("no_organisation_context", "dictionary_unavailable")
ERROR_PREFIX = "egress_refused:"
_COUNTS: Counter = Counter()

MESSAGES = {
    "no_organisation_context": "Yapay zekâ adımı yapılmadı: bu çağrının hangi şirkete ait olduğu bilinmiyor, "
                               "maskeli modda isimler korunamayacağı için hiçbir veri gönderilmedi.",
    "dictionary_unavailable": "Yapay zekâ adımı yapılmadı: şirketin isim sözlüğü okunamadı, maskeli modda "
                              "isimler korunamayacağı için hiçbir veri gönderilmedi.",
}


def counts() -> dict[str, int]:
    return {r: _COUNTS[r] for r in REASONS}


def reset() -> None:
    _COUNTS.clear()


def refuse(reason: str, *, task: str | None, org_id: str | None) -> EgressRefused:
    """Count, log and audit one refusal; return the exception for the caller to raise."""
    _COUNTS[reason] += 1
    logger.warning("llm egress refused (masked mode, fail closed): reason=%s task=%s", reason, task or "-")
    try:
        from app.platform.llm_egress.audit import persist_call_log

        persist_call_log(org_id=org_id, job_id=None, task=task or "unknown", model="-", res=None, ok=False,
                         error=ERROR_PREFIX + reason, tally=None, data_mode="masked")
    except Exception as exc:  # pragma: no cover - the refusal stands even if the ledger is down
        logger.debug("refusal audit row skipped: %s", type(exc).__name__)
    return EgressRefused(MESSAGES[reason], reason=reason)
