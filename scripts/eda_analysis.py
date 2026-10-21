"""Deterministic EDA calculations. Never fill prices or bridge candle gaps."""
from __future__ import annotations

import numpy as np
import pandas as pd


MEASURES = ['open_price', 'high_price', 'low_price', 'close_price', 'volume_quote']


def validate_frame(frame):
    frame = frame.copy()
    frame['open_time'] = pd.to_datetime(frame['open_time'], utc=True)
    if frame.duplicated(['symbol', 'open_time']).any():
        raise ValueError('Duplicate symbol/time in snapshot; inspect warehouse grain before EDA')
    values = frame[MEASURES].astype(float)
    invalid = (~np.isfinite(values).all(axis=1)
               | ~values[['open_price', 'high_price', 'low_price', 'close_price']].gt(0).all(axis=1)
               | values.volume_quote.lt(0)
               | values.high_price.lt(values[['open_price', 'close_price', 'low_price']].max(axis=1))
               | values.low_price.gt(values[['open_price', 'close_price']].min(axis=1)))
    if invalid.any():
        raise ValueError(f'{int(invalid.sum())} invalid OHLC/volume rows; fix warehouse before EDA')
    frame[MEASURES] = values
    return frame.sort_values(['symbol', 'open_time']).reset_index(drop=True)


def coverage(frame, symbols, start, end, step):
    index = pd.date_range(start, end, freq=step, inclusive='left', tz='UTC')
    rows = []
    for symbol in symbols:
        group = frame.loc[frame.symbol.eq(symbol)]
        observed = pd.DatetimeIndex(group.open_time)
        internal = (len(pd.date_range(observed.min(), observed.max(), freq=step)) - len(observed)) if len(observed) else 0
        rows.append({'symbol': symbol, 'rows': len(observed),
                     'first': observed.min() if len(observed) else None,
                     'last': observed.max() if len(observed) else None,
                     'internal_missing': internal,
                     'requested_missing': len(index.difference(observed)),
                     'requested_expected': len(index),
                     'lineage_missing': int(group.sha256.isna().sum()) if 'sha256' in group else len(group)})
    return pd.DataFrame(rows), index


def price_panels(frame, symbols, index):
    close = frame.pivot(index='open_time', columns='symbol', values='close_price').reindex(index=index, columns=symbols)
    # Reindex first so a missing candle produces NaN instead of a multi-period return.
    simple = close.pct_change(fill_method=None)
    log = np.log(close / close.shift(1))
    return close, simple, log


def risk_table(close, simple, log, periods_per_year):
    rows = []
    for symbol in close:
        prices = close[symbol].dropna()
        returns = simple[symbol].dropna()
        if prices.empty:
            continue
        rows.append({'symbol': symbol, 'n_returns': len(returns),
                     'total_return_pct': (prices.iloc[-1] / prices.iloc[0] - 1) * 100,
                     'up_pct': returns.gt(0).mean() * 100,
                     'flat_pct': returns.eq(0).mean() * 100,
                     'annual_vol_pct': log[symbol].std() * np.sqrt(periods_per_year) * 100,
                     'max_drawdown_pct': (prices / prices.cummax() - 1).min() * 100,
                     'worst_return_pct': returns.min() * 100,
                     'best_return_pct': returns.max() * 100})
    return pd.DataFrame(rows)


def block_mean_interval(values, block=7, repeats=500, seed=42):
    """Exploratory moving-block bootstrap CI; not an independence assumption."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < max(30, 2 * block):
        return None
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(values) - block + 1, size=(repeats, int(np.ceil(len(values) / block))))
    offsets = np.arange(block)
    samples = values[(starts[:, :, None] + offsets).reshape(repeats, -1)[:, :len(values)]]
    return tuple(float(v) for v in np.quantile(samples.mean(axis=1), [.025, .975]))


def safe_correlation(left, right):
    pairs = pd.DataFrame({'left': left, 'right': right}).dropna()
    if len(pairs) < 2 or pairs.left.nunique() < 2 or pairs.right.nunique() < 2:
        return float('nan')
    return float(pairs.left.corr(pairs.right))


def lag_probe(returns, split_at, block=7):
    """Fixed rule: sign of previous return predicts next direction.

    Split is a calendar timestamp; baseline majority direction is chosen only on
    training rows. No rule selection or parameter fitting on holdout.
    """
    pairs = pd.DataFrame({'previous': returns.shift(1), 'target': returns}).dropna()
    train = pairs.loc[pairs.index < split_at]
    test = pairs.loc[pairs.index >= split_at]
    if len(train) < 60 or len(test) < 30:
        return {'available': False, 'train_n': len(train), 'test_n': len(test)}
    majority_up = bool(train.target.gt(0).mean() >= .5)
    actual_up = test.target.gt(0)
    rule_ok = test.previous.gt(0).eq(actual_up)
    baseline_ok = actual_up.eq(majority_up)
    difference = (rule_ok.astype(float) - baseline_ok.astype(float)).to_numpy()
    ci = block_mean_interval(difference, block=block)
    return {'available': True, 'train_n': len(train), 'test_n': len(test),
            'split_at': split_at.isoformat(), 'test_first': test.index.min().isoformat(),
            'test_last': test.index.max().isoformat(), 'majority_up_from_train': majority_up,
            'test_up_pct': float(actual_up.mean() * 100),
            'train_lag_correlation': safe_correlation(train.previous, train.target),
            'test_lag_correlation': safe_correlation(test.previous, test.target),
            'rule_accuracy_pct': float(rule_ok.mean() * 100),
            'baseline_accuracy_pct': float(baseline_ok.mean() * 100),
            'accuracy_difference_pp': float(difference.mean() * 100),
            'difference_ci_pp': [v * 100 for v in ci] if ci else None,
            'zero_return_mae': float(test.target.abs().mean()),
            'previous_return_mae': float((test.target - test.previous).abs().mean()),
            'after_up_mean_pct': float(test.loc[test.previous.gt(0), 'target'].mean() * 100),
            'after_down_or_flat_mean_pct': float(test.loc[test.previous.le(0), 'target'].mean() * 100),
            'after_up_n': int(test.previous.gt(0).sum()),
            'after_down_or_flat_n': int(test.previous.le(0).sum())}
