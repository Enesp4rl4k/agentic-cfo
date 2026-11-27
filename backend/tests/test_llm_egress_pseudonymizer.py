"""Detection and pseudonymisation: checksums AND shape AND evidence, Turkish casing, exact restore, invented
placeholders, streaming, stable embedding tokens, and a mapping that never shows up in a repr or a pickle.

The invariant behind every test here (fuzzed at scale in test_llm_egress_fidelity.py): figures are never
masked or altered.
"""
from __future__ import annotations

import logging
import pickle
import re

import pytest

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
TOKEN = re.compile(r"\[\[([A-Z]+)_([A-Z0-9]{3})_(\d+)([a-z]?)\]\]")


def spaced(iban: str) -> str:
    return " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))


def labels(text: str) -> list[str]:
    return [s.label for s in d.find_identifiers(text)]


def names() -> NameDictionary:
    nd = NameDictionary()
    nd.add(COUNTERPARTY, "Atlas Lojistik Ltd. Şti.")
    nd.add(COMPANY, "Menekşe Tekstil Sanayi A.Ş.")
    nd.add(PERSON, "Ahmet Yılmaz", person=True)
    nd.add_identifier(VKN)
    return nd


# ── checksums ────────────────────────────────────────────────────────────────

def test_checksums_true_and_false() -> None:
    assert d.iban_ok(IBAN) and d.iban_ok("DE89370400440532013000") and d.iban_ok("GB82WEST12345698765432")
    assert not d.iban_ok(IBAN[:-1] + ("2" if IBAN[-1] != "2" else "3"))
    assert not d.iban_ok("TR" + IBAN[2:-1])              # a Turkish IBAN is exactly 26 characters
    assert not d.iban_ok("ZZ89370400440532013000")       # no such country: never an IBAN
    assert d.tckn_ok(TCKN) and not d.tckn_ok("10000000147") and not d.tckn_ok("01234567890")
    assert d.vkn_ok(VKN) and not d.vkn_ok(VKN[:-1] + str((int(VKN[-1]) + 1) % 10))
    assert d.luhn_ok(PAN) and not d.luhn_ok("4111111111111112")


# ── identifiers need evidence ────────────────────────────────────────────────

def test_iban_in_every_spelling_and_never_with_a_wrong_check() -> None:
    for text in (IBAN, spaced(IBAN), IBAN.lower(), "-".join(IBAN[i:i + 4] for i in range(0, 26, 4)),
                 f"{IBAN[:9]}\n{IBAN[9:]}", f"IBAN: {IBAN[2:]}", "DE89370400440532013000"):
        assert labels(f"hesap {text} kaydı") == [d.IBAN], text
    assert labels(IBAN[:-1] + ("2" if IBAN[-1] != "2" else "3")) == []
    assert labels(IBAN[2:]) == []                         # 24 digits with no "TR" and no label: just a number


def test_tckn_and_vkn_need_checksum_and_their_label() -> None:
    assert labels(f"TCKN {TCKN}") == [d.TCKN] and labels(f"T.C. Kimlik No: {TCKN}") == [d.TCKN]
    assert labels(f'"tc_kimlik_no": "{TCKN}"') == [d.TCKN]
    for bare in (f"kişi {TCKN}", f"Net kâr {TCKN}", f"Tutar: {TCKN}", f"{TCKN} TL", TCKN):
        assert labels(bare) == [], bare                   # no label: a number, never a person
    assert labels("TCKN 10000000147") == []               # a label without the checksum is not enough
    assert labels(f"VKN: {VKN}") == [d.VKN] and labels(f"Vergi No {VKN}") == [d.VKN]
    assert labels(f"firma {VKN}") == []


def test_cards_need_luhn_issuer_and_a_label_or_the_printed_grouping() -> None:
    assert labels(f"Kart No: {PAN}") == [d.PAN] and labels("4111 1111 1111 1111") == [d.PAN]
    assert labels(f"ödeme {PAN} referansı") == [] and labels(f"Ref {PAN}") == []
    assert labels("Kart No: 4111111111111112") == []      # Luhn fails


def test_phones_need_a_phone_shape_or_a_label_never_a_decimal() -> None:
    for text in ("0532 987 65 43", "+90 532 987 65 43", "(0212) 555 12 34", "+905329876543", "0532-987-65-43",
                 "Tel: 5329876543", "GSM 05329876543", "Tel: 532 987 65 43"):
        assert labels(text) == [d.PHONE], text
    for text in ("Net 41176993.01 TL", "Dekont 05321234567", "05321234567", "532.987.65.43", "20240315 60 TL"):
        assert labels(text) == [], text


def test_email_plate_and_account_number() -> None:
    assert labels("info@ışık.com.tr") == [d.EMAIL] and labels("a.b+c@örnek.com.tr") == [d.EMAIL]
    assert labels("Plaka: 34 ABC 123") == [d.PLATE] and labels("34 ABC 123") == []   # a plate needs its label
    assert labels("30 GÜN 45 TL") == []
    assert labels("Hesap No: 1234 5678 90") == [d.ACCOUNT_NO] and labels("Hesap No: 120.01.001") == []


# ── round trip and figures ───────────────────────────────────────────────────

def test_figures_next_to_masked_values_survive_byte_for_byte() -> None:
    p = Pseudonymizer(names())
    line = (f"Atlas Lojistik'e 1.234.567,89 TL (15.03.2026) IBAN {spaced(IBAN)}; KDV %20; 41176993.01 USD; "
            f"TCKN {TCKN}; 120.01.001 hesabı; Fatura No: GIB2024000000123")
    masked = p.mask(line)
    for figure in ("1.234.567,89 TL", "15.03.2026", "%20", "41176993.01 USD", "120.01.001", "GIB2024000000123"):
        assert figure in masked
    assert IBAN not in masked.replace(" ", "") and TCKN not in masked and "Atlas" not in masked
    assert p.restore(masked) == line


def test_fold_is_length_preserving_and_handles_dotted_and_dotless_i() -> None:
    assert fold("İSTANBUL ışık IĞDIR") == "istanbul isik igdir"
    assert len(fold("İı")) == 2


def test_known_names_in_any_casing_spacing_and_with_suffixes() -> None:
    p = Pseudonymizer(names())
    for text in ("ATLAS LOJİSTİK", "atlas lojistik ltd sti", "Atlas\n  Lojistik", "Atlas Lojistiğe", "Atlas Lojistiğin",
                 "Atlas Lojistikten", "Menekşe Tekstil Sanayi A.Ş.'nin", "menekse tekstil", "Ahmet Yılmaz", "Yılmazın",
                 "dün Ahmet aradı"):
        assert "[[" in p.mask(text), text


def test_an_apostrophe_suffix_stays_outside_the_placeholder_and_words_are_whole() -> None:
    p = Pseudonymizer(names())
    assert re.fullmatch(r"\[\[CP_[A-Z0-9]{3}_1\]\]'e ödendi", p.mask("Atlas Lojistik'e ödendi"))
    assert p.mask("Atlasçılar Lojistikçiler") == "Atlasçılar Lojistikçiler"   # "çılar" is not in the suffix grammar


def test_placeholders_are_ascii_typed_numbered_per_entity_with_one_nonce_per_call() -> None:
    p = Pseudonymizer(names())
    masked = p.mask("Atlas Lojistik, ATLAS LOJİSTİK ve Atlas Lojistik; Ahmet Yılmaz")
    found = TOKEN.findall(masked)
    assert masked.isascii() or all(t.isascii() for t in re.findall(r"\[\[[^\]]+\]\]", masked))
    assert [f[0] for f in found] == ["CP", "CP", "CP", "PER"]
    assert found[0][2] == found[1][2] == "1" and found[0][3] == "" and found[1][3] == "b"   # one entity, two spellings
    assert found[2] == found[0]                                                            # same spelling, same token
    assert len({f[1] for f in found}) == 1 and Pseudonymizer(names()).nonce != "" and len(p.nonce) == 3


def test_a_tax_number_the_books_hold_is_found_without_a_label_unless_it_is_a_figure() -> None:
    p = Pseudonymizer(names())
    assert "[[VKN_" in p.mask(f"firma {VKN} ile")
    assert p.mask(f"Tutar {VKN} TL") == f"Tutar {VKN} TL"


def test_identifiers_win_over_names_where_they_overlap() -> None:
    p = Pseudonymizer(names())
    out = p.mask("yaz atlas.lojistik@firma.com ve Atlas Lojistik")
    assert re.fullmatch(r"yaz \[\[MAIL_\w+\]\] ve \[\[CP_\w+\]\]", out)


def test_restore_is_byte_exact_and_never_guesses() -> None:
    p = Pseudonymizer(names())
    masked = p.mask("ATLAS LOJİSTİK ödedi, Tel: 0532 987 65 43")
    cp = TOKEN.search(masked).group(0)
    assert p.restore(masked) == "ATLAS LOJİSTİK ödedi, Tel: 0532 987 65 43"   # the original spelling, not the books'
    assert p.restore(f"{cp} ve [[CP_{p.nonce}_9]]") == f"ATLAS LOJİSTİK ve {UNKNOWN_NAME}"
    assert p.restore("[[TEL_ZZZ_1]]") == UNKNOWN_VALUE                       # another call's nonce: unknown
    assert p.restore(cp.lower().replace("[[", "[ [").replace(" ", "")) == "ATLAS LOJİSTİK"
    assert p.restore(cp[1:-1]) == "ATLAS LOJİSTİK"                            # single brackets: still ours
    assert p.restore("[normal bir parantez]") == "[normal bir parantez]"


def test_restore_strict_returns_none_for_anything_unresolved() -> None:
    p = Pseudonymizer(names())
    masked = p.mask("Atlas Lojistik")
    assert p.restore_strict(masked) == "Atlas Lojistik"
    assert p.restore_strict(f"{masked} ve [[CP_{p.nonce}_7]]") is None
    assert p.restore_strict("[[CP_a1b2c3d4]]") is None                        # a stable token is never data
    assert p.restore_strict("düz metin") == "düz metin"


def test_a_streamed_placeholder_split_across_chunks_is_restored_whole() -> None:
    p = Pseudonymizer(names())
    token = TOKEN.search(p.mask("Atlas Lojistik")).group(0)
    text = f"Ödeme {token} yapıldı, [not bir yer] ve {token} tamam."
    for size in range(1, 12):
        r = StreamRestorer(p)
        out = "".join(r.feed(text[i:i + size]) for i in range(0, len(text), size)) + r.flush()
        assert out == p.restore(text) == "Ödeme Atlas Lojistik yapıldı, [not bir yer] ve Atlas Lojistik tamam."


def test_stable_pseudonyms_are_the_same_across_calls_and_differ_across_organisations() -> None:
    nd = names()
    a1, a2, b = Pseudonymizer(nd, stable_key=b"org-a"), Pseudonymizer(nd, stable_key=b"org-a"), Pseudonymizer(nd, stable_key=b"org-b")
    t1, t2, t3 = (x.mask("Atlas Lojistik") for x in (a1, a2, b))
    assert t1 == t2 != t3 and re.fullmatch(r"\[\[CP_[0-9a-f]{8}\]\]", t1)


# ── the mapping never leaks through a repr, a log line or a pickle ───────────

def test_repr_and_str_show_counts_never_the_mapping_or_a_name(caplog) -> None:
    from app.platform.llm_egress.dictionary import LoadedDictionary
    from app.platform.llm_egress.policy import DataMode, ModeDecision
    from app.platform.llm_egress.session import EgressSession

    nd = names()
    p = Pseudonymizer(nd)
    p.mask(f"Atlas Lojistik, Ahmet Yılmaz, IBAN {IBAN}")
    sess = EgressSession(ModeDecision(DataMode.MASKED, "platform", DataMode.MASKED, None, False), "org", p, set())
    shown = " ".join([repr(p), str(p), repr(nd), str(nd), repr(LoadedDictionary(nd)), repr(sess), repr(StreamRestorer(p)),
                      f"{p!r} {sess}"])
    for secret in ("Atlas", "atlas", "Yılmaz", "yilmaz", IBAN, VKN, "Menekşe", "menekse"):
        assert secret not in shown, secret
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("x").warning("session %s pseudo %r", sess, p)
    assert "Atlas" not in caplog.text and IBAN not in caplog.text
    with pytest.raises(TypeError):
        pickle.dumps(p)
