"""
ForecastingService — STL Decomposition + ARIMA Forecasting.

Sprint L1: Lineer ekstrapolasyonu güçlü time-series forecasting ile değiştirir.

Methods
-------
- STL (default): Seasonal-Trend decomposition — mevsimsellik + trend ayrıştırma
- ARIMA: otomatik parametre seçimi (p,d,q) — kısa vadeli tahmin
- Linear: fallback when < 12 data points

Graceful degradation
--------------------
- statsmodels not installed → linear fallback
- ARIMA convergence failure → STL or linear
- < 4 data points → returns empty forecast

Usage
-----
    svc = ForecastingService()
    result = svc.forecast(
        series=[100, 110, 95, 120, ...],
        dates=["2024-01", "2024-02", ...],
        periods=6,
        method="stl",
    )
    # result.forecast: [{date, p10, p50, p90}, ...]
    # result.change_points: [{date, direction}, ...]
    # result.seasonality: {trend: [...], seasonal: [...], residual: [...]}
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

MIN_POINTS_STL    = 12    # STL needs at least 2 full seasons
MIN_POINTS_ARIMA  = 8     # ARIMA minimum
MIN_POINTS_LINEAR = 4     # absolute minimum
PREDICTION_INTERVALS = [0.10, 0.50, 0.90]  # P10, P50, P90


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class ForecastPoint:
    date: str
    p10:  float
    p50:  float
    p90:  float


@dataclass
class TrendChangePoint:
    date:         str
    direction:    str    # "up" | "down"
    magnitude:    float  # absolute change
    description:  str


@dataclass
class ForecastResult:
    method:       str                         # "stl" | "arima" | "linear"
    historical:   list[dict[str, Any]]        # [{date, value}]
    forecast:     list[dict[str, Any]]        # [{date, p10, p50, p90}]
    change_points: list[dict[str, Any]]       # [{date, direction, magnitude}]
    seasonality:  dict[str, list[float]]      # {trend, seasonal, residual}
    mae:          float | None = None         # mean absolute error (in-sample)
    summary:      str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "method":        self.method,
            "historical":    self.historical,
            "forecast":      self.forecast,
            "change_points": self.change_points,
            "seasonality":   self.seasonality,
            "mae":           self.mae,
            "summary":       self.summary,
        }


# ── Trend change detection (PELT-inspired simple implementation) ─────────────

def _detect_trend_changes(
    series: list[float],
    dates: list[str],
    window: int = 3,
    threshold_pct: float = 0.15,
) -> list[dict[str, Any]]:
    """
    Detect significant trend changes using rolling window comparison.

    A change point occurs when the average of the next `window` points
    differs from the average of the previous `window` points by more
    than `threshold_pct` (default 15%).
    """
    if len(series) < window * 2 + 1:
        return []

    change_points = []

    for i in range(window, len(series) - window):
        pre_mean  = sum(series[i - window:i]) / window
        post_mean = sum(series[i:i + window]) / window

        if pre_mean == 0:
            continue

        pct_change = (post_mean - pre_mean) / abs(pre_mean)
        if abs(pct_change) >= threshold_pct:
            direction = "up" if pct_change > 0 else "down"
            magnitude = abs(post_mean - pre_mean)
            date = dates[i] if i < len(dates) else str(i)

            change_points.append({
                "date":        date,
                "direction":   direction,
                "magnitude":   round(magnitude, 2),
                "pct_change":  round(pct_change * 100, 1),
                "description": (
                    f"Trend değişimi: {date} tarihinde "
                    f"{'+' if pct_change > 0 else ''}{pct_change*100:.1f}% "
                    f"{'artış' if direction == 'up' else 'düşüş'}"
                ),
            })

    return change_points


# ── Linear fallback ───────────────────────────────────────────────────────────

def _linear_forecast(
    series: list[float],
    dates: list[str],
    periods: int,
) -> ForecastResult:
    """
    Simple linear extrapolation with uncertainty widening.
    Used when series is too short for STL/ARIMA.
    """
    n = len(series)

    # Fit linear trend
    x_mean = (n - 1) / 2
    y_mean = sum(series) / n
    num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(series))
    den = sum((i - x_mean) ** 2 for i in range(n)) or 1.0
    slope = num / den
    intercept = y_mean - slope * x_mean

    # Residual std for uncertainty bounds
    residuals = [series[i] - (slope * i + intercept) for i in range(n)]
    std = (sum(r ** 2 for r in residuals) / max(1, n - 2)) ** 0.5

    # Generate future dates
    last_date = dates[-1] if dates else "T+0"
    future_dates = _generate_future_dates(last_date, periods)

    forecast_points = []
    for step, fdate in enumerate(future_dates, 1):
        p50 = slope * (n + step - 1) + intercept
        # Uncertainty grows with horizon
        uncertainty = std * (1.0 + 0.1 * step)
        forecast_points.append({
            "date": fdate,
            "p10":  round(p50 - 1.645 * uncertainty, 2),
            "p50":  round(p50, 2),
            "p90":  round(p50 + 1.645 * uncertainty, 2),
        })

    historical = [{"date": d, "value": round(v, 2)} for d, v in zip(dates, series)]

    return ForecastResult(
        method        = "linear",
        historical    = historical,
        forecast      = forecast_points,
        change_points = _detect_trend_changes(series, dates),
        seasonality   = {},
        summary       = f"Lineer ekstrapolasyon ({n} veri noktası, {periods} dönem tahmin)",
    )


# ── STL (Seasonal-Trend Decomposition) ───────────────────────────────────────

def _stl_forecast(
    series: list[float],
    dates: list[str],
    periods: int,
    period_seasonality: int = 12,
) -> ForecastResult:
    """
    STL decomposition + ETS/ARIMA on trend component.

    Uses statsmodels STL + ExponentialSmoothing for trend forecasting.
    Falls back to linear if statsmodels unavailable.
    """
    try:
        from statsmodels.tsa.seasonal import STL
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
        import numpy as np

        y = np.array(series, dtype=float)
        n = len(y)

        # STL decomposition
        stl = STL(y, period=min(period_seasonality, n // 2), robust=True)
        stl_result = stl.fit()

        trend    = stl_result.trend
        seasonal = stl_result.seasonal
        residual = stl_result.resid

        # Forecast trend using Exponential Smoothing
        trend_model = ExponentialSmoothing(
            trend,
            trend="add",
            damped_trend=True,
        ).fit(optimized=True)

        trend_forecast = trend_model.forecast(periods)

        # Seasonal: use last full cycle
        cycle_len = min(period_seasonality, n)
        seasonal_cycle = seasonal[-cycle_len:]
        seasonal_forecast = [
            seasonal_cycle[i % cycle_len] for i in range(periods)
        ]

        # Residual uncertainty: use IQR
        q25, q75 = np.percentile(residual, 25), np.percentile(residual, 75)
        iqr = (q75 - q25) / 2 or 1.0

        future_dates = _generate_future_dates(dates[-1] if dates else "T+0", periods)
        forecast_pts = []

        for step, (fdate, tf, sf) in enumerate(
            zip(future_dates, trend_forecast, seasonal_forecast), 1
        ):
            p50 = float(tf + sf)
            uncertainty = iqr * (1.0 + 0.05 * step)
            forecast_pts.append({
                "date": fdate,
                "p10":  round(p50 - 1.645 * uncertainty, 2),
                "p50":  round(p50, 2),
                "p90":  round(p50 + 1.645 * uncertainty, 2),
            })

        # In-sample MAE
        fitted = trend + seasonal + residual
        mae = float(np.mean(np.abs(y - fitted)))

        seasonality_data = {
            "trend":    [round(float(v), 2) for v in trend],
            "seasonal": [round(float(v), 2) for v in seasonal],
            "residual": [round(float(v), 2) for v in residual],
        }

        historical = [{"date": d, "value": round(v, 2)} for d, v in zip(dates, series)]

        return ForecastResult(
            method        = "stl",
            historical    = historical,
            forecast      = forecast_pts,
            change_points = _detect_trend_changes(series, dates),
            seasonality   = seasonality_data,
            mae           = round(mae, 2),
            summary       = (
                f"STL ayrıştırma + Üstel Düzleştirme "
                f"(MAE: {mae:.1f}, {periods} dönem tahmin)"
            ),
        )

    except ImportError:
        logger.debug("statsmodels not installed — falling back to linear forecast")
        return _linear_forecast(series, dates, periods)
    except Exception as exc:
        logger.warning("STL forecast failed: %s — falling back to linear", exc)
        return _linear_forecast(series, dates, periods)


# ── ARIMA ─────────────────────────────────────────────────────────────────────

def _arima_forecast(
    series: list[float],
    dates: list[str],
    periods: int,
) -> ForecastResult:
    """
    ARIMA with automatic order selection (AIC minimization).
    Tries common (p,d,q) combinations and picks best AIC.
    Falls back to STL if ARIMA fails.
    """
    try:
        from statsmodels.tsa.arima.model import ARIMA
        import numpy as np

        y = np.array(series, dtype=float)

        # Try simple ARIMA orders — pick best AIC
        best_aic  = float("inf")
        best_fit  = None

        for p in range(0, 4):
            for d in range(0, 3):
                for q in range(0, 4):
                    try:
                        model = ARIMA(y, order=(p, d, q))
                        fit   = model.fit()
                        if fit.aic < best_aic:
                            best_aic = fit.aic
                            best_fit = fit
                    except Exception:
                        continue

        if best_fit is None:
            return _stl_forecast(series, dates, periods)

        forecast_obj  = best_fit.get_forecast(steps=periods)
        p50_values    = forecast_obj.predicted_mean
        conf_int      = forecast_obj.conf_int(alpha=0.1)  # 90% CI

        future_dates  = _generate_future_dates(dates[-1] if dates else "T+0", periods)
        forecast_pts  = []

        for fdate, p50, ci_row in zip(future_dates, p50_values, conf_int):
            forecast_pts.append({
                "date": fdate,
                "p10":  round(float(ci_row[0]), 2),
                "p50":  round(float(p50), 2),
                "p90":  round(float(ci_row[1]), 2),
            })

        # In-sample MAE
        mae = float(np.mean(np.abs(y - best_fit.fittedvalues)))

        historical = [{"date": d, "value": round(v, 2)} for d, v in zip(dates, series)]

        return ForecastResult(
            method        = "arima",
            historical    = historical,
            forecast      = forecast_pts,
            change_points = _detect_trend_changes(series, dates),
            seasonality   = {},
            mae           = round(mae, 2),
            summary       = (
                f"ARIMA (AIC: {best_aic:.1f}, MAE: {mae:.1f}, {periods} dönem)"
            ),
        )

    except ImportError:
        logger.debug("statsmodels not installed — falling back to STL")
        return _stl_forecast(series, dates, periods)
    except Exception as exc:
        logger.warning("ARIMA failed: %s — falling back to STL", exc)
        return _stl_forecast(series, dates, periods)


# ── Date generation helper ────────────────────────────────────────────────────

def _generate_future_dates(last_date: str, periods: int) -> list[str]:
    """
    Generate future period labels (monthly).
    Supports formats: "2024-01", "2024-01-01", "Jan 2024"
    Falls back to "T+N" labels if unparseable.
    """
    future = []

    try:
        # Try ISO month format first
        from datetime import datetime, timedelta

        # Try "YYYY-MM" format
        for fmt in ("%Y-%m", "%Y-%m-%d", "%b %Y", "%B %Y"):
            try:
                dt = datetime.strptime(last_date, fmt)
                for i in range(1, periods + 1):
                    # Add months
                    month = (dt.month - 1 + i) % 12 + 1
                    year  = dt.year + (dt.month - 1 + i) // 12
                    future.append(f"{year:04d}-{month:02d}")
                return future
            except ValueError:
                continue
    except Exception:
        pass

    # Fallback: T+N labels
    return [f"T+{i}" for i in range(1, periods + 1)]


# ── Main service class ────────────────────────────────────────────────────────

class ForecastingService:
    """
    Advanced time-series forecasting service.

    Auto-selects method based on data length:
    - STL (default, >= 12 points)
    - ARIMA (>= 8 points, when explicitly requested)
    - Linear (< 12 points fallback)
    """

    def forecast(
        self,
        series: list[float],
        dates: list[str],
        periods: int = 6,
        method: Literal["stl", "arima", "linear"] = "stl",
    ) -> ForecastResult:
        """
        Generate probabilistic forecast.

        Args:
            series:   historical values (chronological order)
            dates:    corresponding period labels
            periods:  number of future periods to forecast
            method:   "stl" | "arima" | "linear"

        Returns:
            ForecastResult with forecast, change_points, seasonality
        """
        n = len(series)

        if n < MIN_POINTS_LINEAR:
            logger.warning(
                "ForecastingService: only %d points, need %d minimum",
                n, MIN_POINTS_LINEAR,
            )
            return ForecastResult(
                method="none", historical=[], forecast=[],
                change_points=[], seasonality={},
                summary="Yeterli veri yok (minimum 4 nokta gerekli)",
            )

        # Auto-downgrade method if insufficient data
        if method == "stl" and n < MIN_POINTS_STL:
            logger.debug("Insufficient data for STL (%d < %d), using linear", n, MIN_POINTS_STL)
            method = "linear"
        elif method == "arima" and n < MIN_POINTS_ARIMA:
            logger.debug("Insufficient data for ARIMA (%d < %d), using linear", n, MIN_POINTS_ARIMA)
            method = "linear"

        if method == "stl":
            return _stl_forecast(series, dates, periods)
        elif method == "arima":
            return _arima_forecast(series, dates, periods)
        else:
            return _linear_forecast(series, dates, periods)

    def detect_trend_changes(
        self,
        series: list[float],
        dates: list[str],
        window: int = 3,
        threshold_pct: float = 0.15,
    ) -> list[dict[str, Any]]:
        """Public wrapper for trend change detection."""
        return _detect_trend_changes(series, dates, window, threshold_pct)
