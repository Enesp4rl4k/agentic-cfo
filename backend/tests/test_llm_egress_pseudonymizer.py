"""Detection and pseudonymisation: checksums, context rules, Turkish casing, round trip, hallucinations.

The invariant behind every test here: amounts, dates and currencies are never masked or altered.
"""
from __future__ import annotations

import random
import re

from app.platform.llm_egress import detectors as d
from app.platform.llm_egress.names import NameDictionary, fold
from app.platform.llm_egress.pseudonymizer import (
    COMPANY,
    COUNTERPARTY,
    PERSON,
    UNKNOWN_NAME,
    UNKNOWN_VALUE,
    Pseudonymizer,
    StreamRestorer,
)


def make_iban(bban: str = "0006200000000000000001", country: str = "TR") -> str:
    check = 98 - int("".join(str(int(c, 36)) for c in bban + country + "00")) % 97
    return f"{country}{check:02d}{bban}"


def make_vkn(prefix9: str = "123456789") -> str:
    return next(prefix9 + str(c) for c in range(10) if d.vkn_ok(prefix9 + str(c)))


IBAN = make_iban()
TCKN = "10000000146"
VKN = make_vkn()
PAN = "4111111111111111"


def spaced(iban: str) -> str:
    return " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))


def labels(text: str) -> list[str]:
    return [s.label for s in d.find_identifiers(text)]


# ── checksums ────────────────────────────────────────────────────────────────

def test_iban_checksum_true_and_false() -> None:
    assert d.iban_ok(IBAN)
    assert d.iban_ok("DE89370400440532013000") and d.iban_ok("GB82WEST12345698765432")
    assert not d.iban_ok(IBAN[:-1] + "2")                  # one digit off: mod 97 fails
    assert not d.iban_ok("TR" + IBAN[2:] + "0")            # a Turkish IBAN is exactly 26 characters
    assert not d.iban_ok("1234567890123456789012345")


def test_tckn_vkn_luhn_checksums() -> None:
    assert d.tckn_ok(TCKN) and not d.tckn_ok("10000000147") and not d.tckn_ok("01234567890")
    assert d.vkn_ok(VKN) and not d.vkn_ok(VKN[:-1] + str((int(VKN[-1]) + 1) % 10))
    assert d.luhn_ok(PAN) and not d.luhn_ok("4111111111111112")


# ── identifiers: true positives ──────────────────────────────────────────────

def test_iban_is_found_spaced_unspaced_lowercase_and_general() -> None:
    for text in (f"IBAN {IBAN} tutar", f"IBAN {spaced(IBAN)} tutar", f"iban {IBAN.lower()} tutar"):
        assert labels(text) == ["IBAN"], text
    assert labels("DE89 3704 0044 0532 0130 00") == ["IBAN"]
    span = d.find_identifiers(f"x {spaced(IBAN)} y")[0]
    assert f"x {spaced(IBAN)} y"[span.start:span.end] == spaced(IBAN)  # the span is exactly the IBAN, no trailing word


def test_an_iban_with_a_wrong_check_is_left_alone() -> None:
    assert labels(f"IBAN {IBAN[:-1]}2 ödendi") == []


def test_tckn_needs_its_checksum_and_a_non_amount_context() -> None:
    assert labels(f"T.C. Kimlik No: {TCKN}") == ["TCKN"]
    assert labels(f"sahibi {TCKN} olan kişi") == ["TCKN"]
    assert labels("T.C. Kimlik No: 10000000147") == []                      # checksum false
    assert labels(f"Tutar: {TCKN}") == []                                    # an amount field
    assert labels(f"{TCKN} TL ödendi") == []                                 # a currency next to it
    assert labels(f"toplam {TCKN},00") == []                                 # decimal comma: an amount
    assert labels(f"1.{TCKN}") == [] and labels(f"{TCKN}.50") == []          # glued to amount punctuation


def test_vkn_needs_checksum_and_its_label() -> None:
    assert labels(f"Vergi No: {VKN}") == ["VKN"] and labels(f"VKN {VKN}") == ["VKN"]
    assert labels(f"referans {VKN}") == []                                   # ten digits without the label: a document no.
    assert labels(f"VKN {VKN[:-1]}{(int(VKN[-1]) + 1) % 10}") == []          # checksum false


def test_card_numbers_by_luhn_with_context_or_shape() -> None:
    assert labels("kart 4111 1111 1111 1111") == ["KART"]
    assert labels("4111-1111-1111-1111") == ["KART"]
    assert labels(f"pan {PAN}") == ["KART"] and labels(PAN) == ["KART"]       # a 16-digit run with a card prefix
    assert labels("4111 1111 1111 1112") == []                               # Luhn false
    assert labels("1700000000003") == []                                      # an epoch-millisecond timestamp


def test_turkish_phone_formats_email_and_plate() -> None:
    for number in ("0532 123 45 67", "+90 532 123 45 67", "0 (532) 123 45 67", "0532-123-45-67", "05321234567",
                   "0212 555 12 34", "tel: 5321234567"):
        assert labels(f"ara {number} lütfen") == ["TELEFON"], number
    assert labels("5321234567") == []                                         # bare ten digits: not claimed
    assert labels("yaz ahmet.k+fatura@firma.com.tr şimdi") == ["E_POSTA"]
    assert labels("araç 34 ABC 123 geldi") == ["PLAKA"] and labels("34 ABC 123") == ["PLAKA"]
    assert labels("05 MAR 24 tarihli") == [] and labels("12 TL 100") == []   # a date and an amount are not plates


def test_account_number_after_its_label() -> None:
    assert labels("Hesap No: 12345678 aidat") == ["HESAP_NO"]


# ── amounts, dates, currencies are never touched ─────────────────────────────

def test_amounts_dates_and_currencies_are_byte_identical_through_a_round_trip() -> None:
    rng = random.Random(7)
    lines = []
    for _ in range(400):
        whole = rng.randint(1, 10 ** rng.randint(1, 13))
        amount = f"{whole:,}".replace(",", ".") + f",{rng.randint(0, 99):02d}"
        lines.append(f"{rng.randint(1, 28):02d}.{rng.randint(1, 12):02d}.2026 {amount} TL fatura {rng.randint(1, 99999)}")
        lines.append(f"{whole} kuruş; tutar {whole}.{rng.randint(0, 99):02d} USD; 2026-0{rng.randint(1, 9)}-1{rng.randint(0, 9)}")
    text = "\n".join(lines)
    p = Pseudonymizer(None)
    assert p.mask(text) == text and p.total == 0
    assert p.restore(text) == text


def test_amounts_survive_next_to_masked_names_and_identifiers() -> None:
    nd = NameDictionary()
    nd.add(COUNTERPARTY, "Atlas Lojistik A.Ş.")
    text = f"Atlas Lojistik A.Ş. 1.234.567,89 TL, IBAN {IBAN}, 15.03.2026, 250,00 EUR, TC {TCKN}"
    p = Pseudonymizer(nd)
    masked = p.mask(text)
    numerals = r"\d{1,3}(?:\.\d{3})*,\d{2}|\d{2}\.\d{2}\.\d{4}"
    assert re.findall(numerals, masked) == re.findall(numerals, text)
    assert "TL" in masked and "EUR" in masked
    assert "Atlas" not in masked and IBAN not in masked and TCKN not in masked
    assert re.findall(numerals, p.restore(masked)) == re.findall(numerals, text)


# ── known names: Turkish casing and legal suffixes ───────────────────────────

def dictionary() -> NameDictionary:
    nd = NameDictionary()
    nd.add(COMPANY, "Yıldız Tekstil Ltd. Şti.")
    nd.add(COUNTERPARTY, "Atlas Lojistik Ticaret A.Ş.")
    nd.add(COUNTERPARTY, "Işık İnşaat San. ve Tic. Ltd. Şti.")
    nd.add(PERSON, "Ahmet Yılmaz")
    return nd


def test_fold_is_length_preserving_and_handles_dotted_and_dotless_i() -> None:
    for s in ("İSTANBUL", "ışık", "Işık İnşaat", "ÇAĞRI Öğüt Şükrü", "Éclair"):
        assert len(fold(s)) == len(s)
    assert fold("İI ıi") == "ii ii" and fold("ŞĞÜÖÇ") == "sguoc"


def test_a_known_name_matches_in_any_turkish_casing_with_or_without_suffix() -> None:
    nd = dictionary()
    for spelling in ("IŞIK İNŞAAT", "ışık inşaat", "Isik Insaat", "ISIK INSAAT LTD STI", "Işık İnşaat San. ve Tic. Ltd. Şti.",
                     "işik inşaat ltd.şti."):
        p = Pseudonymizer(nd)
        masked = p.mask(f"{spelling} ödemesi")
        assert masked == f"[{COUNTERPARTY}_1] ödemesi", (spelling, masked)
    for spelling in ("ATLAS LOJİSTİK", "atlas lojistik a.ş.", "Atlas Lojistik Ticaret AŞ", "Atlas Lojistik Ticaret"):
        assert Pseudonymizer(nd).mask(spelling) == f"[{COUNTERPARTY}_1]", spelling


def test_word_boundaries_and_turkish_apostrophe_suffixes() -> None:
    nd = dictionary()
    assert Pseudonymizer(nd).mask("Atlasyan Lojistikçi") == "Atlasyan Lojistikçi"   # not the same word
    assert Pseudonymizer(nd).mask("Atlas Lojistik'e ödendi") == f"[{COUNTERPARTY}_1]'e ödendi"
    assert Pseudonymizer(nd).mask("Ahmet Yılmaz'a") == f"[{PERSON}_1]'a"
    assert Pseudonymizer(nd).mask("Ahmet Kaya") == "Ahmet Kaya"                       # not in the books


def test_placeholders_are_typed_numbered_by_first_appearance_and_stable_within_a_call() -> None:
    p = Pseudonymizer(dictionary())
    out = p.mask("Işık İnşaat, Atlas Lojistik, tekrar IŞIK İNŞAAT; Yıldız Tekstil; Ahmet Yılmaz")
    assert out == (f"[{COUNTERPARTY}_1], [{COUNTERPARTY}_2], tekrar [{COUNTERPARTY}_1]; [{COMPANY}_1]; [{PERSON}_1]")
    assert p.mask("Atlas Lojistik") == f"[{COUNTERPARTY}_2]"       # the same value, the same placeholder, in a later message
    assert p.counts[COUNTERPARTY] == 4 and p.counts[COMPANY] == 1 and p.total == 6


def test_a_known_tax_number_is_found_without_a_label() -> None:
    nd = NameDictionary()
    nd.add_identifier(VKN)
    nd.add_identifier(TCKN)
    p = Pseudonymizer(nd)
    assert p.mask(f"firma {VKN} ve {TCKN}.") == "firma [VKN_1] ve [TCKN_1]."


def test_identifiers_win_over_names_where_they_overlap() -> None:
    nd = NameDictionary()
    nd.add(COUNTERPARTY, "Atlas Lojistik")
    out = Pseudonymizer(nd).mask("yaz muhasebe@atlas-lojistik.com ve Atlas Lojistik")
    assert out == f"yaz [E_POSTA_1] ve [{COUNTERPARTY}_1]"


# ── restoring the reply ──────────────────────────────────────────────────────

def test_restore_returns_the_books_own_spelling_and_the_original_identifier() -> None:
    p = Pseudonymizer(dictionary())
    masked = p.mask(f"ATLAS LOJISTIK a.s. IBAN {spaced(IBAN)} gönderdi")
    assert p.restore(masked) == f"Atlas Lojistik Ticaret A.Ş. IBAN {spaced(IBAN)} gönderdi"


def test_a_placeholder_the_call_never_issued_becomes_unknown_never_a_wrong_name() -> None:
    p = Pseudonymizer(dictionary())
    p.mask("Atlas Lojistik")
    reply = f"[{COUNTERPARTY}_7] ve [{COUNTERPARTY}_1] ve [IBAN_3] ve [KİŞİ_2] ve [bir not]"
    assert p.restore(reply) == f"{UNKNOWN_NAME} ve Atlas Lojistik Ticaret A.Ş. ve {UNKNOWN_VALUE} ve {UNKNOWN_NAME} ve [bir not]"


def test_a_placeholder_written_without_diacritics_or_with_spaces_is_still_understood() -> None:
    p = Pseudonymizer(dictionary())
    p.mask("Ahmet Yılmaz")
    assert p.restore("[KISI_1] ve [ KİŞİ_1 ]") == "Ahmet Yılmaz ve Ahmet Yılmaz"


def test_a_streamed_placeholder_split_across_chunks_is_restored_whole() -> None:
    p = Pseudonymizer(dictionary())
    p.mask("Atlas Lojistik")
    r = StreamRestorer(p)
    pieces = ["Ödeme [KARŞI_", "TARAF_", "1] yapıldı, [not", " bir yer] ve [KARŞI_TARAF_9", "]"]
    out = "".join(r.feed(x) for x in pieces) + r.flush()
    assert out == f"Ödeme Atlas Lojistik Ticaret A.Ş. yapıldı, [not bir yer] ve {UNKNOWN_NAME}"
    r2 = StreamRestorer(p)
    assert r2.feed("açık [KARŞI") + r2.flush() == "açık [KARŞI"        # an unfinished bracket is released at the end


# ── stable pseudonyms (embeddings) ───────────────────────────────────────────

def test_stable_pseudonyms_are_the_same_across_calls_and_differ_across_organisations() -> None:
    nd = dictionary()
    a1, a2 = Pseudonymizer(nd, stable_key=b"org-a"), Pseudonymizer(nd, stable_key=b"org-a")
    b = Pseudonymizer(nd, stable_key=b"org-b")
    text = f"Atlas Lojistik IBAN {IBAN}"
    m1, m2, mb = a1.mask(text), a2.mask("sorgu: ATLAS LOJISTIK " + f"IBAN {spaced(IBAN)}"), b.mask(text)
    assert m1.split()[0:2] == ["[KARŞI_TARAF_" + m1.split("_")[2].split("]")[0] + "]", "IBAN"]
    assert re.findall(r"\[[A-ZÇĞİÖŞÜ_]+_[0-9a-f]{8}\]", m1) == re.findall(r"\[[A-ZÇĞİÖŞÜ_]+_[0-9a-f]{8}\]", m2)
    assert m1 != mb and "Atlas" not in m1 + mb and IBAN not in m1 + mb
