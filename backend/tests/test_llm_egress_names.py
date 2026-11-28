"""Names, IBANs and e-mails in the spellings the review found leaking; over-masking measured; time bounded.

Review: 11 of 29 name variants leaked (a suffix with no apostrophe, a line break or extra spaces inside a name,
a first name or surname alone), 4 of 8 IBAN variants, 5 of 6 e-mails with a non-ASCII domain. Each is a case
here and must be masked. The single-word rule for ordinary words ("Güneş", "Deniz", "Demir") is measured on
synthetic Turkish financial text: the over-masking (ordinary words replaced) and under-masking (names missed)
rates are asserted below the bounds documented in docs/kvkk/yapay-zeka-veri-akisi.md.
"""
from __future__ import annotations

import random
import re
import time

import pytest

from app.platform.llm_egress import detectors as d
from app.platform.llm_egress.names import NameDictionary
from app.platform.llm_egress.pseudonymizer import Pseudonymizer


def _dictionary() -> NameDictionary:
    nd = NameDictionary()
    for name in ("Işık Gıda Ltd. Şti.", "Yıldız Holding A.Ş.", "Güneş Ticaret A.Ş.", "ACME Lojistik",
                 "Karvesta Yapı Malzemeleri A.Ş.", "Usta \"Gıda\" Ltd. Şti."):
        nd.add("CP", name)
    for person in ("Selin Aksoy", "Ahmet Yılmaz", "Deniz Demir"):
        nd.add("PER", person, person=True)
    return nd


# (text, the substring that must not survive)
NAME_VARIANTS = (
    ("Ödeme Işık Gıdaya yapıldı.", "Işık Gıda"), ("Fatura Yıldız Holdingin adına.", "Yıldız Holding"),
    ("Dün Güneşe ödendi.", "Güneş"), ("Bakiye ACMEye aktarıldı.", "ACME"), ("Dosya Yılmazın masasında.", "Yılmaz"),
    ("Ödemeyi Yılmazlar onayladı.", "Yılmaz"), ("Tutar Işık\nGıda hesabına.", "Işık\nGıda"),
    ("Tutar Işık      Gıda hesabına.", "Işık      Gıda"), ("Tutar Işık​Gıda hesabına.", "Işık​Gıda"),
    ("Tutar Iş​ık Gıda hesabına.", "Iş​ık Gıda"), ("Onayı Aksoy verdi.", "Aksoy"),
    ("Onayı dün Selin verdi.", "Selin"), ("Rapor Aksoy'a gitti.", "Aksoy"), ("Rapor Aksoya gitti.", "Aksoy"),
    ("KARVESTA YAPI MALZEMELERİ A.Ş. ödemesi", "KARVESTA YAPI"), ("karvesta yapi malzemeleri faturasi", "karvesta yapi"),
    ("Karvesta Yapı Malzemeleri'ne havale", "Karvesta Yapı"), ("Karvesta Yapı Malzemelerine havale", "Karvesta Yapı"),
    ("Isik Gida Ltd Sti faturasi", "Isik Gida"), ("IŞIK GIDA LTD. ŞTİ.", "IŞIK GIDA"), ("ışık gıdanın borcu", "ışık gıda"),
    ("Işık Gıda'nın borcu", "Işık Gıda"), ("Yıldız Holding'e", "Yıldız Holding"), ("Ahmet\nYılmaz imzaladı", "Ahmet\nYılmaz"),
    ("AHMET YILMAZ imzaladı", "AHMET YILMAZ"), ("ahmet yılmaz imzaladı", "ahmet yılmaz"), ("Selin Aksoyun onayı", "Selin Aksoy"),
    ("Toplantıya Deniz Demir katıldı.", "Deniz Demir"), ("Usta \"Gıda\" Ltd. Şti. faturası", "Usta \"Gıda\""),
    # the final review's leaks: hyphenation across a line break, a Cyrillic / Greek look-alike letter in a first name
    ("Ödeme Iş-\nık Gıda hesabına", "Iş-\nık Gıda"), ("Ödeme Işık Gı-\r\nda Ltd. Şti. adına", "Işık Gı-\r\nda"),
    ("Sözleşmeyi Ah-\nmet Yılmaz imzaladı", "Ah-\nmet"), ("Onay Аhmet Yılmaz verdi", "Аhmet"),
    ("Onay Аhmet verdi", "Аhmet"), ("Rapor Sеlin Aksoy'a gitti", "Sеlin"),
    ("Onay Αhmet Yılmaz verdi", "Αhmet"), ("Ödeme Işık-\nGıda hesabına", "Işık-\nGıda"),
)

# Must NOT be masked: the folding is for matching only, and never invents a match.
NOT_NAMES = (
    "iş-\nlem tamamlandı", "Москва ofisi kapandı", "Дмитрий aradı", "Ахмет",  # real Cyrillic words stay
    "gı-\nda fiyatları arttı",  # a hyphenated ordinary word that is not a known name
)


@pytest.mark.parametrize("text", NOT_NAMES)
def test_folding_does_not_invent_a_name(text: str) -> None:
    assert Pseudonymizer(_dictionary()).mask(text) == text


def test_a_labelled_tckn_in_groups_is_masked_and_an_unlabelled_one_is_not() -> None:
    for text in ("Kimlik: 100 000 001 46", "T.C. Kimlik No: 100-000-001-46", "TCKN 100 000 00146", "tc_kimlik_no: 100 000 001 46"):
        masked = Pseudonymizer().mask(f"{text} ile kayıt")
        assert "[[TCKN_" in masked and "001" not in masked, masked
    for text in ("Tutar 100 000 001 46", "Ref 100 000 001 46", "100 000 001 46", "Kimlik: 100 000 001,46"):
        assert Pseudonymizer().mask(text) == text, text  # no label, or not a TCKN shape: a number stays a number

IBAN = "TR330006100519786457841326"
IBAN_VARIANTS = (
    IBAN, " ".join(IBAN[i:i + 4] for i in range(0, 26, 4)), "-".join(IBAN[i:i + 4] for i in range(0, 26, 4)),
    IBAN.lower(), f"{IBAN[:10]}\n{IBAN[10:]}", f"IBAN: {IBAN[2:]}", f"IBAN {' '.join(IBAN[2:][i:i + 4] for i in range(0, 24, 4))}",
    f"IBAN: {IBAN[4:]}",
)
EMAILS = ("info@ışık.com.tr", "user@münchen.de", "muhasebe@gıda-dünyası.com", "satış@örnek.com.tr",
          "karvesta.muhasebe@zemtrak-nakliyat.example", "ali@xn--k-7ga.com")


@pytest.mark.parametrize(("text", "name"), NAME_VARIANTS)
def test_every_name_variant_the_review_found_is_masked(text: str, name: str) -> None:
    p = Pseudonymizer(_dictionary())
    masked = p.mask(text)
    assert name not in masked and "[[" in masked, masked
    assert p.restore(masked) == text  # exact substring back, never the canonical spelling


@pytest.mark.parametrize("text", IBAN_VARIANTS)
def test_every_iban_variant_is_masked(text: str) -> None:
    found = d.find_identifiers(f"Ödeme {text} hesabına")
    assert [s.label for s in found] == [d.IBAN], text
    digits = re.sub(r"\D", "", IBAN[4:])
    masked = Pseudonymizer().mask(f"Ödeme {text} hesabına")
    assert digits not in re.sub(r"\D", "", masked)


@pytest.mark.parametrize("email", EMAILS)
def test_every_email_with_a_unicode_or_idn_domain_is_masked(email: str) -> None:
    masked = Pseudonymizer().mask(f"Yanıtı {email} adresine yaz.")
    assert email not in masked and "[[MAIL_" in masked


def test_an_ordinary_word_is_not_a_name_unless_it_reads_as_one() -> None:
    p = Pseudonymizer(_dictionary())
    assert p.mask("güneş enerjisi paneli alındı") == "güneş enerjisi paneli alındı"
    assert p.mask("Güneş enerjisi paneli alındı") == "Güneş enerjisi paneli alındı"  # sentence start: a word
    assert p.mask("deniz taşımacılığı ve demir çelik alımı") == "deniz taşımacılığı ve demir çelik alımı"
    assert "Güneş" not in p.mask("Ödemeyi Güneş'e yaptık")
    assert "Güneş" not in p.mask("ödemeyi dün Güneş yaptı")
    assert "Güneş" not in p.mask("Güneş Ticaret A.Ş. ile görüşüldü")


# ── measured over- and under-masking of the single-word rule ────────────────

_ORDINARY = (
    "{w} enerjisi yatırımı tamamlandı", "yeni {w} paneli için teklif alındı", "{w} taşımacılığı maliyeti arttı",
    "bu ay {w} fiyatları yükseldi", "{W} çelik alımı ertelendi", "kaya gibi sağlam bir nakit pozisyonu",
    "{w} yolu ile ihracat yapıldı", "Mart ayında {w} kaynaklı gider oluştu", "{W} ışığı altında ürün depolandı",
)
_COMMON = ("güneş", "deniz", "demir", "yıldız", "kaya", "çelik", "doğan", "ateş", "bulut", "toprak")
_NAMED = (
    "Ödeme dün {n} tarafından onaylandı.", "Fatura {n}'e gönderildi.", "{n} ile toplantı yapıldı.",
    "Bu hafta {n} aradı.", "Tahsilat {n} hesabına geçti.", "Sözleşmeyi {n} imzaladı.",
)


def _measure(rng: random.Random, n: int) -> tuple[float, float]:
    nd = NameDictionary()
    nd.add("CP", "Güneş Ticaret A.Ş.")
    nd.add("CP", "Yıldız Holding A.Ş.")
    nd.add("PER", "Deniz Demir", person=True)
    nd.add("PER", "Mehmet Kaya", person=True)
    nd.add("PER", "Selin Aksoy", person=True)
    ordinary_total = ordinary_masked = named_total = named_missed = 0
    for _ in range(n):
        w = rng.choice(_COMMON)
        text = rng.choice(_ORDINARY).format(w=w, W=w.capitalize())
        ordinary_total += 1
        ordinary_masked += "[[" in Pseudonymizer(nd).mask(text)
        name = rng.choice(("Güneş", "Deniz", "Demir", "Kaya", "Aksoy", "Selin", "Deniz Demir", "Güneş Ticaret"))
        sentence = rng.choice(_NAMED).format(n=name)
        named_total += 1
        named_missed += name.split()[0] in Pseudonymizer(nd).mask(sentence)
    return ordinary_masked / ordinary_total, named_missed / named_total


def test_single_word_rule_over_and_under_masking_measured() -> None:
    over, under = _measure(random.Random(7), 5000)
    # measured (seed 7, 5,000 + 5,000 sentences): see docs/kvkk/yapay-zeka-veri-akisi.md
    assert over <= 0.01, f"ordinary words masked: {over:.2%}"
    assert under <= 0.25, f"names missed: {under:.2%}"


# ── bounded time on a large dictionary ───────────────────────────────────────

def _big_dictionary(rng: random.Random, size: int = 5000) -> NameDictionary:
    syll = ("ka", "ra", "ya", "pı", "me", "nek", "şe", "zü", "rüt", "na", "lo", "jis", "tik", "gı", "da", "ışı", "yıl")
    nd = NameDictionary()
    for i in range(size):
        words = ["".join(rng.choice(syll) for _ in range(rng.randint(2, 4))).capitalize() for _ in range(rng.randint(1, 4))]
        nd.add("CP" if i % 3 else "PER", " ".join(words) + rng.choice(("", " A.Ş.", " Ltd. Şti.")), person=i % 3 == 0)
    return nd


@pytest.mark.parametrize("length", [8_000, 100_000])
def test_time_is_bounded_with_5000_names(length: int) -> None:
    rng = random.Random(3)
    nd = _big_dictionary(rng)
    words = ("ödeme", "Karapı", "1.234,56", "TL", "\n", "Işık", "a" * 40, "Kayaka'ya", "     ", "15.03.2026")
    text = " ".join(rng.choice(words) for _ in range(length // 6))[:length]
    adversarial = ("Ka " * (length // 3))[:length]  # one first word, over and over, never a full name
    for sample in (text, adversarial):
        start = time.perf_counter()
        Pseudonymizer(nd).mask(sample)
        assert time.perf_counter() - start < (2.0 if length <= 8_000 else 10.0)
