"""Deterministic, reversible pseudonymisation of one outbound call.

Two flavours, one class:

* SEQUENTIAL (chat, narratives, extraction): `[KARŞI_TARAF_3]`, numbered by first appearance within ONE
  call. The same value is the same placeholder everywhere in that call, so the model can still reason
  ("[KARŞI_TARAF_1] was paid twice"); the next call numbers afresh, so the provider cannot link two
  calls through a placeholder. The reply is restored with `restore`.
* STABLE (embeddings): `[KARŞI_TARAF_a1b2c3d4]`, a keyed hash of (organisation, label, value). A chunk
  indexed today and a question asked next month produce the SAME token for the same name, so cosine
  similarity between them survives; the key is the server secret, so the provider cannot reverse the
  token by hashing a guessed name. There is nothing to restore: an embedding is not text.

Amounts, dates and currencies are never touched: no detector looks at a number without an identifier's
own check digits and context, and the dictionary only holds names.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from collections import Counter
from dataclasses import dataclass, field

from app.platform.llm_egress import detectors
from app.platform.llm_egress.names import NameDictionary, fold

# Name labels (the identifier labels live in `detectors`).
COMPANY, COUNTERPARTY, PERSON = "ŞİRKET", "KARŞI_TARAF", "KİŞİ"
NAME_LABELS = (COMPANY, COUNTERPARTY, PERSON)
ALL_LABELS = (*detectors.PRIORITY, *NAME_LABELS)

UNKNOWN_NAME = "[bilinmeyen taraf]"
UNKNOWN_VALUE = "[bilinmeyen değer]"

_PLACEHOLDER = re.compile(r"\[\s*([A-Za-zÇĞİıÖŞÜçğöşü_]+?)_(\d{1,4}|[0-9a-f]{8})\s*\]")
_FOLDED_LABELS = {fold(label): label for label in ALL_LABELS}


@dataclass
class Pseudonymizer:
    names: NameDictionary | None = None
    stable_key: bytes | None = None          # set: STABLE flavour (embeddings)
    _map: dict[tuple[str, str], str] = field(default_factory=dict)        # (label, key) -> token
    _original: dict[str, str] = field(default_factory=dict)               # token -> text to restore
    _next: Counter = field(default_factory=Counter)
    counts: Counter = field(default_factory=Counter)                      # label -> occurrences replaced

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def _token(self, label: str, key: str, shown: str) -> str:
        hit = self._map.get((label, key))
        if hit is None:
            if self.stable_key is not None:
                digest = hmac.new(self.stable_key, f"{label}\x00{key}".encode(), hashlib.sha256).hexdigest()[:8]
                hit = f"[{label}_{digest}]"
            else:
                self._next[label] += 1
                hit = f"[{label}_{self._next[label]}]"
            self._map[(label, key)] = hit
            self._original[hit] = shown
        return hit

    def mask(self, text: str) -> str:
        """`text` with every identifier and known name replaced; everything else byte for byte."""
        if not text:
            return text
        spans = [
            detectors.Span(h.start, h.end, h.label, h.key, h.canonical)
            for h in (self.names.find(text) if self.names else [])
        ]
        # identifiers beat names where they overlap (an e-mail address that contains a company name)
        merged = detectors.resolve_overlaps(detectors.find_identifiers(text) + spans)
        if not merged:
            return text
        out: list[str] = []
        last = 0
        for s in merged:
            out.append(text[last:s.start])
            out.append(self._token(s.label, s.key, s.canonical or text[s.start:s.end]))
            self.counts[s.label] += 1
            last = s.end
        out.append(text[last:])
        return "".join(out)

    def restore(self, text: str) -> str:
        """Put the original values back. A placeholder this call never issued is not guessed at."""
        if not text or "[" not in text:
            return text

        def sub(m: re.Match[str]) -> str:
            label = _FOLDED_LABELS.get(fold(m.group(1)))
            if label is None:
                return m.group(0)  # not one of ours: an ordinary bracket
            token = f"[{label}_{m.group(2)}]"
            if token in self._original:
                return self._original[token]
            return UNKNOWN_NAME if label in NAME_LABELS else UNKNOWN_VALUE

        return _PLACEHOLDER.sub(sub, text)


class StreamRestorer:
    """Restore placeholders in a token stream: a placeholder cut in two chunks is held until complete."""

    _HOLD = 48

    def __init__(self, pseudo: Pseudonymizer) -> None:
        self._p = pseudo
        self._pending = ""

    def feed(self, piece: str) -> str:
        text = self._pending + piece
        cut = text.rfind("[")
        if cut != -1 and "]" not in text[cut:] and len(text) - cut <= self._HOLD:
            self._pending = text[cut:]
            text = text[:cut]
        else:
            self._pending = ""
        return self._p.restore(text)

    def flush(self) -> str:
        rest, self._pending = self._pending, ""
        return self._p.restore(rest)
