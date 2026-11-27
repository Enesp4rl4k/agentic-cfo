"""The names the system already KNOWS: the company's own, its counterparties, its people.

No NER model: the dictionary is built from the tenant's own tables (`dictionary.py`) and matched here on
TOKENS, not characters, so spelling noise does not break a match:

* case- and diacritic-insensitive, with Turkish casing (İ/I/ı/i) folded first;
* any amount of whitespace, line breaks or zero-width characters between the words of a name (at most one
  of `. - & /` besides);
* an attached Turkish suffix after the last word, with or without an apostrophe ("Yılmazın", "ACMEye",
  "Işık Gıdaya"), from a bounded grammar (`suffixes.py`), never "anything after";
* the legal-form tail ("A.Ş.", "Ltd. Şti.", "San. ve Tic.") optional on either side;
* single words: a person's first name or surname alone, and a company's distinctive first word alone, but a
  word that is also ordinary Turkish ("Güneş", "Deniz", "Demir": `common_words.py`) only where it reads as a
  name: capitalised, not at the start of a sentence, or followed by an apostrophe suffix. The measured
  over- and under-masking of this rule is in docs/kvkk/yapay-zeka-veri-akisi.md.

The matcher is a hash lookup per token (first word -> candidate names, suffix stems by length), so time is
linear in the text and does not depend on the dictionary's size beyond its longest name.

Residual risk, stated plainly: a name the books do not hold (a person only named in a free-text note, a name
new to the document being read) is not found.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.platform.llm_egress.common_words import COMMON_WORDS
from app.platform.llm_egress.suffixes import MAX_SUFFIX, SUFFIXES

_TR = {
    "ı": "i", "İ": "i", "I": "i", "ğ": "g", "Ğ": "g", "ş": "s", "Ş": "s",
    "ö": "o", "Ö": "o", "ü": "u", "Ü": "u", "ç": "c", "Ç": "c",
    "â": "a", "Â": "a", "î": "i", "Î": "i", "û": "u", "Û": "u",
}
_ZERO_WIDTH = frozenset("​‌‍⁠﻿­")
_APOSTROPHES = frozenset("'’‘´`")


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


@dataclass(frozen=True)
class Token:
    word: str      # folded, zero-width characters removed
    start: int     # in the original text
    end: int
    shape: str     # "title" | "upper" | "lower" | "other"


_WORD = re.compile(r"[^\W_]+")


def _shape(raw: str) -> str:
    letters = [c for c in raw if c.isalpha()]
    if not letters:
        return "other"
    if all(c.isupper() for c in letters):
        return "upper" if len(letters) > 1 else "title"
    if letters[0].isupper():
        return "title"
    return "lower" if all(c.islower() for c in letters) else "other"


def tokenize(text: str) -> list[Token]:
    """Words of `text` with their original offsets; a zero-width character inside a word does not split it."""
    if any(c in _ZERO_WIDTH for c in text):
        index = [i for i, c in enumerate(text) if c not in _ZERO_WIDTH]
        clean = "".join(text[i] for i in index)
    else:
        index, clean = None, text
    out: list[Token] = []
    for m in _WORD.finditer(clean):
        s, e = (index[m.start()], index[m.end() - 1] + 1) if index is not None else (m.start(), m.end())
        out.append(Token(fold(m.group(0)), s, e, _shape(m.group(0))))
    return out


def words_of(text: str) -> list[str]:
    return [t.word for t in tokenize(text)]


_SUFFIXES_LEGAL: tuple[tuple[str, ...], ...] = (
    ("limited", "sirketi"), ("anonim", "sirketi"), ("ltd", "sti"), ("a", "s"),
    ("as",), ("ltd",), ("sti",), ("limited",), ("sirketi",), ("anonim",), ("inc",), ("llc",), ("gmbh",),
)
_FILLER = frozenset({"san", "sanayi", "tic", "ticaret", "ve", "ic", "dis"})
_MIN_SINGLE = 3     # a single-word key needs at least this many letters
_MIN_STEM = 4       # a word only takes an unapostrophed suffix when its base has at least this many letters
_MAX_WORDS = 8


def _strip_legal(words: list[str]) -> list[str]:
    out = list(words)
    changed = True
    while changed and out:
        changed = False
        for suf in sorted(_SUFFIXES_LEGAL, key=len, reverse=True):
            if len(out) > len(suf) and tuple(out[-len(suf):]) == suf:
                out, changed = out[:-len(suf)], True
                break
    return out


def _strip_fillers(words: list[str]) -> list[str]:
    out = list(words)
    while len(out) > 1 and out[-1] in _FILLER:
        out.pop()
    return out


def name_keys(name: str, *, person: bool = False) -> list[tuple[str, ...]]:
    """The word tuples one name is matched by: as written, without its legal tail, without "San. ve Tic.",
    and the single words that may stand for it alone (a person's names; a company's distinctive first word)."""
    words = words_of(name)
    if not words or all(w.isdigit() for w in words) or (len(words) == 1 and len(words[0]) < _MIN_SINGLE):
        return []
    keys = [tuple(words[:_MAX_WORDS])]
    core = _strip_fillers(_strip_legal(words))
    for variant in (_strip_legal(words), core):
        if variant and sum(len(w) for w in variant) >= _MIN_SINGLE and tuple(variant[:_MAX_WORDS]) not in keys:
            keys.append(tuple(variant[:_MAX_WORDS]))
    if len(core) > 1 and sum(len(w) for w in core) >= 6 and (glued := ("".join(core),)) not in keys:
        keys.append(glued)  # "IşıkGıda", or a zero-width character where the space was
    singles = [w for w in core if not w.isdigit()] if person else core[:1]
    for w in singles:
        if len(w) >= _MIN_SINGLE and (w,) not in keys and (person or (len(core) > 1 and w not in COMMON_WORDS)):
            keys.append((w,))
    return keys


@dataclass(frozen=True)
class NameHit:
    start: int
    end: int
    label: str
    key: str        # the entity (its canonical name, folded): one entity number for every spelling
    canonical: str


class NameDictionary:
    """label -> names; built once per organisation, matched per outbound text. Its repr shows sizes only. A plain
    class on purpose: a serializer that walks dataclass fields (LangGraph checkpoints) cannot copy the names."""

    def __init__(self) -> None:
        self.entries: dict[tuple[str, ...], tuple[str, str]] = {}  # words -> (label, canonical)
        self.identifiers: dict[str, str] = {}                      # a tax number the books hold -> its label
        self.truncated = False
        self._by_first: dict[str, list[tuple[str, ...]]] = {}

    def __reduce__(self):  # pickling (a checkpoint, a cache, a task queue) would carry the names: refuse
        raise TypeError("NameDictionary holds an organisation's names and is never serialised")

    def __repr__(self) -> str:
        return f"NameDictionary(names={len(self)}, truncated={self.truncated})"

    __str__ = __repr__

    def add(self, label: str, name: str | None, *, person: bool = False) -> None:
        name = (name or "").strip()
        if not name:
            return
        for key in name_keys(name, person=person):
            if key in self.entries:
                continue
            self.entries[key] = (label, name)
            bucket = self._by_first.setdefault(key[0], [])
            bucket.append(key)
            bucket.sort(key=len, reverse=True)

    def add_identifier(self, value: str | None) -> None:
        digits = re.sub(r"\D", "", value or "")
        if len(digits) in (10, 11):
            self.identifiers.setdefault(digits, "TCKN" if len(digits) == 11 else "VKN")

    def __len__(self) -> int:
        return len(set(self.entries.values())) + len(self.identifiers)

    def find(self, text: str) -> list[NameHit]:
        if not self.entries or not text:
            return []
        tokens = tokenize(text)
        hits: list[NameHit] = []
        i = 0
        while i < len(tokens):
            hit = self._match_at(text, tokens, i)
            if hit is None:
                i += 1
                continue
            end_idx, end, (label, canonical) = hit
            end_idx, end = _swallow_legal_tail(text, tokens, end_idx, end)
            hits.append(NameHit(tokens[i].start, end, label, "|".join(words_of(canonical)), canonical))
            i = end_idx
        return hits

    def _match_at(self, text: str, tokens: list[Token], i: int) -> tuple[int, int, tuple[str, str]] | None:
        first = tokens[i]
        for key in self._by_first.get(first.word, ()):  # longest first; exact first word
            n = len(key)
            if n == 1 or i + n > len(tokens):
                continue
            chunk = tokens[i:i + n]
            if any(chunk[j].word != key[j] for j in range(1, n - 1)) or not _joined(text, chunk):
                continue
            last = chunk[-1]
            if last.word == key[-1] or _suffixed(last.word, key[-1]):
                return i + n, last.end, self.entries[key]
        for stem in _stems(first.word):  # one word, possibly with a suffix
            entry = self.entries.get((stem,))
            if entry is not None and _reads_as_name(text, tokens, i, stem):
                return i + 1, first.end, entry
        return None


# Consonant softening before a vowel suffix ("Lojistik" -> "Lojistiğe", "Kebap" -> "Kebabı"), folded.
_HARDEN = {"g": "k", "b": "p", "d": "t", "c": "c"}
_VOWELS = frozenset("aeiou")


def _stems(word: str) -> list[str]:
    out = [word]
    for k in range(1, min(MAX_SUFFIX, len(word) - _MIN_STEM) + 1):
        if word[-k:] in SUFFIXES:
            stem = word[:-k]
            out.append(stem)
            if word[-k] in _VOWELS and stem[-1] in _HARDEN:
                out.append(stem[:-1] + _HARDEN[stem[-1]])
    return out


def _suffixed(word: str, base: str) -> bool:
    if len(base) < _MIN_STEM:
        return False
    if word.startswith(base) and word[len(base):] in SUFFIXES:
        return True
    rest = word[len(base):]  # softened: base "lojistik", word "lojistige"
    return (word[:len(base) - 1] == base[:-1] and _HARDEN.get(word[len(base) - 1:len(base)]) == base[-1]
            and rest[:1] in _VOWELS and rest in SUFFIXES)


_SPACE = r"[\s​‌‍⁠﻿­]*"
# between two words of one name: any whitespace, at most one of . - & / \ and quotes around a word
_GAP_OK = re.compile(
    "^" + _SPACE + r"[\"“”«»]?" + _SPACE + r"[.\-&/\\]?" + _SPACE + r"[\"“”«»]?" + _SPACE + "$"
)


def _joined(text: str, chunk: list[Token]) -> bool:
    return all(_GAP_OK.match(text[chunk[j].end:chunk[j + 1].start]) for j in range(len(chunk) - 1))


def _sentence_start(text: str, pos: int) -> bool:
    j = pos - 1
    while j >= 0 and (text[j].isspace() or text[j] in "\"'“”‘’(«»-–—*•"):
        if text[j] == "\n":
            return True
        j -= 1
    return j < 0 or text[j] in ".!?:;"


def _reads_as_name(text: str, tokens: list[Token], i: int, stem: str) -> bool:
    """A single word stands for a known name. An ordinary word ("güneş") only where it reads as a name."""
    tok = tokens[i]
    if stem != tok.word and not _apostrophe_after(text, tok.end) and len(stem) < _MIN_STEM:
        return False
    if stem not in COMMON_WORDS:
        return True
    if _apostrophe_after(text, tok.end) and tok.shape in ("title", "upper"):
        return True
    return tok.shape == "title" and not _sentence_start(text, tok.start)


def _apostrophe_after(text: str, end: int) -> bool:
    return end < len(text) and text[end] in _APOSTROPHES


_ABBREVIATED_TAILS = frozenset({"s", "as", "sti", "ltd", "inc"})


def _swallow_legal_tail(text: str, tokens: list[Token], idx: int, end: int) -> tuple[int, int]:
    """Extend a match over an immediately following legal-form tail ("A.Ş.", "San. ve Tic. Ltd. Şti.") and its dot."""
    progressed = True
    while progressed and idx < len(tokens):
        progressed = False
        j, last = idx, end
        while j < len(tokens) and tokens[j].word in _FILLER and tokens[j].start - last <= 2:
            last = tokens[j].end
            j += 1
        for suf in sorted(_SUFFIXES_LEGAL, key=len, reverse=True):
            chunk = tokens[j:j + len(suf)]
            if (len(chunk) == len(suf) and tuple(t.word for t in chunk) == suf and chunk[0].start - last <= 2
                    and all(chunk[k + 1].start - chunk[k].end <= 2 for k in range(len(suf) - 1))):
                idx, end, progressed = j + len(suf), chunk[-1].end, True
                break
    if idx and tokens[idx - 1].word in _ABBREVIATED_TAILS and text[end:end + 1] == ".":
        end += 1
    return idx, end
