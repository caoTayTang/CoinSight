"""Validation-only experimental feature sets; never changes hourly-return-v1.

All windows are <=168 hourly returns (169 raw candles), use no future or learned
whole-dataset normalization, and preserve the original accepted sample index.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.decision.hourly_features import build_dataset, build_inputs, prepare_grid

FEATURE_VERSION = 'hourly-return-v2-experimental'


def ratio(numerator, denominator, when_zero=0.):
    result = numerator / denominator.where(denominator.ne(0))
    return result.where(denominator.ne(0), when_zero).where(numerator.notna() & denominator.notna())


def build_experimental_inputs(frame):
    """Inference features: the latest 169 raw candles suffice, no label required."""
    base, _, grid, _ = build_inputs(frame)
    _, raw, _ = prepare_grid(frame)
    close, high, low, volume, trades = (raw[column] for column in
        ['close_price', 'high_price', 'low_price', 'volume_quote', 'trade_count'])
    returns = np.log(close / close.shift(1))
    extra = pd.DataFrame(index=grid.index)
    for window in (6, 24, 72, 168):
        mean = returns.rolling(window, min_periods=window).mean()
        std = returns.rolling(window, min_periods=window).std(ddof=0)
        momentum = np.log(close / close.shift(window))
        extra[f'vol_normalized_momentum_{window}'] = ratio(momentum, std * np.sqrt(window))
        extra[f'mean_return_{window}'] = mean
        extra[f'median_return_{window}'] = returns.rolling(window, min_periods=window).median()
        rolling_mean_close = close.rolling(window, min_periods=window).mean()
        extra[f'log_distance_mean_close_{window}'] = np.log(close / rolling_mean_close)
    for window in (24, 168):
        rolling_high = high.rolling(window, min_periods=window).max()
        rolling_low = low.rolling(window, min_periods=window).min()
        extra[f'position_in_range_{window}'] = ratio(close - rolling_low, rolling_high - rolling_low, .5)
        extra[f'distance_high_{window}'] = np.log(close / rolling_high)
        extra[f'distance_low_{window}'] = np.log(close / rolling_low)
        # Signed-candle-volume proxy, NOT actual buyer/seller order flow.
        signed_volume = (np.sign(returns) * volume).rolling(window, min_periods=window).sum()
        total_volume = volume.rolling(window, min_periods=window).sum()
        extra[f'signed_candle_volume_{window}'] = ratio(signed_volume, total_volume)
    for window in (14, 48):
        changes = close.diff()
        gain = changes.clip(lower=0).rolling(window, min_periods=window).mean()
        loss = (-changes.clip(upper=0)).rolling(window, min_periods=window).mean()
        # Simple rolling RSI/100, not Wilder's infinite-history smoothing.
        extra[f'rsi_fraction_{window}'] = ratio(gain, gain + loss, .5)
    std6 = returns.rolling(6, min_periods=6).std(ddof=0)
    std24 = returns.rolling(24, min_periods=24).std(ddof=0)
    std168 = returns.rolling(168, min_periods=168).std(ddof=0)
    extra['vol_ratio_6_24'] = ratio(std6, std24)
    extra['vol_ratio_24_168'] = ratio(std24, std168)
    extra['return_z_24'] = ratio(returns - returns.rolling(24, min_periods=24).mean(), std24)
    extra['absolute_return_rank_168'] = returns.abs().rolling(168, min_periods=168).rank(pct=True)
    extra['log_quote_per_trade'] = np.log1p(ratio(volume, trades))
    extra['trade_intensity_24'] = ratio(trades, trades.rolling(24, min_periods=24).mean())
    # Timestamp of the target opening is known at cutoff; no target price is used.
    target_clock = grid.index + pd.Timedelta(hours=1)
    extra['target_hour_sin'] = np.sin(2 * np.pi * target_clock.hour / 24)
    extra['target_hour_cos'] = np.cos(2 * np.pi * target_clock.hour / 24)
    context_ok = base.notna().all(axis=1)
    extra = extra.replace([np.inf, -np.inf], np.nan).where(context_ok)
    if extra.loc[context_ok].isna().any().any():
        raise ValueError('Engineered features must not silently remove or impute original accepted samples')
    expanded = pd.concat([base, extra], axis=1)
    compact = expanded[[column for column in expanded if '_lag_' not in column]]
    return {'base':base, 'expanded':expanded, 'compact':compact}


def feature_sets(frame):
    """Training wrapper adds labels; never makes inference depend on the future."""
    _, meta, audit = build_dataset(frame)
    sets = build_experimental_inputs(frame)
    return {name:features.loc[meta.index] for name,features in sets.items()}, meta, audit
