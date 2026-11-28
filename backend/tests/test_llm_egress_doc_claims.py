"""The statements of docs/kvkk/yapay-zeka-veri-akisi.md that a lawyer will rely on, tied to the code's behaviour.

Each test reads the sentence from the document AND checks the behaviour it describes, so neither can change alone:
the measured name rates, the identifier shapes that are deliberately NOT masked (and their masked counterparts),
the exact limit of the "amounts are never changed" guarantee, the number of guard mutations, and the audit error
format. Three statements of the previous version were wrong (amounts "never changed", "a bare digit run is never
an identifier", "no other code can build a client"); the first two are pinned below, the third by
`test_llm_egress_provider_helpers.py` (whose mutation count is pinned here).
"""
from __future__ import annotations

import functools
import random
import re
from pathlib import Path

import pytest

from app.platform.llm_egress.pseudonymizer import Pseudonymizer

DOC = Path(__file__).resolve().parents[2] / "docs" / "kvkk" / "yapay-zeka-veri-akisi.md"


@functools.cache
def _doc() -> str:
    return " ".join(DOC.read_text(encoding="utf-8").split())  # line breaks of the markdown do not matter


def _pct(x: float) -> str:
    return f"%{x * 100:.1f}".replace(".", ",")


@functools.cache
def _measured() -> tuple[float, float]:
    from tests.test_llm_egress_names import _measure

    return _measure(random.Random(7), 5000)


def test_the_documented_name_rates_are_the_measured_ones() -> None:
    over, under = _measured()
    doc = _doc()
    assert f"**{_pct(over)}**; adın kaçırılması **{_pct(under)}**" in doc, (over, under)
    assert f"ölçülen oran {_pct(under)}" in doc and f"kalma oranı {_pct(under)}'dir" in doc
    assert f"yanlışlıkla maskelenme oranı {_pct(over)}'dır" in doc


# (example, must it be masked?): the document's "Bilinçli olarak maskelenmeyen kimlik biçimleri" list, both sides.
NOT_MASKED_BY_DESIGN = {
    "unlabelled VKN": ("Ödeme 7291045386 numaralı firmaya", False),
    "unlabelled 16-digit card": ("İşlem 4111111111111111 onaylandı", False),
    "unlabelled plate": ("34 ABC 123 otoparkta", False),
    "compact mobile": ("Arayan 05321234567 idi", False),
    "compact mobile without 0": ("Arayan 5321234567 idi", False),
    "dotted mobile": ("Arayan 0532.123.45.67 idi", False),
    "grouped TCKN without a label": ("Numara 100 000 001 46 idi", False),
    "labelled VKN": ("VKN: 7291045386", True),
    "labelled card": ("Kart No: 4111111111111111", True),
    "printed card grouping": ("4111 1111 1111 1111 ile ödendi", True),
    "labelled plate": ("Plaka: 34 ABC 123", True),
    "+90 mobile": ("Arayan +90 532 123 45 67 idi", True),
    "spaced mobile": ("Arayan 0532 123 45 67 idi", True),
    "labelled compact mobile": ("Tel: 05321234567", True),
    "unlabelled TCKN": ("Kişi 10000000146 numaralı", True),
    "labelled grouped TCKN": ("Kimlik: 100 000 001 46", True),
}


def test_the_documented_unmasked_shapes_are_listed_in_the_document() -> None:
    doc = _doc()
    for phrase in ("etiketsiz vergi kimlik numarası (VKN)", "etiketsiz 16 haneli kart numarası", "araç plakası",
                   "`+90` öneki ya da gruplar arası boşluk/tire olmadan yazılmışsa", "(`0532.123.45.67`)",
                   "önünde kimlik etiketi"):
        assert phrase in doc, phrase


@pytest.mark.parametrize("case", sorted(NOT_MASKED_BY_DESIGN))
def test_the_documented_unmasked_shapes_behave_as_documented(case: str) -> None:
    text, masked = NOT_MASKED_BY_DESIGN[case]
    out = Pseudonymizer().mask(text)
    assert (out != text) is masked, f"{case}: {out!r}"


def test_the_amount_guarantee_is_stated_with_its_exact_limit() -> None:
    doc = _doc()
    assert "hiçbir zaman değiştirilmez; 200.000+" not in doc, "the old, unconditional claim is back"
    assert "Çıplak bir rakam dizisi hiçbir zaman kimlik sayılmaz" not in doc, "the old, contradictory claim is back"
    assert "**Güvencenin tam sınırı:**" in doc and "tutar adlı bir JSON / sözlük / `anahtar=değer` alanının değeri" in doc
    # the cue cases: never changed
    for text in ('{"amount": "10000000146"}', '{"tutar": 10000000146}', "toplam_borc=10000000146", "Net 10000000146 TL",
                 "| -10000000146 | 05.03.2024 |", '{"amountCents": "10000000146"}'):
        assert Pseudonymizer().mask(text) == text, text
    # the documented exception: no cue at all, TCKN checksum holds -> may be masked (restored exactly)
    p = Pseudonymizer()
    text = 'Açıklama: "10000000146"'
    assert "`Açıklama: \"10000000146\"`" in doc
    masked = p.mask(text)
    assert masked != text and p.restore(masked) == text
    # an identifier key is not an amount key
    assert "`credit_card_number` bir karttır" in doc


def test_the_guard_mutation_count_in_the_document_is_the_tested_one() -> None:
    from tests import test_llm_egress_provider_helpers as guard

    others = (len(guard.AGENT_MUTATIONS) - 1) + len(guard.GATEWAY_MUTATIONS) + 2  # + re-export + new-helper tests
    assert f"şimdi bu ve {others} benzer değişiklik" in _doc()
    assert f"inceleme mutasyonu ve {others} benzeri" in _doc()


def test_the_audit_error_format_in_the_document_is_the_stored_one() -> None:
    from app.platform.llm_egress.audit import safe_error

    doc = _doc()
    for code in ("TimeoutError:timeout", "APIStatusError:http_429", "RuntimeError:failed"):
        assert f"`{code}`" in doc and safe_error(code) == code
    assert "hata **iletisi saklanmaz**" in doc
    assert safe_error("ValueError: Selin Aksoy 1.234,56 TL") == "ValueError"


def test_no_reassurance_beyond_what_is_tested() -> None:
    """The residual-risk section must keep the plain statements a lawyer needs."""
    section = _doc().split("## Kalan risk (düz sözle)")[1].split("## Hangi dosya neyi sınar")[0]
    for must in ("Maskeleme bir güvence değildir", "Okunan belgede ilk kez geçen adlar olduğu gibi gider",
                 "Her zaman gidenler", "Gömmeler (embedding)", "Sağlayıcının tuttuğu veri bu çalışmanın dışındadır",
                 "Ham kip (`raw`) her şeyi gönderir", "gerçek müşteri metninde ölçülmemiştir"):
        assert must in section, must
    assert not re.search(r"(?i)\b(tamamen güvenli|hiçbir kişisel veri gitmez|garanti eder)\b", section)


def test_the_label_wins_over_a_minus_sign_as_documented() -> None:
    doc = _doc()
    assert "Eksi işareti tek başına tutar kanıtı değildir" in doc and "etiket kazanır" in doc
    for text, value in (("TC -10000000146", "10000000146"), ("Kimlik No:-10000000146", "10000000146"),
                        ('{"tckn": "-10000000146"}', "10000000146"), ("Tel:-0532 123 45 67", "5321234567"),
                        ("Vergi No:-7291045386", "7291045386")):
        assert value not in re.sub(r"\D", "", Pseudonymizer().mask(text)), text
    assert Pseudonymizer().mask("| -10000000146 | 05.03.2024 |") == "| -10000000146 | 05.03.2024 |"


def test_bracketless_codes_of_another_nonce_stay_as_documented() -> None:
    assert "bu çağrının ekini" in _doc() and "**olduğu gibi kalır**" in _doc()
    p = Pseudonymizer()
    for code in ("CO_A12_3", "ACCT_TRY_100", "PLATE_34A_1234"):
        assert p.restore(code) == code and p.restore_strict(code) == code

