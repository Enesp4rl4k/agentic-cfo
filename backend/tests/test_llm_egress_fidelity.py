"""Fidelity: the masking layer NEVER alters a figure. Seeded fuzz at the review's scale and larger.

A masking layer that changes an amount is worse than none: it corrupts what the model reads and gives false
assurance. So the rule is "a number is data unless there is positive evidence it is an identifier" (see
`llm_egress.figures` and `llm_egress.detectors`), and this file holds it:

* 200,000 realistic Turkish lines of amounts (tr-TR, en-US, plain dot or comma decimals, signs, currencies,
  percentages, bare integers of every length incl. 10/11 digits that pass the TCKN/VKN checksums), dates
  (separated, ISO, compact), times, THP account codes and document references (16-digit, 11-digit "05..."),
  next to the label-like words of financial text (Telefon faturası, Kart ödemesi, TC Ziraat, Vergi, Net kâr):
  ZERO lines changed;
* 60,000 lines that mix the same figures with real identifiers and known names: every figure survives
  verbatim, and restoring gives back the line byte for byte;
* every shape the review found broken, as fixed cases.
"""
from __future__ import annotations

import random
import re

import pytest

from app.platform.llm_egress import detectors as d
from app.platform.llm_egress.names import NameDictionary
from app.platform.llm_egress.pseudonymizer import Pseudonymizer

SEED = 20261127
NUMBER_LINES = 200_000
MIXED_LINES = 60_000

# The review's own failing cases, and the neighbouring shapes.
REVIEW_CASES = (
    "Net 41176993.01 TL", "Gider: 41176993.01", "| 20623047.57 |", "-20623047.57", "Toplam 59999999.99",
    "20000000.00 TL", "20240315 60 TL", "22032024 346980", "20623047.57 ve 2062304757", "Dekont 05321234567",
    "Net kâr 10000000146", "Gelir: 10000000146", "Havale 10000000146", "Satış cirosu 10000000146", "Kalan 10000000146",
    "Ref 4111111111111111", "4111111111111111 referanslı işlem", "Dekont no 05321234567 tutar 1.250,00 TL",
    "Telefon faturası 1.234,56 TL", "Kart ödemesi 4.111,11 TL", "TC Ziraat Bankası 12.500,00 TL", "Vergi 18.000 TL",
    "05.03.2024 tarihli 1.234.567,89 TL", "2024-03-05T14:05:33 1,234,567.89 USD", "%18 KDV 1.800,00",
    "120.01.001 Kasa hesabı 15.000,00", "Fatura No: GIB2024000000123 tutarı 3.450,00 TL", "−1.500,00 ₺",
)

_LABELLISH = (
    "Telefon faturası", "Kart ödemesi", "Kredi kartı ekstresi", "TC Ziraat Bankası", "Vergi ödemesi", "Vergi dairesi",
    "GSM operatörü", "Hesap özeti", "Plaka cezası", "IBAN'a gönderilen", "Cep telefonu taksidi", "Net kâr",
    "Gelir:", "Havale", "Satış cirosu", "Kalan", "Bakiye", "Toplam", "Tutar:", "Gider:", "KDV", "Stopaj", "Net",
    "Brüt maaş", "Kira", "Otel konaklama", "Telekom aboneliği", "Aras Kargo", "Dekont", "Ref", "Fiş no",
)
_TAIL = ("ödendi", "tahsil edildi", "hesaba geçti", "olarak kaydedildi", "", "(onaylandı)", "- kontrol edildi", "|")
_CUR = ("TL", "₺", "TRY", "USD", "EUR", "$", "€", "")


def _grouped(n: int, thousands: str, decimal: str, cents: int | None) -> str:
    body = f"{n:,}".replace(",", thousands)
    return body if cents is None else f"{body}{decimal}{cents:02d}"


def _amount(rng: random.Random) -> str:
    n = rng.choice((rng.randint(0, 999), rng.randint(1_000, 999_999), rng.randint(10**6, 10**8), rng.randint(10**8, 10**12)))
    cents = rng.randint(0, 99)
    kind = rng.randrange(9)
    sign = rng.choice(("", "", "", "-", "−", "+"))
    if kind == 0:
        s = _grouped(n, ".", ",", cents)
    elif kind == 1:
        s = _grouped(n, ",", ".", cents)
    elif kind == 2:
        s = f"{n}.{cents:02d}"
    elif kind == 3:
        s = f"{n},{cents:02d}"
    elif kind == 4:
        s = _grouped(n, " ", ",", cents)
    elif kind == 5:
        s = f"%{rng.randint(0, 100)}" if rng.random() < 0.5 else f"{rng.randint(0, 100)},{rng.randint(0, 9)}%"
        return s
    elif kind == 6:
        s = str(rng.randint(10**9, 10**11 - 1))  # bare 10-11 digit integers: many pass TCKN / VKN checksums
    elif kind == 7:
        s = str(n)
    else:
        s = _grouped(n, ".", ",", None)
    cur = rng.choice(_CUR)
    return f"{sign}{s} {cur}".strip() if rng.random() < 0.7 else f"{cur}{sign}{s}".strip()


def _date(rng: random.Random) -> str:
    y, m, day = rng.randint(1995, 2035), rng.randint(1, 12), rng.randint(1, 28)
    return rng.choice((
        f"{day:02d}.{m:02d}.{y}", f"{y}-{m:02d}-{day:02d}", f"{day:02d}/{m:02d}/{y % 100:02d}", f"{y}{m:02d}{day:02d}",
        f"{day:02d}{m:02d}{y}", f"{day}.{m}.{y}", f"{y}-{m:02d}-{day:02d} {rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}",
    ))


def _reference(rng: random.Random) -> str:
    return rng.choice((
        "".join(rng.choice("0123456789") for _ in range(16)),
        "05" + "".join(rng.choice("0123456789") for _ in range(9)),
        "".join(rng.choice("0123456789") for _ in range(rng.randint(6, 20))),
        f"GIB{rng.randint(2015, 2030)}{rng.randint(0, 10**9):09d}",
        f"{rng.randint(100, 999)}.{rng.randint(1, 99):02d}.{rng.randint(1, 999):03d}",
        f"{rng.randint(2015, 2030)}-{rng.randint(1, 999999):06d}",
    ))


def number_line(rng: random.Random) -> str:
    parts = [rng.choice(_LABELLISH), _amount(rng)]
    if rng.random() < 0.6:
        parts.insert(rng.randrange(len(parts) + 1), _date(rng))
    if rng.random() < 0.4:
        parts.insert(rng.randrange(len(parts) + 1), rng.choice(("Ref", "Dekont", "Fatura No:", "Belge no", "")) + " " + _reference(rng))
    if rng.random() < 0.3:
        parts.append(_amount(rng))
    line = " ".join(p for p in parts if p) + " " + rng.choice(_TAIL)
    return line.strip() if rng.random() < 0.8 else f"| {' | '.join(parts)} |"


def _bare_numbers(rng: random.Random) -> str:
    """Adversarial: numbers next to each other with no words at all (table cells, CSV)."""
    sep = rng.choice((" ", ";", " | ", "\t", ", "))
    return sep.join(rng.choice((_amount, _date, _reference))(rng) for _ in range(rng.randint(2, 5)))


@pytest.fixture(scope="module")
def pseudo() -> Pseudonymizer:
    nd = NameDictionary()
    for label, name in (("CP", "Kanarya Yapı Malzemeleri A.Ş."), ("CP", "Güneş Ticaret A.Ş."),
                        ("PER", "Selin Aksoy"), ("CO", "Menekşe Tekstil Sanayi A.Ş.")):
        nd.add(label, name, person=label == "PER")
    return Pseudonymizer(nd)


@pytest.mark.parametrize("line", REVIEW_CASES)
def test_the_reviews_cases_are_not_touched(line: str, pseudo: Pseudonymizer) -> None:
    assert pseudo.mask(line) == line


def test_two_different_originals_never_share_a_placeholder_and_restore_is_exact() -> None:
    p = Pseudonymizer(NameDictionary())
    a, b = "Tel: 0532 987 65 43", "GSM: 05329876543"
    masked = p.mask(f"{a} / {b}")
    tokens = re.findall(r"\[\[[^\]]+\]\]", masked)
    assert len(tokens) == 2 and tokens[0] != tokens[1]
    assert p.restore(masked) == f"{a} / {b}"


def test_200000_figure_lines_zero_alterations(pseudo: Pseudonymizer) -> None:
    rng = random.Random(SEED)
    changed: list[str] = []
    for i in range(NUMBER_LINES):
        line = _bare_numbers(rng) if i % 5 == 0 else number_line(rng)
        if pseudo.mask(line) != line:
            changed.append(line)
    assert changed == [], f"{len(changed)} of {NUMBER_LINES} lines altered, e.g. {changed[:5]}"


def _identifier(rng: random.Random) -> str:
    bban = "".join(rng.choice("0123456789") for _ in range(22))
    check = 98 - int("".join(str(int(c, 36)) for c in bban + "TR00")) % 97
    iban = f"TR{check:02d}{bban}"
    return rng.choice((
        f"IBAN {iban}", f"IBAN: {' '.join(iban[i:i + 4] for i in range(0, 26, 4))}", "Tel: 0532 987 65 43",
        "TCKN 10000000146", "kanarya.muhasebe@zumrut.example", "Kart No: 4111 1111 1111 1111", "+90 212 555 12 34",
    ))


def test_60000_mixed_lines_keep_every_figure_and_restore_byte_for_byte() -> None:
    rng = random.Random(SEED + 1)
    names = ("Kanarya Yapı Malzemeleri A.Ş.", "KANARYA YAPI MALZEMELERİ", "Selin Aksoy", "Aksoy'un", "Güneş Ticaret")
    nd = NameDictionary()
    nd.add("CP", "Kanarya Yapı Malzemeleri A.Ş.")
    nd.add("CP", "Güneş Ticaret A.Ş.")
    nd.add("PER", "Selin Aksoy", person=True)
    bad: list[str] = []
    for _ in range(MIXED_LINES):
        figures = [_amount(rng), _date(rng), rng.choice(("Ref", "Dekont")) + " " + _reference(rng)]
        parts = [rng.choice(names), *figures, _identifier(rng), rng.choice(_LABELLISH)]
        rng.shuffle(parts)
        line = " ".join(parts)
        p = Pseudonymizer(nd)
        masked = p.mask(line)
        if p.restore(masked) != line or any(f not in masked for f in figures):
            bad.append(line)
    assert bad == [], f"{len(bad)} of {MIXED_LINES} mixed lines lost a figure or did not restore exactly: {bad[:3]}"


def test_identifiers_with_evidence_are_still_found() -> None:
    """Fidelity does not mean blindness: each type is found where the evidence is there."""
    cases = {
        "IBAN TR33 0006 1005 1978 6457 8413 26": d.IBAN, "tr330006100519786457841326": d.IBAN,
        "TR33-0006-1005-1978-6457-8413-26": d.IBAN, "IBAN: 33 0006 1005 1978 6457 8413 26": d.IBAN,
        "TR33 0006 1005\n1978 6457 8413 26": d.IBAN, "IBAN 0006100519786457841326"[:5] + "0006 1 0000000000000000 01": None,
        "Kart No: 4111111111111111": d.PAN, "4111 1111 1111 1111": d.PAN, "T.C. Kimlik No: 10000000146": d.TCKN,
        "Tel: 0532 987 65 43": d.PHONE, "+905329876543": d.PHONE, "(0212) 555 12 34": d.PHONE,
        "GSM 5329876543": d.PHONE, "info@ışık.com.tr": d.EMAIL, "user@münchen.de": d.EMAIL, "Plaka: 34 ABC 123": d.PLATE,
        "Hesap No: 12345678": d.ACCOUNT_NO, '"tckn": "10000000146"': d.TCKN,
    }
    for text, label in cases.items():
        found = [s.label for s in d.find_identifiers(text)]
        if label is not None:
            assert found and found[0] == label, f"{text!r}: {found}"
