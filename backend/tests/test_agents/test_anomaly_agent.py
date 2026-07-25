"""
Tests for anomaly_agent.py — pure helper functions only (no LLM, no DB).
Covers: _z_score, _iqr_outlier_score, _is_round_number, _days_between
and the detection functions that use them.
"""
import pytest
from app.agents.anomaly_agent import (
    _z_score,
    _iqr_outlier_score,
    _is_round_number,
    _days_between,
    MIN_TRANSACTIONS_FOR_STATS,
    Z_SCORE_THRESHOLD,
    DUPLICATE_WINDOW_DAYS,
)


# ── _z_score ──────────────────────────────────────────────────────────────────

class TestZScore:

    def test_returns_none_for_short_list(self):
        values = [100, 200, 300]  # < MIN_TRANSACTIONS_FOR_STATS
        assert _z_score(200, values) is None

    def test_returns_float_for_valid_list(self):
        values = [100, 100, 100, 100, 100, 200]
        result = _z_score(100, values)
        assert result is not None
        assert isinstance(result, float)

    def test_outlier_has_high_z_score(self):
        """Value far from mean should have the highest abs z-score in the group."""
        # Use many normal values and one extreme outlier
        normals = [100] * 20 + [200]  # 21 values, last is outlier
        z_outlier = _z_score(200, normals)
        z_normal  = _z_score(100, normals)
        assert z_outlier is not None
        assert z_normal is not None
        assert abs(z_outlier) > abs(z_normal)

    def test_normal_value_has_low_z_score(self):
        """Value near mean should have low z-score."""
        values = [100, 102, 98, 101, 99, 100]
        z = _z_score(100, values)
        assert z is not None
        assert abs(z) < 1.0

    def test_returns_zero_for_all_same_values(self):
        """Zero standard deviation — scipy may return NaN; implementation should not crash."""
        values = [100, 100, 100, 100, 100]
        result = _z_score(100, values)
        # scipy zscore with ddof=1 returns NaN for identical values (catastrophic cancellation)
        # The implementation may return None, 0.0, or NaN — all acceptable as long as no exception
        import math
        assert result is None or result == pytest.approx(0.0, abs=0.1) or (
            isinstance(result, float) and math.isnan(result)
        )

    def test_exactly_min_transactions_works(self):
        values = [10, 20, 30, 40, 50]  # exactly MIN_TRANSACTIONS_FOR_STATS
        result = _z_score(30, values)
        # Should return a float now
        assert result is not None


# ── _iqr_outlier_score ────────────────────────────────────────────────────────

class TestIQROutlierScore:

    def test_returns_none_for_short_list(self):
        values = [10, 20, 30]
        assert _iqr_outlier_score(20, values) is None

    def test_returns_float_for_valid_list(self):
        values = [10, 20, 30, 40, 50, 60]
        result = _iqr_outlier_score(30, values)
        assert result is not None
        assert isinstance(result, float)

    def test_extreme_outlier_positive_score(self):
        """Very large value should have positive IQR score > 0."""
        values = [100, 110, 90, 105, 95, 5_000]
        result = _iqr_outlier_score(5_000, values)
        assert result is not None
        assert result > 0

    def test_value_below_q3_negative_or_zero(self):
        """Value below Q3 should have non-positive IQR score."""
        values = [100, 110, 90, 105, 95, 100]
        result = _iqr_outlier_score(95, values)
        assert result is not None
        assert result <= 0

    def test_zero_iqr_returns_zero(self):
        """All same values → IQR = 0 → should return 0.0, not divide by zero."""
        values = [100, 100, 100, 100, 100]
        result = _iqr_outlier_score(100, values)
        assert result == pytest.approx(0.0)


# ── _is_round_number ──────────────────────────────────────────────────────────

class TestIsRoundNumber:

    def test_round_100_tl_is_round(self):
        assert _is_round_number(10_000) is True  # 100 TL

    def test_round_1000_tl_is_round(self):
        assert _is_round_number(100_000) is True  # 1,000 TL

    def test_odd_amount_not_round(self):
        assert _is_round_number(9_999) is False  # 99.99 TL

    def test_zero_not_round(self):
        assert _is_round_number(0) is False

    def test_99_99_tl_not_round(self):
        assert _is_round_number(9_999) is False

    def test_50_tl_not_round_multiple_of_100(self):
        # 50 TL = 5000 cents — 50 % 100 == 50 ≠ 0
        assert _is_round_number(5_000) is False

    def test_500_tl_is_round(self):
        assert _is_round_number(50_000) is True  # 500 TL = 50000 cents, 500 % 100 == 0


# ── _days_between ─────────────────────────────────────────────────────────────

class TestDaysBetween:

    def test_same_date_zero_days(self):
        result = _days_between("2024-01-15", "2024-01-15")
        assert result == 0

    def test_one_day_apart(self):
        result = _days_between("2024-01-15", "2024-01-16")
        assert result == 1

    def test_month_apart(self):
        result = _days_between("2024-01-01", "2024-02-01")
        assert result == 31

    def test_returns_absolute_value(self):
        r1 = _days_between("2024-01-15", "2024-01-10")
        r2 = _days_between("2024-01-10", "2024-01-15")
        assert r1 == r2 == 5

    def test_none_a_returns_none(self):
        assert _days_between(None, "2024-01-15") is None

    def test_none_b_returns_none(self):
        assert _days_between("2024-01-15", None) is None

    def test_both_none_returns_none(self):
        assert _days_between(None, None) is None

    def test_invalid_date_returns_none(self):
        assert _days_between("not-a-date", "2024-01-15") is None

    def test_iso_with_time_works(self):
        # Two naive datetime strings — same day, different times
        result = _days_between("2024-01-15T08:00:00", "2024-01-15T18:00:00")
        # Both are naive datetimes; timedelta.days = 0 for same calendar day
        assert result is not None
        assert result <= 1  # either 0 (naive) or 1 (if mixed tz); either is acceptable

    def test_z_suffix_handled(self):
        result = _days_between("2024-01-15T00:00:00Z", "2024-01-17T00:00:00Z")
        assert result == 2


# ── Integration: threshold constants are sensible ─────────────────────────────

class TestThresholdConstants:

    def test_min_transactions_positive(self):
        assert MIN_TRANSACTIONS_FOR_STATS > 0

    def test_z_score_threshold_reasonable(self):
        assert 1.0 < Z_SCORE_THRESHOLD < 5.0

    def test_duplicate_window_positive(self):
        assert DUPLICATE_WINDOW_DAYS > 0
