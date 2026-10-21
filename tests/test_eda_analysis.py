import numpy as np
import pandas as pd
import pytest

from scripts.eda_analysis import block_mean_interval, coverage, lag_probe, price_panels, validate_frame
from scripts.run_eda import describe


def sample_frame():
    index = pd.date_range('2024-01-01', periods=400, tz='UTC')
    random = np.random.default_rng(1)
    rows = []
    for symbol in ['BTC', 'ETH']:
        prices = 100 * np.exp(np.cumsum(random.normal(0, .01, len(index))))
        for stamp, price in zip(index, prices):
            rows.append({'symbol': symbol, 'open_time': stamp, 'open_price': price,
                         'high_price': price * 1.01, 'low_price': price * .99,
                         'close_price': price, 'volume_quote': 1000, 'sha256': 'example'})
    return pd.DataFrame(rows)


def test_missing_candles_are_not_filled_and_returns_do_not_bridge_gap():
    frame = sample_frame()
    missing = pd.Timestamp('2024-02-01', tz='UTC')
    frame = frame.loc[~(frame.symbol.eq('BTC') & frame.open_time.eq(missing))]
    cov, index = coverage(frame, ['BTC', 'ETH'], '2024-01-01', '2024-03-01', pd.Timedelta(days=1))
    # Limit frame to the requested scope as the query does.
    frame = frame.loc[frame.open_time < pd.Timestamp('2024-03-01', tz='UTC')]
    close, simple, log = price_panels(frame, ['BTC', 'ETH'], index)
    assert pd.isna(close.loc[missing, 'BTC'])
    assert pd.isna(simple.loc[missing, 'BTC'])
    assert pd.isna(simple.loc[missing + pd.Timedelta(days=1), 'BTC'])
    assert pd.isna(log.loc[missing + pd.Timedelta(days=1), 'BTC'])
    assert cov.loc[cov.symbol.eq('BTC'), 'requested_missing'].iloc[0] == 1


def test_coverage_counts_missing_at_requested_edges():
    frame = sample_frame()
    frame = frame.loc[frame.open_time < pd.Timestamp('2025-02-04', tz='UTC')]
    cov, _ = coverage(frame, ['BTC'], '2023-12-31', '2025-02-05', pd.Timedelta(days=1))
    assert cov.iloc[0].internal_missing == 0
    assert cov.iloc[0].requested_missing == 2


def test_invalid_ohlc_and_duplicates_fail_explicitly():
    frame = sample_frame()
    with pytest.raises(ValueError, match='Duplicate'):
        validate_frame(pd.concat([frame, frame.iloc[:1]]))
    frame.loc[0, 'high_price'] = .01
    with pytest.raises(ValueError, match='invalid OHLC'):
        validate_frame(frame)


def test_baseline_direction_is_fitted_on_train_not_holdout():
    index = pd.date_range('2024-01-01', periods=200, tz='UTC')
    returns = pd.Series([.01] * 130 + [-.02] * 70, index=index)
    probe = lag_probe(returns, index[130])
    assert probe['majority_up_from_train'] is True
    assert probe['baseline_accuracy_pct'] == 0
    assert probe['test_n'] == 70


def test_changes_after_split_cannot_change_train_probe_or_volatility_threshold():
    frame = sample_frame()
    start = pd.Timestamp('2024-01-01', tz='UTC')
    end = start + pd.Timedelta(days=400)
    original = describe(frame, ['BTC', 'ETH'], start, end, '1d')
    altered = frame.copy()
    mask = altered.open_time >= original['split_at']
    for measure in ['open_price', 'high_price', 'low_price', 'close_price']:
        altered.loc[mask, measure] *= 2
    new = describe(altered, ['BTC', 'ETH'], start, end, '1d')
    assert new['regime_threshold'] == original['regime_threshold']
    assert new['probes']['BTC']['train_lag_correlation'] == original['probes']['BTC']['train_lag_correlation']
    assert new['probes']['BTC']['majority_up_from_train'] == original['probes']['BTC']['majority_up_from_train']


def test_block_bootstrap_is_deterministic():
    values = np.linspace(-1, 1, 200)
    assert block_mean_interval(values) == block_mean_interval(values)
    assert block_mean_interval([1, 2]) is None


def test_snapshot_round_trip_preserves_numerical_results(tmp_path):
    frame = sample_frame()
    start = pd.Timestamp('2024-01-01', tz='UTC')
    end = start + pd.Timedelta(days=400)
    before = describe(frame, ['BTC', 'ETH'], start, end, '1d')
    path = tmp_path / 'snapshot.csv'
    frame.to_csv(path, index=False, float_format='%.17g')
    loaded = pd.read_csv(path, float_precision='round_trip')
    after = describe(loaded, ['BTC', 'ETH'], start, end, '1d')
    assert before['probes'] == after['probes']
    pd.testing.assert_frame_equal(before['risk'], after['risk'])
