"""İlişkili taraf sicili — matching and the authority rule it finally feeds."""
from __future__ import annotations

import pytest

from app.models.related_party import RelatedParty
from app.platform.authority_matrix import (
    DEFAULT_POLICY_RULES,
    AuthorityRequest,
    evaluate,
)
from app.services.related_party import (
    annotate_transactions,
    group_counterparties,
    match_transaction,
    normalize_name,
    normalize_tax_id,
)


def _party(name: str, *, tax_id: str | None = None, rel: str = "aile") -> RelatedParty:
    return RelatedParty(
        id=f"p-{name}",
        org_id="org-1",
        name=name,
        normalized_name=normalize_name(name),
        relationship_type=rel,
        tax_id=tax_id,
        active=True,
    )


# ── Normalisation ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Demir İnşaat Sanayi ve Ticaret Ltd. Şti.", "demir"),
        ("DEMİR A.Ş.", "demir"),
        ("Demir Anonim Şirketi", "demir"),
        ("  Öztürk   Holding ", "ozturk"),
        ("Ali Yılmaz", "ali yilmaz"),
    ],
)
def test_legal_forms_and_casing_collapse_to_one_name(raw: str, expected: str) -> None:
    """A register entry must match however the statement spells the company.

    "Demir A.Ş." and "Demir İnşaat Sanayi ve Ticaret Ltd. Şti." are the same
    counterparty; a register that only matched the exact string would miss the
    transaction it exists to catch.
    """
    assert normalize_name(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1234567890", "1234567890"), ("12.345.678.901", "12345678901"),
     ("123", ""), (None, ""), ("abc", "")],
)
def test_only_vkn_and_tckn_lengths_count_as_identifiers(raw, expected) -> None:
    assert normalize_tax_id(raw) == expected


# ── Matching ──────────────────────────────────────────────────────────────────

def test_matches_on_tax_id_even_when_the_name_differs() -> None:
    parties = [_party("Demir İnşaat A.Ş.", tax_id="1234567890")]
    match = match_transaction(
        {"vendor": "DMR YAPI", "tax_id": "1234567890"}, parties
    )
    assert match is not None
    assert match.matched_on == "tax_id"


def test_matches_a_party_named_only_in_the_description() -> None:
    """Rent rarely names the landlord in a structured field."""
    parties = [_party("Öztürk Holding", rel="ortak")]
    match = match_transaction(
        {"vendor": "", "description": "Ocak ayi ofis kirasi - Ozturk Holding"}, parties
    )
    assert match is not None
    assert match.matched_on == "name_in_text"
    assert match.relationship_type == "ortak"


def test_short_names_do_not_match_on_containment() -> None:
    """"Ata" must not flag "Atasehir kirasi" — a false positive costs the owner
    an approval, but a register nobody trusts gets switched off."""
    parties = [_party("Ata")]
    assert match_transaction({"description": "Atasehir kirasi odemesi"}, parties) is None


def test_unrelated_counterparty_is_not_flagged() -> None:
    parties = [_party("Demir İnşaat A.Ş.")]
    assert match_transaction({"vendor": "Migros Ticaret A.Ş."}, parties) is None


def test_empty_register_flags_nothing() -> None:
    assert match_transaction({"vendor": "Demir A.Ş."}, []) is None


def test_annotate_sets_the_flag_and_records_the_evidence() -> None:
    parties = [_party("Demir İnşaat A.Ş.", rel="aile")]
    txs = [
        {"vendor": "Demir A.Ş.", "amount_kurus": 500_00},
        {"vendor": "Migros", "amount_kurus": 120_00},
    ]
    flagged = annotate_transactions(txs, parties)

    assert flagged == 1
    assert txs[0]["is_related_party"] is True
    # The reviewer is told what the machine keyed on, not just that it matched.
    assert txs[0]["related_party"]["matched_on"] == "exact_name"
    assert txs[0]["related_party"]["relationship_type"] == "aile"
    assert "is_related_party" not in txs[1]


# ── The rule this exists to feed ──────────────────────────────────────────────

def test_flagged_transaction_now_reaches_the_owner() -> None:
    """The delegation matrix has always had a related-party rule; nothing ever
    set the flag, so it had never once fired."""
    decision = evaluate(
        DEFAULT_POLICY_RULES,
        AuthorityRequest(
            domain="journal_entry",
            amount_kurus=500_00,
            is_related_party=True,
            confidence=0.99,
            classification_method="kural",
        ),
    )
    assert decision.matched_rule_id == "related_party"
    assert decision.needs_review
    assert {a["role"] for a in decision.required_approvals} == {"owner"}
    assert "disclosure" in decision.required_evidence


def test_same_entry_without_the_flag_is_auto_approved() -> None:
    decision = evaluate(
        DEFAULT_POLICY_RULES,
        AuthorityRequest(
            domain="journal_entry",
            amount_kurus=500_00,
            is_related_party=False,
            confidence=0.99,
            classification_method="kural",
        ),
    )
    assert decision.matched_rule_id != "related_party"
    assert not decision.needs_review


# ── The suggestion flow ───────────────────────────────────────────────────────
# An empty register flags nothing, so the feature is dead until somebody fills
# it — and nobody lists their own related parties from memory. These cover the
# ranking rule the suggestion endpoint applies.

def test_suggestion_normalisation_dedupes_spellings() -> None:
    """The same counterparty spelled three ways is one suggestion.

    A statement will carry "OZTURK HOLDING", "Öztürk Holding A.Ş." and
    "Ozturk Hold." for one company; offering all three as separate candidates
    makes the list unusable.
    """
    spellings = ["OZTURK HOLDING", "Öztürk Holding A.Ş.", "Ozturk Holding Anonim Şirketi"]
    assert len({normalize_name(s) for s in spellings}) == 1


def test_already_registered_party_is_not_suggested_again() -> None:
    party = _party("Öztürk Holding")
    known = {party.normalized_name}
    assert normalize_name("OZTURK HOLDING A.S.") in known


def test_recurrence_is_counted_after_normalising_not_before() -> None:
    """The regression that made this endpoint useless on its first live run.

    Grouping and thresholding in SQL counts how often a company was spelled one
    particular way. A landlord whose name lands differently every month is the
    exact counterparty the register exists to surface, and it was the one the
    threshold filtered out — while a supermarket spelled identically twice
    sailed through.
    """
    rows = [
        ("OZTURK HOLDING", 1, 25_000_00),
        ("Ozturk Holding A.S.", 1, 25_000_00),
        ("OZTURK HOLDING ANONIM SIRKETI", 1, 25_000_00),
        ("Migros", 2, 1_750_00),
        ("Acme Ltd", 1, 150_000_00),   # genuinely a one-off
    ]
    out = group_counterparties(rows, known=set())

    names = [g["normalized_name"] for g in out]
    assert names == ["ozturk", "migros"], names

    ozturk = out[0]
    assert ozturk["transaction_count"] == 3
    assert ozturk["spellings"] == 3
    # The longest spelling is shown: most information for someone deciding
    # whether they recognise the name.
    assert ozturk["vendor"] == "OZTURK HOLDING ANONIM SIRKETI"


def test_registered_parties_drop_out_of_suggestions() -> None:
    rows = [("OZTURK HOLDING", 2, 100), ("Migros", 2, 100)]
    out = group_counterparties(rows, known={"ozturk"})
    assert [g["normalized_name"] for g in out] == ["migros"]
