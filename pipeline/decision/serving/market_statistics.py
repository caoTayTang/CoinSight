"""Deterministic daily market aggregates and closed-hour trend diagnostics."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _max_drawdown(close: np.ndarray) -> float:
    peaks = np.maximum.accumulate(close)
    return float(np.min(close / peaks - 1.0))


class MarketStatisticsService:
    def daily_statistics(self, candles: pd.DataFrame, days: int) -> dict:
        frame = candles.sort_values("open_time").tail(days + 1).copy()
        if len(frame) < days + 1:
            raise ValueError(f"daily statistics require at least {days + 1} candles")
        close = frame["close_price"].to_numpy(dtype=np.float64)
        returns = np.diff(np.log(close))
        volume = frame["volume_quote"].to_numpy(dtype=np.float64)
        volume_change = np.diff(np.log1p(volume))
        selected = frame.iloc[1:]
        ranges = np.log(
            selected["high_price"].to_numpy(dtype=np.float64)
            / selected["low_price"].to_numpy(dtype=np.float64)
        )
        return {
            "sample_count": days,
            "first_day": pd.Timestamp(selected.iloc[0]["open_time"]).isoformat(),
            "last_day": pd.Timestamp(selected.iloc[-1]["open_time"]).isoformat(),
            "cumulative_log_return": float(np.sum(returns)),
            "cumulative_return": float(np.exp(np.sum(returns)) - 1.0),
            "mean_daily_return": float(np.mean(returns)),
            "median_daily_return": float(np.median(returns)),
            "realized_volatility": float(np.std(returns, ddof=0)),
            "annualized_volatility": float(np.std(returns, ddof=0) * np.sqrt(365)),
            "maximum_drawdown": _max_drawdown(close),
            "highest_close_usdt": float(np.max(selected["close_price"])),
            "lowest_close_usdt": float(np.min(selected["close_price"])),
            "average_quote_volume": float(np.mean(selected["volume_quote"])),
            "mean_log_volume_change": float(np.mean(volume_change)),
            "average_high_low_range": float(np.mean(ranges)),
            "up_days": int((returns > 0).sum()),
            "down_or_flat_days": int((returns <= 0).sum()),
            "up_day_ratio": float((returns > 0).mean()),
        }

    def hourly_trend(self, candles: pd.DataFrame, hours: int) -> dict:
        frame = candles.sort_values("open_time").tail(hours + 1).copy()
        if len(frame) < hours + 1:
            raise ValueError(f"hourly trend requires at least {hours + 1} candles")
        close_all = frame["close_price"].to_numpy(dtype=np.float64)
        close = close_all[-hours:]
        x = np.arange(hours, dtype=np.float64)
        y = np.log(close)
        slope, intercept = np.polyfit(x, y, 1)
        fitted = intercept + slope * x
        residual = float(np.sum((y - fitted) ** 2))
        total = float(np.sum((y - y.mean()) ** 2))
        r_squared = 1.0 if total == 0 and residual == 0 else 0.0 if total == 0 else 1 - residual / total
        returns = np.diff(np.log(close_all))
        series = pd.Series(close_all)
        ema24 = float(series.ewm(span=24, adjust=False).mean().iloc[-1])
        ema168 = (
            float(series.ewm(span=168, adjust=False).mean().iloc[-1])
            if hours >= 168 else None
        )
        latest = float(close_all[-1])
        return {
            "sample_count": hours,
            "first_hour": pd.Timestamp(frame.iloc[-hours]["open_time"]).isoformat(),
            "last_hour": pd.Timestamp(frame.iloc[-1]["open_time"]).isoformat(),
            "slope_per_hour": float(slope),
            "regression_r_squared": float(r_squared),
            "cumulative_return": float(np.exp(np.sum(returns)) - 1.0),
            "up_candle_ratio": float((returns > 0).mean()),
            "realized_volatility": float(np.std(returns, ddof=0)),
            "maximum_drawdown": _max_drawdown(close_all),
            "close_vs_ema_24h": latest / ema24 - 1.0,
            "close_vs_ema_168h": None if ema168 is None else latest / ema168 - 1.0,
            "direction": "up" if slope > 0 else "down" if slope < 0 else "flat",
            "interpretation": "closed-hour log-price regression; low R-squared means a weak/noisy trend",
        }
