"""Risk indicators are only what was measured — and the page contract they feed."""
from app.agents.risk.gercek_kri import gercek_kri


def test_nothing_measured_is_no_data_not_a_calm_posture():
    kris, posture = gercek_kri(None, None, None)
    assert kris == []
    assert posture["posture"] == "no_data"
    assert posture["kri_score"] is None
    assert posture["counts"]["total"] == 0


def test_cfo_figures_become_kris_with_source_and_no_invented_trend():
    pnl = {"revenue": 1_000_000, "net_margin": -0.04, "total_opex": 1_150_000}
    forecast = {"scenarios": {"base": {"runway_months": 2.5}}}
    kris, posture = gercek_kri(pnl, forecast, None)

    names = {k["name"] for k in kris}
    assert names == {"Nakit Ömrü", "Net Kâr Marjı", "Gider / Gelir"}
    for k in kris:
        assert k["source"].startswith("CFO")
        assert k["trend"] is None and k["trajectory_months"] is None
        assert "higher_is_worse" in k
    assert posture["posture"] == "critical"
    assert posture["upcoming_red"] == []
    assert posture["sources"] == ["CFO kâr-zarar", "CFO tahmini (baz senaryo)"]
    assert set(posture["by_category"]) == {"financial"}


def test_missing_figure_is_left_out_not_defaulted():
    # No forecast: runway is not assumed to be 12 months.
    kris, _ = gercek_kri({"revenue": 500_000, "net_margin": 0.12}, None, None)
    assert [k["name"] for k in kris] == ["Net Kâr Marjı"]
    assert kris[0]["status"] == "green"


def test_uploaded_kri_file_keeps_its_own_thresholds():
    risk_result = {"kris": {"breached_red": [{
        "name": "Kilit personel ayrılığı", "category": "people", "value": 3,
        "threshold_red": 2, "threshold_amber": 1, "unit": "kişi", "owner": "İK",
        "lower_is_worse": False,
    }]}}
    kris, posture = gercek_kri(None, None, risk_result)
    assert len(kris) == 1
    k = kris[0]
    assert (k["status"], k["threshold_red"], k["source"]) == ("red", 2.0, "yüklenen KRI dosyası")
    assert k["cascade_trigger"] == "key_person_loss"
    assert posture["cascade_ready"] == [k]
