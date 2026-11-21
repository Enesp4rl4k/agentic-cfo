"""Canonical invoice and document identity resolution.

Ensures that an invoice arriving from multiple sources (manual file upload, UBL-TR XML,
Paraşüt, Logo Tiger, Netsis, or Open Banking) resolves to the exact same canonical
document identity, solving Plan v10 Gap G2 (cross-source double-counting).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping

# GİB (Gelir İdaresi Başkanlığı) 16-character e-Fatura / e-Arşiv pattern:
# 3 alphanumeric characters (series) + 4-digit year + 9-digit sequence
GIB_INVOICE_PATTERN = re.compile(r"\b([A-Za-z0-9]{3}20\d{2}\d{9})\b", re.IGNORECASE)

# Standard UUID pattern (e.g. ETTN)
UUID_PATTERN = re.compile(
    r"\b([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\b"
)

# Explicit invoice number markers in Turkish / English accounting descriptions:
# e.g. #A-1, Fatura No: 2024-01, Inv#12345
INVOICE_MARKER_PATTERN = re.compile(
    r"(?:#|(?:\b(?:fatura|irsaliye|invoice|inv|evrak|belge|dekont)(?:\s*(?:no|numarası|nu))?[:\s#\-_]+))([A-Za-z0-9\-_]{2,24})",
    re.IGNORECASE,
)


def _strip_ledger_prefix(value: str | None) -> str | None:
    if value and str(value).lower().startswith("doc:"):
        return str(value)[4:]
    return value


def canonical_invoice_id(
    document_id: str | None = None,
    invoice_no: str | None = None,
    description: str | None = None,
) -> str | None:
    """Derive a normalized, deterministic invoice document identity.

    Priority (the explicit fields always come before free text: a credit note whose
    description names the invoice it reverses must not take that invoice's identity):
    1. GİB 16-character invoice number in invoice_no or document_id.
    2. Clean invoice number explicitly provided in invoice_no.
    3. document_id, if it is not a raw UUID.
    4. GİB 16-character number found in the description.
    5. Invoice number extracted from a description marker (e.g. '#A-1' -> 'A-1').
    6. Normalized UUID if only an ETTN / UUID is present.
    """
    # "doc:" is the ledger's own key prefix, not part of a document number.
    document_id = _strip_ledger_prefix(document_id)
    invoice_no = _strip_ledger_prefix(invoice_no)

    # 1. Official 16-char GİB format in an explicit field
    for text in (invoice_no, document_id):
        if not text:
            continue
        m = GIB_INVOICE_PATTERN.search(str(text))
        if m:
            return m.group(1).upper()

    # 2. invoice_no explicitly
    if invoice_no:
        clean = str(invoice_no).strip().upper()
        if clean and clean != "NONE" and clean != "N/A" and len(clean) >= 2:
            return clean

    # 3. document_id if not a generic UUID
    if document_id:
        doc_str = str(document_id).strip()
        if not UUID_PATTERN.match(doc_str) and len(doc_str) >= 2:
            return doc_str.upper()

    # 4./5. Only now the free-text description
    if description:
        m = GIB_INVOICE_PATTERN.search(str(description))
        if m:
            return m.group(1).upper()
        m = INVOICE_MARKER_PATTERN.search(str(description))
        if m:
            found = m.group(1).strip().upper()
            if len(found) >= 2:
                return found

    # 6. Fallback to UUID if present
    for text in (document_id, invoice_no, description):
        if not text:
            continue
        m = UUID_PATTERN.search(str(text))
        if m:
            return m.group(1).lower()

    return None


# ── who issued it: a free-form number is only unique per counterparty (plan v10 G23) ───────────
#
# Two suppliers that both number an invoice "A-001" issued two documents. A UUID (ETTN) or a
# GİB 16-character number names its document; "A-001" or "2024-01" only names it among one
# issuer's invoices, so the ledger and the open-item index add the counterparty and the side
# (sale or purchase) to such a number. Everything below is the one definition of that key;
# migration 065 imports it, so a change to the normalisation or the key format changes what a fresh
# upgrade writes: it needs its own data migration, and `tests/test_invoice_key_golden.py` fails first.

_UUID_ONLY = re.compile(UUID_PATTERN.pattern.replace(r"\b", "^", 1).replace(r"\b", "$", 1), re.IGNORECASE)
_GIB_ONLY = re.compile(r"^[A-Za-z0-9]{3}20\d{2}\d{9}$")
_SIDE = {"income": "s", "expense": "p"}  # s = a sales invoice we issued, p = a purchase invoice

# Legal forms that say nothing about who a company is, longest first. Only these come off the end
# of a name: dropping "San. ve Tic." too would make "Alfa Sanayi A.Ş." and "Alfa Ticaret A.Ş."
# one supplier, and merging two suppliers loses a payable silently, while failing to merge two
# spellings of one supplier is caught by the duplicate window (ledger.DUPLICATE_WINDOW_DAYS).
_LEGAL_FORMS: tuple[tuple[str, ...], ...] = (
    ("anonim", "sirketi"), ("limited", "sirketi"), ("kollektif", "sirketi"),
    ("komandit", "sirketi"), ("ltd", "sti"), ("a", "s"),
    ("as",), ("ltd",), ("sti",), ("limited",), ("sirketi",), ("anonim",),
)

_FORM_CLASS: dict[tuple[str, ...], str] = {
    ("anonim", "sirketi"): "as", ("a", "s"): "as", ("as",): "as", ("anonim",): "as",
    ("limited", "sirketi"): "ltd", ("ltd", "sti"): "ltd", ("ltd",): "ltd", ("sti",): "ltd",
    ("limited",): "ltd", ("sirketi",): "ltd", ("kollektif", "sirketi"): "kol",
    ("komandit", "sirketi"): "kom",
}

_TURKISH = str.maketrans({
    "ı": "i", "İ": "i", "I": "i", "ğ": "g", "Ğ": "g", "ş": "s", "Ş": "s", "ö": "o", "Ö": "o",
    "ü": "u", "Ü": "u", "ç": "c", "Ç": "c", "â": "a", "Â": "a", "î": "i", "Î": "i", "û": "u",
    "Û": "u", "̇": "",
})
_TOKEN = re.compile(r"[a-z0-9]+")
_TAX_NUMBER = re.compile(r"(?<!\d)(\d{10}|\d{11})(?!\d)")


def is_unique_id(document_id: str | None) -> bool:
    """A UUID (ETTN) or a GİB 16-character number: the document's own name, whoever issued it."""
    text = (document_id or "").strip()
    return bool(_UUID_ONLY.match(text) or _GIB_ONLY.match(text))


def _valid_vkn(digits: str) -> bool:
    if len(digits) != 10:
        return False
    total = 0
    for i in range(9):
        tmp = (int(digits[i]) + (9 - i)) % 10
        part = (tmp * 2 ** (9 - i)) % 9
        total += 9 if tmp != 0 and part == 0 else part
    return (10 - total % 10) % 10 == int(digits[9])


def _valid_tckn(digits: str) -> bool:
    if len(digits) != 11 or digits[0] == "0":
        return False
    d = [int(c) for c in digits]
    return (
        (sum(d[0:9:2]) * 7 - sum(d[1:8:2])) % 10 == d[9] and sum(d[:10]) % 10 == d[10]
    )


def tax_number_in(text: str | None) -> str | None:
    """A VKN (10 digits) or TCKN (11) written in a counterparty field, when its check digits hold."""
    for found in _TAX_NUMBER.findall(text or ""):
        if _valid_vkn(found) or _valid_tckn(found):
            return found
    return None


def normalise_party(name: str | None) -> str | None:
    """A counterparty's name as a comparison key; None when nothing telling is left.

    Lower case with Turkish letters folded ("İ", "I", "ı" are all "i"; "Ş" is "s"), every
    non-alphanumeric run a single space, and trailing legal forms removed ("A.Ş.", "AŞ",
    "Anonim Şirketi", "Ltd. Şti.", "Limited Şirketi"). Words inside the name are never dropped.
    """
    return " ".join(_strip_legal_forms(name)[0]) or None


def legal_form(name: str | None) -> str | None:
    """The legal form class written after a name ("as", "ltd", "kol", "kom"), None if it has none.

    "A.Ş.", "AŞ" and "Anonim Şirketi" are one class; "Ltd.", "Ltd. Şti." and "Limited Şirketi"
    another. Two spellings of one name with different classes may be two companies.
    """
    return _strip_legal_forms(name)[1]


def _strip_legal_forms(name: str | None) -> tuple[list[str], str | None]:
    tokens = _TOKEN.findall((name or "").lower().translate(_TURKISH))
    first: str | None = None
    stripped = True
    while stripped and tokens:
        stripped = False
        for form in _LEGAL_FORMS:
            if len(tokens) >= len(form) and tuple(tokens[-len(form):]) == form:
                tokens = tokens[: -len(form)]
                first = first or _FORM_CLASS[form]
                stripped = True
                break
    return tokens, first


def party_token(org_id: str, counterparty: str | None) -> str | None:
    """`t<hash>` for a tax number in the counterparty field, else `n<hash>` for its normalised name.

    The tax number is the stabler identifier (a name has spellings, a number has one), so it wins
    when it is there. The token is a hash salted with the organisation: the key outlives the
    counterparty's name (organisation erasure keeps it), and a sole trader's TCKN is a personal
    identifier that must not sit in clear in a retained key.
    """
    tax = tax_number_in(counterparty)
    if tax:
        return "t" + hashlib.sha256(f"{org_id}|tax|{tax}".encode()).hexdigest()[:12]
    name = normalise_party(counterparty)
    if name:
        return "n" + hashlib.sha256(f"{org_id}|name|{name}".encode()).hexdigest()[:12]
    return None


def document_key(
    org_id: str,
    document_id: str,
    counterparty: str | None,
    direction: str | None,
    aliases: Mapping[str, str] | None = None,
) -> str:
    """The ledger identity (`source_record_id`) of an invoice.

    - a UUID or GİB number: `doc:<id>`, as before;
    - a free-form number with a known counterparty and side: `inv:<s|p>:<party>:<number>`;
    - a free-form number with either unknown: `doc:<number>`, as before. It is not guessed: the
      row is counted (`ledger.append_job` reports it as `no_counterparty`) and a second
      supplier's same number will still meet it.
    """
    number = canonical_invoice_id(document_id) or document_id
    side, party = _SIDE.get(direction or ""), party_token(org_id, counterparty)
    if party is not None and aliases:
        party = aliases.get(party, party)  # a person said these two names are one supplier
    if is_unique_id(number) or side is None or party is None:
        return f"doc:{number}"
    return f"inv:{side}:{party}:{number}"


def lacks_counterparty(key: str) -> bool:
    """A key that rests on a free-form number alone (`doc:` and not a UUID or GİB number)."""
    return key.startswith("doc:") and not is_unique_id(key[4:])


def open_item_key(key: str) -> str:
    """`open_items.document_id` for a ledger key: the bare number, or the `inv:` key itself."""
    return key[4:] if key.startswith("doc:") else key


def key_party(key: str) -> tuple[str, str] | None:
    """(side, party token) of an `inv:` key; None for any other."""
    if not key.startswith("inv:"):
        return None
    parts = key.split(":", 3)
    return (parts[1], parts[2]) if len(parts) == 4 else None


_VARIANT = re.compile(r"~v[0-9a-f]{8}$")


def key_number(key: str) -> str | None:
    """The free-form document number inside an `inv:` or weak `doc:` key; None for UUID/GİB/other keys."""
    if key.startswith("inv:"):
        parts = key.split(":", 3)
        number = parts[3] if len(parts) == 4 else None
    elif key.startswith("doc:") and not is_unique_id(_VARIANT.sub("", key[4:])):
        number = key[4:]
    else:
        return None
    return _VARIANT.sub("", number) if number else None


def variant_key(key: str, amount_cents: int, day: str, raw_counterparty: str | None) -> str:
    """A second identity for a document that arrives under a key already held by a different one.

    Stable for one version of the document (amount, day, the words of its counterparty as written),
    so reading the same file again finds the same variant instead of making another.
    """
    words = " ".join(_TOKEN.findall((raw_counterparty or "").lower().translate(_TURKISH)))
    digest = hashlib.sha256(f"{amount_cents}|{day}|{words}".encode()).hexdigest()[:8]
    return f"{key}~v{digest}"
