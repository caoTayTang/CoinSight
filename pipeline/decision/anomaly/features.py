"""Leakage-safe feature extraction for hourly and daily anomaly models.

The value at timestamp ``t`` may use the closed candle at ``t``.  Every
reference distribution is shifted by one period, so that candle never helps
define the normal range against which it is scored.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PRICE_COLUMNS = ("open_price", "high_price", "low_price", "close_price")
REQUIRED_COLUMNS = ("open_time", *PRICE_COLUMNS, "volume_quote", "trade_count")

HOURLY_FEATURES = (
    "return_z_168h",
    "body_z_168h",
    "range_ratio_168h",
    "volume_z_168h",
    "trades_z_168h",
    "momentum_6h_z",
    "volatility_ratio_6_168h",
    "close_position",
    "upper_wick_fraction",
    "lower_wick_fraction",
)

DAILY_FEATURES = (
    "return_z_30d",
    "body_z_30d",
    "range_ratio_30d",
    "volume_z_30d",
    "volume_z_90d",
    "trades_z_30d",
    "momentum_7d_z",
    "momentum_30d_z",
    "volatility_ratio_7_30d",
    "volatility_ratio_30_90d",
    "close_position",
    "upper_wick_fraction",
    "lower_wick_fraction",
    "drawdown_30d",
    "drawdown_90d",
)


def feature_names(frequency: str) -> tuple[str, ...]:
    if frequency == "1h":
        return HOURLY_FEATURES
    if frequency == "1d":
        return DAILY_FEATURES
    raise ValueError("frequency must be 1h or 1d")


def required_candles(frequency: str) -> int:
    # Hourly: current return + 168 past returns. Daily: 30-day momentum
    # standardized against 90 past momentum observations.
    return 170 if frequency == "1h" else 121 if frequency == "1d" else _bad_frequency()


def _bad_frequency():
    raise ValueError("frequency must be 1h or 1d")


def _validated_grid(raw: pd.DataFrame, frequency: str) -> tuple[pd.DataFrame, pd.Series]:
    missing = set(REQUIRED_COLUMNS) - set(raw.columns)
    if missing:
        raise ValueError(f"candles are missing columns: {sorted(missing)}")
    frame = raw.loc[:, REQUIRED_COLUMNS].copy()
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
    frame = frame.sort_values("open_time").reset_index(drop=True)
    if frame["open_time"].duplicated().any():
        raise ValueError("duplicate candle timestamps are not allowed")
    numeric = frame[[*PRICE_COLUMNS, "volume_quote", "trade_count"]].apply(
        pd.to_numeric, errors="coerce"
    )
    finite = np.isfinite(numeric).all(axis=1)
    positive = numeric[list(PRICE_COLUMNS)].gt(0).all(axis=1)
    bounds = (
        numeric["high_price"].ge(
            numeric[["open_price", "low_price", "close_price"]].max(axis=1)
        )
        & numeric["low_price"].le(
            numeric[["open_price", "high_price", "close_price"]].min(axis=1)
        )
    )
    nonnegative = numeric[["volume_quote", "trade_count"]].ge(0).all(axis=1)
    valid = finite & positive & bounds & nonnegative
    frame[numeric.columns] = numeric
    frame = frame.set_index("open_time")
    step = pd.Timedelta(hours=1) if frequency == "1h" else pd.Timedelta(days=1)
    contiguous = frame.index.to_series().diff().eq(step)
    contiguous.iloc[0] = True
    return frame, valid.set_axis(frame.index) & contiguous


def _zscore_current(value: pd.Series, periods: int, floor: float) -> pd.Series:
    history = value.shift(1)
    mean = history.rolling(periods, min_periods=periods).mean()
    std = history.rolling(periods, min_periods=periods).std(ddof=0).clip(lower=floor)
    return (value - mean) / std


def _shape_features(out: pd.DataFrame, o, h, l, c) -> None:
    span = (h - l).replace(0, np.nan)
    out["close_position"] = ((c - l) / span).fillna(0.5)
    out["upper_wick_fraction"] = (
        (h - pd.concat([o, c], axis=1).max(axis=1)) / span
    ).fillna(0.0)
    out["lower_wick_fraction"] = (
        (pd.concat([o, c], axis=1).min(axis=1) - l) / span
    ).fillna(0.0)


def _hourly(frame: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c, q, trades = (
        frame[name]
        for name in (
            "open_price", "high_price", "low_price", "close_price",
            "volume_quote", "trade_count",
        )
    )
    returns = np.log(c / c.shift(1))
    body = np.log(c / o)
    candle_range = (h - l) / o
    past_volatility = returns.shift(1).rolling(168, min_periods=168).std(ddof=0).clip(1e-6)
    past_range = candle_range.shift(1).rolling(168, min_periods=168).median().clip(1e-6)
    out = pd.DataFrame(index=frame.index)
    out["return_z_168h"] = returns / past_volatility
    out["body_z_168h"] = body / past_volatility
    out["range_ratio_168h"] = candle_range / past_range
    out["volume_z_168h"] = _zscore_current(np.log1p(q), 168, 0.05)
    out["trades_z_168h"] = _zscore_current(np.log1p(trades), 168, 0.05)
    momentum = np.log(c / c.shift(6))
    out["momentum_6h_z"] = momentum / (past_volatility * np.sqrt(6))
    out["volatility_ratio_6_168h"] = (
        returns.rolling(6, min_periods=6).std(ddof=0) / past_volatility
    )
    _shape_features(out, o, h, l, c)
    return out


def _daily(frame: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c, q, trades = (
        frame[name]
        for name in (
            "open_price", "high_price", "low_price", "close_price",
            "volume_quote", "trade_count",
        )
    )
    returns = np.log(c / c.shift(1))
    body = np.log(c / o)
    candle_range = (h - l) / o
    past_vol_30 = returns.shift(1).rolling(30, min_periods=30).std(ddof=0).clip(1e-6)
    past_vol_90 = returns.shift(1).rolling(90, min_periods=90).std(ddof=0).clip(1e-6)
    past_range_30 = candle_range.shift(1).rolling(30, min_periods=30).median().clip(1e-6)
    out = pd.DataFrame(index=frame.index)
    out["return_z_30d"] = returns / past_vol_30
    out["body_z_30d"] = body / past_vol_30
    out["range_ratio_30d"] = candle_range / past_range_30
    out["volume_z_30d"] = _zscore_current(np.log1p(q), 30, 0.05)
    out["volume_z_90d"] = _zscore_current(np.log1p(q), 90, 0.05)
    out["trades_z_30d"] = _zscore_current(np.log1p(trades), 30, 0.05)
    momentum_7 = np.log(c / c.shift(7))
    momentum_30 = np.log(c / c.shift(30))
    out["momentum_7d_z"] = _zscore_current(momentum_7, 90, 1e-5)
    out["momentum_30d_z"] = _zscore_current(momentum_30, 90, 1e-5)
    out["volatility_ratio_7_30d"] = (
        returns.rolling(7, min_periods=7).std(ddof=0) / past_vol_30
    )
    out["volatility_ratio_30_90d"] = (
        returns.rolling(30, min_periods=30).std(ddof=0) / past_vol_90
    )
    _shape_features(out, o, h, l, c)
    out["drawdown_30d"] = c / c.rolling(30, min_periods=30).max() - 1.0
    out["drawdown_90d"] = c / c.rolling(90, min_periods=90).max() - 1.0
    return out


def extract_anomaly_features(raw: pd.DataFrame, frequency: str) -> pd.DataFrame:
    """Return one row per candle; invalid/incomplete causal windows are NaN."""
    frame, row_valid = _validated_grid(raw, frequency)
    out = _hourly(frame) if frequency == "1h" else _daily(frame) if frequency == "1d" else _bad_frequency()
    periods = required_candles(frequency)
    full_window = row_valid.rolling(periods, min_periods=periods).sum().eq(periods)
    return out.loc[:, feature_names(frequency)].replace([np.inf, -np.inf], np.nan).where(full_window)
