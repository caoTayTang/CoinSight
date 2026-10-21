"""Causal BTC hourly features: 169 raw candles -> one row, never fill gaps."""
from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_VERSION = 'hourly-return-v1'
LAGS = (1, 2, 3, 6, 12, 24, 48, 72, 167)
LAG_SERIES = ('log_return', 'open_close_return', 'range_pct', 'log_volume', 'volume_change', 'log_trade_count')
RAW_COLUMNS = ('open_price', 'high_price', 'low_price', 'close_price', 'volume_quote', 'trade_count')
BASE_COLUMNS = ('log_return', 'open_close_return', 'range_pct', 'close_position', 'upper_wick',
                'lower_wick', 'log_volume', 'volume_change', 'log_trade_count',
                'hour_sin', 'hour_cos', 'weekday_sin', 'weekday_cos')
FEATURE_COLUMNS = (list(BASE_COLUMNS) + [f'{name}_lag_{lag}' for name in LAG_SERIES for lag in LAGS]
                   + [f'momentum_{window}' for window in (6, 12, 24, 72, 168)]
                   + [f'return_std_{window}' for window in (6, 24, 72, 168)]
                   + [f'volume_z_{window}' for window in (24, 168)])


def prepare_grid(frame):
    frame = frame.copy()
    frame['open_time'] = pd.to_datetime(frame.open_time, utc=True)
    if frame.open_time.isna().any() or (frame.open_time != frame.open_time.dt.floor('h')).any():
        raise ValueError('Hourly snapshot contains unaligned or missing timestamps')
    if frame.open_time.duplicated().any():
        raise ValueError('Duplicate candle timestamps in hourly snapshot')
    if 'symbol' in frame and (frame.symbol.nunique() != 1 or frame.symbol.iloc[0] != 'BTC'):
        raise ValueError('Initial hourly model accepts BTC only')
    if frame.empty:
        raise ValueError('Empty hourly snapshot')
    frame = frame.sort_values('open_time').set_index('open_time')
    index = pd.date_range(frame.index.min(), frame.index.max(), freq='h', tz='UTC')
    grid = frame.reindex(index)
    values = grid[list(RAW_COLUMNS)].astype(float)
    valid = (np.isfinite(values).all(axis=1)
             & values[['open_price', 'high_price', 'low_price', 'close_price']].gt(0).all(axis=1)
             & values.volume_quote.ge(0) & values.trade_count.ge(0)
             & values.trade_count.eq(np.floor(values.trade_count))
             & values.high_price.ge(values[['open_price', 'close_price', 'low_price']].max(axis=1))
             & values.low_price.le(values[['open_price', 'close_price']].min(axis=1)))
    values = values.where(valid)
    return grid, values, valid


def build_inputs(frame):
    """Inference feature builder. Does not require or read the target candle."""
    grid, values, valid = prepare_grid(frame)
    o, h, l, c, v, trades = (values[column] for column in RAW_COLUMNS)
    features = pd.DataFrame(index=grid.index)
    features['log_return'] = np.log(c / c.shift(1))
    features['open_close_return'] = np.log(c / o)
    features['range_pct'] = (h - l) / o
    candle_range = h - l
    features['close_position'] = ((c - l) / candle_range.where(candle_range.ne(0))).where(candle_range.ne(0), .5).where(valid)
    features['upper_wick'] = (h - pd.concat([o, c], axis=1).max(axis=1)) / o
    features['lower_wick'] = (pd.concat([o, c], axis=1).min(axis=1) - l) / o
    features['log_volume'] = np.log1p(v)
    features['volume_change'] = np.log1p(v).diff()
    features['log_trade_count'] = np.log1p(trades)
    for name, period, clock in [('hour', 24, grid.index.hour), ('weekday', 7, grid.index.dayofweek)]:
        features[f'{name}_sin'] = np.sin(2 * np.pi * clock / period)
        features[f'{name}_cos'] = np.cos(2 * np.pi * clock / period)
    for name in LAG_SERIES:
        for lag in LAGS:
            features[f'{name}_lag_{lag}'] = features[name].shift(lag)
    for window in (6, 12, 24, 72, 168):
        features[f'momentum_{window}'] = np.log(c / c.shift(window))
    for window in (6, 24, 72, 168):
        features[f'return_std_{window}'] = features.log_return.rolling(window, min_periods=window).std(ddof=0)
    for window in (24, 168):
        mean = v.rolling(window, min_periods=window).mean()
        std = v.rolling(window, min_periods=window).std(ddof=0)
        features[f'volume_z_{window}'] = ((v - mean) / std.where(std.ne(0))).where(std.ne(0), 0).where(std.notna())
    # Require every raw candle, even if a sparse lag list would otherwise skip a gap.
    context_ok = valid.rolling(169, min_periods=169).sum().eq(169)
    features = features[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan).where(context_ok)
    # Base return is masked until full context; calculate baseline from raw causal returns.
    baseline_mean24 = np.log(c / c.shift(1)).rolling(24, min_periods=24).mean().where(context_ok)
    return features, baseline_mean24, grid, valid


def build_dataset(frame):
    features, baseline_mean24, grid, valid = build_inputs(frame)
    close = grid.close_price.astype(float).where(valid)
    target = np.log(close.shift(-1) / close).where(valid.shift(-1, fill_value=False))
    meta = pd.DataFrame({
        'input_open_time':grid.index, 'cutoff_time':grid.index + pd.Timedelta(hours=1),
        'target_open_time':grid.index + pd.Timedelta(hours=1),
        'target_close_time':grid.index + pd.Timedelta(hours=2),
        'reference_close_usdt':close, 'actual_close_usdt':close.shift(-1),
        'actual_log_return':target, 'mean24_log_return':baseline_mean24,
    }, index=grid.index)
    complete_features = features.notna().all(axis=1)
    keep = complete_features & target.notna() & baseline_mean24.notna()
    reason = pd.Series('accepted', index=grid.index)
    reason.loc[~complete_features] = 'context_gap_invalid_or_warmup'
    reason.loc[complete_features & target.isna()] = 'target_missing_or_invalid'
    return features.loc[keep], meta.loc[keep], pd.DataFrame({
        'target_open_time':grid.index + pd.Timedelta(hours=1),
        'reason':reason,
    }, index=grid.index)


def chronological_split(meta, validation_start, test_start):
    validation_start = pd.Timestamp(validation_start)
    test_start = pd.Timestamp(test_start)
    if validation_start.tzinfo is None or test_start.tzinfo is None or validation_start >= test_start:
        raise ValueError('Split boundaries must be ordered timezone-aware timestamps')
    times = meta.target_open_time
    splits = {'train':times.lt(validation_start),
              'validation':times.ge(validation_start) & times.lt(test_start),
              'test':times.ge(test_start)}
    for name, mask in splits.items():
        if not mask.any():
            raise ValueError(f'Missing partition: {name}; backfill history, do not change split silently')
    # Last training label can close exactly at the first validation cutoff.
    for left, right in [('train', 'validation'), ('validation', 'test')]:
        if meta.loc[splits[left], 'target_close_time'].max() > meta.loc[splits[right], 'cutoff_time'].min():
            raise ValueError(f'Label crosses the {left}/{right} decision boundary')
    return splits
