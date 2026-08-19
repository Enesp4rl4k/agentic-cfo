from app.services.data_plane.normalization_service import normalize_csv_transactions
from app.services.data_plane.quality_gate_service import score_sync_quality


def test_normalize_csv_transactions_maps_basic_fields() -> None:
    csv_bytes = (
        "date,amount,description,category,reference\n"
        "2026-08-01,1250.50,Office rent,operations,INV-1\n"
    ).encode("utf-8")
    rows = normalize_csv_transactions(csv_bytes=csv_bytes, column_mapping={})

    assert len(rows) == 1
    assert rows[0].amount_cents == 125050
    assert rows[0].description == "Office rent"
    assert rows[0].source_record_id == "INV-1"


def test_score_sync_quality_sets_review_band() -> None:
    result = score_sync_quality(validator_health_score=72, canonical_row_count=10)
    assert result.should_block is False
    assert result.should_review is True
    assert 0.50 <= result.quality_score < 0.80

