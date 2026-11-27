"""Deterministic, reversible pseudonymisation of one outbound call.

Placeholders are ASCII-only tokens that survive JSON escaping (no quote, no backslash, no non-ASCII letter to
be written as \\uXXXX) and tokenisation: `[[CP_7KQ_3]]` = type code, a per-call nonce, the entity number.

* SEQUENTIAL (chat, narratives, extraction): numbered by first appearance within ONE call, with a fresh
  nonce per call, so the provider cannot link two calls through a placeholder and a placeholder from another
  call (or an invented one) is recognised as unknown. Every DIFFERENT original text gets its own placeholder,
  keyed by the exact substring, so restoring is byte-exact; two spellings of one entity share the entity
  number and differ by a letter (`[[CP_7KQ_3]]`, `[[CP_7KQ_3b]]`), so the model still sees they are one party.
* STABLE (embeddings): `[[CP_a1b2c3d4]]`, a keyed hash of (organisation, type, entity). A chunk indexed
  today and a question asked next month give the SAME token for the same name, so similarity survives; the
  key is server-side, so the provider cannot reverse it. Nothing is restored: an embedding is not text.

Restoring: `restore` (free text) puts every issued placeholder back and writes an unknown or mangled one as
"[bilinmeyen taraf]" / "[bilinmeyen değer]", never a guessed name. `restore_strict` (structured data that
may reach the books) returns None when anything placeholder-shaped is left, so the field counts as missing.

Amounts, dates and currencies are never touched (`figures`, `detectors`); the mapping never leaves this
object: its repr shows counts only, and nothing here logs.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections import Counter
from dataclasses import dataclass, field

from app.platform.llm_egress import detectors
from app.platform.llm_egress.names import NameDictionary

# Name labels (identifier labels live in `detectors`).
COMPANY, COUNTERPARTY, PERSON = "CO", "CP", "PER"
NAME_LABELS = (COMPANY, COUNTERPARTY, PERSON)
ALL_LABELS = (*detectors.PRIORITY, *NAME_LABELS)

UNKNOWN_NAME = "[bilinmeyen taraf]"
UNKNOWN_VALUE = "[bilinmeyen değer]"

_NONCE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I
_LABEL_ALT = "|".join(sorted(ALL_LABELS, key=len, reverse=True))
# What the model may give back for one of our placeholders, brackets or case mangled included.
_SHAPED = re.compile(
    r"\[{1,2}\s*(" + _LABEL_ALT + r")\s*[_\-]\s*([A-Za-z0-9]{3})\s*[_\-]\s*(\d{1,4})([a-z]?)\s*\]{1,2}",
    re.IGNORECASE,
)
# Anything that still looks like a placeholder after restoring (stable tokens and foreign nonces included).
RESIDUE = re.compile(r"\[{1,2}\s*(?:" + _LABEL_ALT + r")\s*[_\-]\s*[A-Za-z0-9]{3,8}(?:\s*[_\-]\s*\d{1,4}[a-z]?)?\s*\]{1,2}",
                     re.IGNORECASE)

# A stream chunk that may still grow into a placeholder (held back until it is complete or clearly is not).
_PREFIX = re.compile(r"^\[{1,2}\s*[A-Za-z]{0,5}(?:\s*[_\-]\s*[A-Za-z0-9]{0,8}(?:\s*[_\-]\s*\d{0,4}[a-z]?)?)?\s*\]?$")

PROMPT_NOTE = (
    "Not: [[CP_...]] (karşı taraf), [[CO_...]] (şirket), [[PER_...]] (kişi), [[IBAN_...]], [[CARD_...]], [[TEL_...]], "
    "[[MAIL_...]], [[TCKN_...]], [[VKN_...]], [[ACCT_...]], [[PLATE_...]] biçimindeki ifadeler gizlilik için konmuş "
    "yer tutuculardır. Yanıtında onları köşeli parantezleriyle birlikte aynen yaz; değiştirme, yenisini uydurma."
)


def _variant(n: int) -> str:
    return "" if n == 0 else "bcdefghijklmnopqrstuvwxyz"[min(n - 1, 24)]


@dataclass(repr=False, eq=False)
class Pseudonymizer:
    names: NameDictionary | None = None
    stable_key: bytes | None = None          # set: STABLE flavour (embeddings)
    nonce: str = field(default_factory=lambda: "".join(secrets.choice(_NONCE_ALPHABET) for _ in range(3)))
    _entity: dict[tuple[str, str], int] = field(default_factory=dict)       # (label, entity key) -> number
    _surface: dict[tuple[str, str, str], str] = field(default_factory=dict)  # (label, entity, exact text) -> token
    _variants: Counter = field(default_factory=Counter)
    _original: dict[str, str] = field(default_factory=dict)                 # token core -> exact original text
    _next: Counter = field(default_factory=Counter)
    counts: Counter = field(default_factory=Counter)                        # label -> occurrences replaced

    def __repr__(self) -> str:  # never the mapping, never a name
        return f"Pseudonymizer(replaced={sum(self.counts.values())}, issued={len(self._original)})"

    __str__ = __repr__

    def __reduce__(self):  # pickling (a task queue, a cache) would carry the mapping: refuse
        raise TypeError("Pseudonymizer holds the call's mapping and is never serialised")

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def issued(self) -> int:
        return len(self._original)

    def _token(self, label: str, key: str, exact: str) -> str:
        hit = self._surface.get((label, key, exact))
        if hit is not None:
            return hit
        if self.stable_key is not None:
            digest = hmac.new(self.stable_key, f"{label}\x00{key}".encode(), hashlib.sha256).hexdigest()[:8]
            token = f"[[{label}_{digest}]]"
        else:
            number = self._entity.get((label, key))
            if number is None:
                self._next[label] += 1
                number = self._entity[(label, key)] = self._next[label]
            variant = _variant(self._variants[(label, key)])
            self._variants[(label, key)] += 1
            core = f"{label}_{self.nonce}_{number}{variant}"
            token = f"[[{core}]]"
            self._original[core.upper()] = exact
        self._surface[(label, key, exact)] = token
        return token

    def mask(self, text: str) -> str:
        """`text` with every identifier and known name replaced; everything else byte for byte."""
        if not text:
            return text
        known = self.names.identifiers if self.names else {}
        spans = [
            detectors.Span(h.start, h.end, h.label, h.key, h.canonical)
            for h in (self.names.find(text) if self.names else [])
        ]
        merged = detectors.resolve_overlaps(detectors.find_identifiers(text, known) + spans)
        if not merged:
            return text
        out: list[str] = []
        last = 0
        for s in merged:
            out.append(text[last:s.start])
            out.append(self._token(s.label, s.key, text[s.start:s.end]))
            self.counts[s.label] += 1
            last = s.end
        out.append(text[last:])
        return "".join(out)

    def _lookup(self, m: re.Match[str]) -> str | None:
        label, nonce, number, variant = m.group(1).upper(), m.group(2).upper(), m.group(3), m.group(4).lower()
        return self._original.get(f"{label}_{nonce}_{number}{variant}".upper())

    def restore(self, text: str) -> str:
        """Free text: issued placeholders back byte-exact; anything else placeholder-shaped -> unknown."""
        if not text or "[" not in text:
            return text

        def sub(m: re.Match[str]) -> str:
            hit = self._lookup(m)
            if hit is not None:
                return hit
            return UNKNOWN_NAME if m.group(1).upper() in NAME_LABELS else UNKNOWN_VALUE

        restored = _SHAPED.sub(sub, text)
        return RESIDUE.sub(lambda m: UNKNOWN_VALUE, restored)

    def restore_strict(self, text: str) -> str | None:
        """Structured data: the restored string, or None when any placeholder was unknown or mangled."""
        if not text or "[" not in text:
            return text
        unknown = False

        def sub(m: re.Match[str]) -> str:
            nonlocal unknown
            hit = self._lookup(m)
            if hit is None:
                unknown = True
                return m.group(0)
            return hit

        restored = _SHAPED.sub(sub, text)
        if unknown or RESIDUE.search(_SHAPED.sub("", text)):
            return None
        return restored


class StreamRestorer:
    """Restore placeholders in a token stream: a placeholder cut across chunks is held until complete."""

    _HOLD = 40

    def __init__(self, pseudo: Pseudonymizer) -> None:
        self._p = pseudo
        self._pending = ""

    def __repr__(self) -> str:
        return "StreamRestorer()"

    def feed(self, piece: str) -> str:
        text = self._pending + piece
        cut = text.rfind("[")
        if cut > 0 and text[cut - 1] == "[":
            cut -= 1
        if cut != -1 and len(text) - cut <= self._HOLD and _PREFIX.match(text[cut:]):
            self._pending = text[cut:]
            text = text[:cut]
        else:
            self._pending = ""
        return self._p.restore(text)

    def flush(self) -> str:
        rest, self._pending = self._pending, ""
        return self._p.restore(rest)
