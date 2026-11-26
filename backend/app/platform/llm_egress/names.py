"""The names the system already KNOWS: the company's own, its counterparties, its people.

No NER model: the dictionary is built from the tenant's own tables (see `dictionary.py`) and matched
here, case- and diacritic-insensitively, with the Turkish dotted/dotless i handled and the common legal
suffixes ("A.Ş.", "Ltd. Şti.", "Limited Şirketi") optional on either side.

Matching works on a FOLDED copy of the text that has exactly the same length as the original, so a span
found in the folded text is the span of the original and the original is never altered except by the
placeholder that replaces the span.

Residual risk, stated plainly: a name the books do not hold (a person only named in a free-text
description, a counterparty spelled differently from the books) is not found.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Turkish letters first (str.lower() would turn "İ" into two code points); everything else is folded
# to its base ASCII letter when it has one. One character in, one character out.
_TR = {
    "ı": "i", "İ": "i", "I": "i", "ğ": "g", "Ğ": "g", "ş": "s", "Ş": "s",
    "ö": "o", "Ö": "o", "ü": "u", "Ü": "u", "ç": "c", "Ç": "c",
    "â": "a", "Â": "a", "î": "i", "Î": "i", "û": "u", "Û": "u",
}


def _fold_char(ch: str) -> str:
    if ch in _TR:
        return _TR[ch]
    low = ch.lower()
    if len(low) != 1:
        return ch
    if low.isascii():
        return low
    base = unicodedata.normalize("NFKD", low)[:1]
    return base if base.isascii() and base else low


def fold(text: str) -> str:
    """Lower-case, ASCII-fold, SAME LENGTH as `text`."""
    return "".join(_fold_char(c) for c in text)


_WORD = re.compile(r"[a-z0-9]+")
_DIGITS = re.compile(r"(?<![\d.,])\d{10,11}(?![\d])")

# Legal-form tails, as folded word sequences: "A.Ş." -> ("a", "s"), "Ltd. Şti." -> ("ltd", "sti").
_SUFFIXES: tuple[tuple[str, ...], ...] = (
    ("limited", "sirketi"), ("anonim", "sirketi"), ("ltd", "sti"), ("a", "s"),
    ("as",), ("ltd",), ("sti",), ("limited",), ("sirketi",), ("anonim",), ("inc",), ("llc",), ("gmbh",),
)
_FILLER = frozenset({"san", "sanayi", "tic", "ticaret", "ve", "ic", "dis"})  # "San. ve Tic."
_MIN_CORE_CHARS = 3
_MAX_WORDS = 8
_MAX_GAP = 3  # separator characters allowed between two words of one name


def words_of(text: str) -> list[str]:
    return _WORD.findall(fold(text))


def _strip_suffix(words: list[str]) -> list[str]:
    """Remove legal-form tails ("a s", "ltd sti", ...) from the end, repeatedly."""
    out = list(words)
    changed = True
    while changed and out:
        changed = False
        for suf in sorted(_SUFFIXES, key=len, reverse=True):
            if len(out) > len(suf) and tuple(out[-len(suf):]) == suf:
                out = out[:-len(suf)]
                changed = True
                break
    return out


def _strip_fillers(words: list[str]) -> list[str]:
    out = list(words)
    while len(out) > 1 and out[-1] in _FILLER:
        out.pop()
    return out


def name_keys(name: str) -> list[tuple[str, ...]]:
    """The word tuples one canonical name is matched by: as written, without its legal-form tail, and
    without the "San. ve Tic." filler before it."""
    words = words_of(name)
    if not words or all(w.isdigit() for w in words) or (len(words) == 1 and len(words[0]) < _MIN_CORE_CHARS):
        return []
    keys = [tuple(words[:_MAX_WORDS])]
    bare = _strip_suffix(words)
    core = _strip_fillers(bare)
    for variant in (bare, core):
        if variant and sum(len(w) for w in variant) >= _MIN_CORE_CHARS and tuple(variant[:_MAX_WORDS]) not in keys:
            keys.append(tuple(variant[:_MAX_WORDS]))
    return keys


@dataclass(frozen=True)
class NameHit:
    start: int
    end: int
    label: str
    key: str        # the entity's identity (its canonical name, folded)
    canonical: str  # the books' own spelling, what a restored placeholder shows


@dataclass
class NameDictionary:
    """label -> names; built once per organisation, matched per outbound text."""

    entries: dict[tuple[str, ...], tuple[str, str]] = field(default_factory=dict)  # words -> (label, canonical)
    identifiers: dict[str, str] = field(default_factory=dict)  # a tax number the books hold -> its label
    truncated: bool = False  # a source had more rows than the cap: some names are NOT in the dictionary
    _max_words: int = 1

    def add(self, label: str, name: str | None) -> None:
        name = (name or "").strip()
        if not name:
            return
        for key in name_keys(name):
            self.entries.setdefault(key, (label, name))
            self._max_words = max(self._max_words, len(key))

    def add_identifier(self, value: str | None) -> None:
        """A tax number the books hold (the company's own VKN, a counterparty's): found without any context."""
        digits = re.sub(r"\D", "", value or "")
        if len(digits) in (10, 11):
            self.identifiers.setdefault(digits, "TCKN" if len(digits) == 11 else "VKN")

    def __len__(self) -> int:
        return len(set(self.entries.values())) + len(self.identifiers)

    def find(self, text: str) -> list[NameHit]:
        hits = self._find_names(text)
        if self.identifiers and text:
            for m in _DIGITS.finditer(text):
                label = self.identifiers.get(m.group(0))
                if label:
                    hits.append(NameHit(m.start(), m.end(), label, m.group(0), m.group(0)))
        return hits

    def _find_names(self, text: str) -> list[NameHit]:
        if not self.entries or not text:
            return []
        folded = fold(text)
        tokens = [(m.group(0), m.start(), m.end()) for m in _WORD.finditer(folded)]
        hits: list[NameHit] = []
        i = 0
        while i < len(tokens):
            matched = 0
            for n in range(min(self._max_words, len(tokens) - i), 0, -1):
                chunk = tokens[i:i + n]
                if any(folded[chunk[j][2]:chunk[j + 1][1]].count("\n") or chunk[j + 1][1] - chunk[j][2] > _MAX_GAP
                       for j in range(n - 1)):
                    continue
                hit = self.entries.get(tuple(t[0] for t in chunk))
                if hit is not None:
                    end_idx = i + n
                    end = chunk[-1][2]
                    end_idx, end = _swallow_legal_tail(tokens, end_idx, end, folded)
                    hits.append(NameHit(chunk[0][1], end, hit[0], "|".join(fold(hit[1]).split()), hit[1]))
                    matched = end_idx - i
                    break
            i += matched or 1
        return hits


_ABBREVIATED_TAILS = frozenset({"s", "as", "sti", "ltd", "inc"})  # "A.Ş.", "Ltd. Şti.": the final dot belongs to them


def _swallow_legal_tail(tokens: list[tuple[str, int, int]], idx: int, end: int, folded: str) -> tuple[int, int]:
    """Extend a match over an immediately following legal-form tail ("A.Ş.", "San. ve Tic. Ltd. Şti.") and its dot."""
    progressed = True
    while progressed and idx < len(tokens):
        progressed = False
        j, last = idx, end
        while j < len(tokens) and tokens[j][0] in _FILLER and tokens[j][1] - last <= 2:
            last = tokens[j][2]
            j += 1
        for suf in sorted(_SUFFIXES, key=len, reverse=True):
            chunk = tokens[j:j + len(suf)]
            if (len(chunk) == len(suf) and tuple(t[0] for t in chunk) == suf and chunk[0][1] - last <= 2
                    and all(chunk[k + 1][1] - chunk[k][2] <= 2 for k in range(len(suf) - 1))):
                idx, end, progressed = j + len(suf), chunk[-1][2], True
                break
    if idx and tokens[idx - 1][0] in _ABBREVIATED_TAILS and folded[end:end + 1] == ".":
        end += 1
    return idx, end
