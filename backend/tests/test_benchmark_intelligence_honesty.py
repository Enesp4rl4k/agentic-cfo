"""Plan v10 §13.3 / E2 — the SMMM benchmark service does not cite reports it cannot show.

`benchmark_intelligence.py` held percentiles in a dictionary under contexts such as
"Türkiye SaaS şirketleri 2024" and a header naming a "Türkiye SaaS raporu 2024" and
"KOSGEB KOBİ benchmarks". None of those sources is in the repository or was checked. Every
comparison also used the SaaS values whatever sector was asked for, and the summary told a
company it was "behind its sector" in those terms.

The values stay, because the endpoint's shape depends on them, but every answer says what
they are, and no text names a source that was not verified.
"""
from __future__ import annotations

from pathlib import Path

from app.services.benchmark_intelligence import (
    BENCHMARKS,
    UNVERIFIED_NOTE,
    VERIFIED,
    BenchmarkIntelligenceService,
)

SERVICE_FILE = Path(__file__).resolve().parents[1] / "app" / "services" / "benchmark_intelligence.py"
PNL = {"net_margin": 0.10, "gross_margin": 0.40}


def test_a_report_says_it_is_unverified_and_what_that_means():
    report = BenchmarkIntelligenceService().compare_cfo(PNL, sector="manufacturing").to_dict()
    assert VERIFIED is False
    assert report["verified"] is False
    assert report["note"] == UNVERIFIED_NOTE


def test_no_item_cites_a_report_or_a_year():
    items = BenchmarkIntelligenceService().compare_cfo(PNL, sector="manufacturing").to_dict()["items"]
    assert items
    for item in items:
        assert item["context"] == UNVERIFIED_NOTE


def test_the_summary_does_not_pass_a_verdict_off_as_a_finding():
    summary = BenchmarkIntelligenceService().compare_cfo(PNL, sector="manufacturing").summary
    assert summary.startswith("Doğrulanmamış örnek varsayımlara göre")


def test_an_empty_comparison_makes_no_claim_either():
    report = BenchmarkIntelligenceService().compare_cfo({}, sector="manufacturing").to_dict()
    assert report["items"] == []
    assert report["verified"] is False


def test_the_dictionary_names_no_source():
    assert all("context" not in values for values in BENCHMARKS.values())


def test_the_file_names_no_report_it_cannot_show():
    """A ratchet: the unverifiable attributions must not come back as text."""
    text = SERVICE_FILE.read_text(encoding="utf-8")
    for claim in ("KOSGEB", "SaaS raporu", "benchmark datası", "sektör anketleri", "çalışan anketi"):
        assert claim not in text, claim
