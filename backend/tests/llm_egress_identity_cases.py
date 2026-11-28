"""Labelled identifiers in every spelling the masking must catch: type x label x separator x sign x shape.

Used by `test_llm_egress_fidelity.py` (the property "a labelled identifier never leaves", measured over the whole
product, not sampled) and by `llm_egress_master_masked.py` (the regression set computed against master `3b3c83f`).
A case is (text, the identifier's digits/letters that must not survive in the masked text).
"""
from __future__ import annotations

from itertools import product

TCKN = "10000000146"
VKN = "7291045386"  # tests.llm_egress_harness.VKN (a valid tax number)
IBAN = "TR330006100519786457841326"
CARD = "4111111111111111"

# type -> (values as written, prose labels, JSON / dict keys)
TYPES: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    "TCKN": ((TCKN,), ("TCKN", "T.C. Kimlik No", "TC", "Kimlik No", "Kimlik"), ("tckn", "tc_kimlik_no", "kimlik_no")),
    "VKN": ((VKN,), ("VKN", "Vergi No", "Vergi Kimlik No"), ("vkn", "vergi_no", "tax_id")),
    "TEL": (("0532 123 45 67", "05321234567"), ("Tel", "GSM", "Telefon", "Cep"), ("phone", "telefon", "gsm")),
    "IBAN": ((IBAN, "TR33 0006 1005 1978 6457 8413 26"), ("IBAN",), ("iban",)),
    "CARD": ((CARD, "4111 1111 1111 1111"), ("Kart No", "Kart"), ("card_no", "kart_no")),
}
SEPARATORS = (": ", "=", " - ", " – ", ":-", ": -", " ", ":")
SIGNS = ("", "-")


def _core(value: str) -> str:
    return "".join(c for c in value if c.isalnum()).upper()


def identity_cases() -> list[tuple[str, str]]:
    cases: list[tuple[str, str]] = []
    for _type, (values, labels, keys) in TYPES.items():
        for value, sign in product(values, SIGNS):
            core = _core(value)
            for label, sep in product(labels, SEPARATORS):
                cases.append((f"{label}{sep}{sign}{value}", core))
                cases.append((f"Ödeme kaydı; {label}{sep}{sign}{value} ile eşleşti.", core))
            for key in keys:
                cases.append((f'{{"{key}": "{sign}{value}"}}', core))
                cases.append((f"{{'{key}': '{sign}{value}'}}", core))
                cases.append((f"{key}={sign}{value}", core))
                if value.isdigit():
                    cases.append((f'{{"{key}": {sign}{value}, "tutar": 1500}}', core))
    return cases


def leaked(masked: str, core: str) -> bool:
    return core in _core(masked)
