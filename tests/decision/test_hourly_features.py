import numpy as np
import pandas as pd
import pytest

from pipeline.decision.hourly_features import (FEATURE_COLUMNS, build_dataset, build_inputs,
                                               chronological_split)
from pipeline.decision.hourly_model import goal_passed, paired_relative_ci, regression_metrics


def candles(n=500):
    rng = np.random.default_rng(42)
    close = 100 * np.exp(np.cumsum(rng.normal(0, .005, n)))
    open_price = close * np.exp(rng.normal(0, .001, n))
    return pd.DataFrame({'symbol':'BTC', 'open_time':pd.date_range('2024-01-01', periods=n, freq='h', tz='UTC'),
                         'open_price':open_price, 'high_price':np.maximum(open_price, close) * 1.001,
                         'low_price':np.minimum(open_price, close) * .999, 'close_price':close,
                         'volume_quote':rng.uniform(100, 1000, n), 'trade_count':rng.integers(1, 100, n)})


def test_169_raw_candles_make_168_hour_features_without_target():
    raw = candles(169)
    features, baseline, _, _ = build_inputs(raw)
    assert features.notna().all(axis=1).sum() == 1
    assert len(FEATURE_COLUMNS) == 78
    assert list(features.columns) == FEATURE_COLUMNS
    assert np.isfinite(features.iloc[-1]).all()
    assert np.isfinite(baseline.iloc[-1])
    # Training still needs the next candle; inference must not.
    assert build_dataset(raw)[0].empty
    assert len(build_dataset(candles(170))[0]) == 1


def test_future_changes_do_not_change_past_inputs():
    raw = candles()
    before = build_inputs(raw)[0]
    changed = raw.copy()
    changed.loc[301:, ['open_price', 'high_price', 'low_price', 'close_price']] *= 2
    changed.loc[301:, 'volume_quote'] *= 10
    after = build_inputs(changed)[0]
    pd.testing.assert_frame_equal(before.iloc[:301], after.iloc[:301])


def test_no_raw_history_before_169_candle_context_is_used():
    raw = candles()
    before = build_inputs(raw)[0].iloc[-1]
    raw.loc[:100, ['open_price', 'high_price', 'low_price', 'close_price']] *= 2
    raw.loc[:100, 'volume_quote'] *= 2
    after = build_inputs(raw)[0].iloc[-1]
    np.testing.assert_allclose(before, after, atol=1e-10, rtol=1e-10)


def test_gap_cannot_be_bridged_by_sparse_lags_or_target():
    raw = candles()
    missing_time = raw.loc[200, 'open_time']
    features, meta, audit = build_dataset(raw.drop(index=200))
    forbidden = pd.date_range(missing_time - pd.Timedelta(hours=1), missing_time + pd.Timedelta(hours=168), freq='h')
    assert not features.index.isin(forbidden).any()
    assert (meta.target_open_time - meta.input_open_time).eq(pd.Timedelta(hours=1)).all()
    assert 'context_gap_invalid_or_warmup' in audit.reason.values


def test_duplicates_and_unaligned_times_fail_snapshot():
    raw = candles()
    with pytest.raises(ValueError, match='Duplicate'):
        build_inputs(pd.concat([raw, raw.iloc[[0]]]))
    raw.loc[0, 'open_time'] += pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match='unaligned'):
        build_inputs(raw)


def test_invalid_ohlc_or_trade_count_excludes_context():
    for column, value in [('high_price', 1), ('trade_count', 1.5), ('volume_quote', -1)]:
        raw = candles()
        raw[column] = raw[column].astype(float)
        raw.loc[200, column] = value
        features, _, _ = build_dataset(raw)
        assert raw.loc[200, 'open_time'] not in features.index
        assert raw.loc[368, 'open_time'] not in features.index
        assert raw.loc[369, 'open_time'] in features.index


def test_flat_price_zero_volume_remains_finite():
    raw = candles(170)
    raw[['open_price', 'high_price', 'low_price', 'close_price']] = 100.
    raw[['volume_quote', 'trade_count']] = 0
    features, _, _ = build_dataset(raw)
    assert len(features) == 1
    assert features.iloc[0].close_position == .5
    assert features.iloc[0].volume_z_168 == 0
    assert np.isfinite(features.to_numpy()).all()


def test_chronological_split_uses_target_and_label_close_boundary():
    raw = candles()
    _, meta, _ = build_dataset(raw)
    boundary, test_start = raw.loc[250, 'open_time'], raw.loc[350, 'open_time']
    masks = chronological_split(meta, boundary, test_start)
    assert meta.loc[masks['train'], 'target_open_time'].max() < boundary
    assert meta.loc[masks['validation'], 'target_open_time'].min() == boundary
    assert meta.loc[masks['train'], 'target_close_time'].max() <= meta.loc[masks['validation'], 'cutoff_time'].min()
    assert meta.loc[masks['test'], 'target_open_time'].min() == test_start
    with pytest.raises(ValueError, match='Missing partition'):
        chronological_split(meta, boundary, pd.Timestamp('2026-01-01', tz='UTC'))


def test_zero_return_baseline_has_relative_mae_one():
    metrics = regression_metrics([.01, -.02], [0, 0], [100, 100])
    assert metrics['relative_mae'] == 1
    assert metrics['mae_log_return'] == pytest.approx(.015)
    assert metrics['directional_accuracy_pct'] == 0  # sign(0)=0, not random up/down.
    assert not goal_passed(metrics, .95)
    better = regression_metrics([.01, -.02], [.005, -.01], [100, 100])
    assert goal_passed(better, .95)
    flat = regression_metrics([0, 0], [0, 0], [100, 100])
    assert flat['relative_mae'] is None
    assert not goal_passed(flat, .95)


def test_mae_units_and_nonfinite_predictions():
    result = regression_metrics([.01], [.008], [100])
    assert result['mae_log_return'] == pytest.approx(.002)
    assert result['mae_price_usdt'] == pytest.approx(100 * (np.exp(.01) - np.exp(.008)))
    with pytest.raises(ValueError, match='non-finite'):
        regression_metrics([.01], [np.inf], [100])


def test_block_ci_is_deterministic_and_does_not_cross_gaps():
    times = pd.date_range('2025-01-01', periods=72, freq='h', tz='UTC')
    first = paired_relative_ci(np.full(72, .01), np.full(72, .001), times)
    assert first == pytest.approx([.9, .9])
    assert first == paired_relative_ci(np.full(72, .01), np.full(72, .001), times)
    times_with_gaps = pd.date_range('2025-01-01', periods=72, freq='2h', tz='UTC')
    assert paired_relative_ci(np.full(72, .01), np.zeros(72), times_with_gaps) is None


def test_experimental_features_preserve_samples_and_are_causal():
    from pipeline.decision.hourly_engineering import feature_sets
    raw = candles()
    before, meta, _ = feature_sets(raw)
    assert len(before['base']) == len(before['expanded']) == len(before['compact']) == len(meta)
    assert before['expanded'].shape[1] > before['base'].shape[1]
    assert not any('_lag_' in column for column in before['compact'])
    raw.loc[301:, ['open_price', 'high_price', 'low_price', 'close_price']] *= 2
    raw.loc[301:, 'volume_quote'] *= 3
    after, _, _ = feature_sets(raw)
    cutoff = raw.loc[300, 'open_time']
    for name in before:
        pd.testing.assert_frame_equal(before[name].loc[:cutoff], after[name].loc[:cutoff])


def test_experimental_features_do_not_use_history_outside_context():
    from pipeline.decision.hourly_engineering import feature_sets
    raw = candles()
    before = feature_sets(raw)[0]['expanded'].iloc[-1]
    raw.loc[:100, ['open_price', 'high_price', 'low_price', 'close_price']] *= 2
    raw.loc[:100, 'volume_quote'] *= 3
    after = feature_sets(raw)[0]['expanded'].iloc[-1]
    np.testing.assert_allclose(before, after, atol=1e-9, rtol=1e-9)


def test_experimental_features_handle_flat_zero_activity():
    from pipeline.decision.hourly_engineering import feature_sets
    raw = candles(200)
    raw[['open_price', 'high_price', 'low_price', 'close_price']] = 100.
    raw[['volume_quote', 'trade_count']] = 0
    sets, _, _ = feature_sets(raw)
    for features in sets.values():
        assert np.isfinite(features.to_numpy()).all()
    assert sets['expanded'].rsi_fraction_14.eq(.5).all()


def test_tuning_plan_is_bounded_and_pruning_is_matched():
    from pipeline.decision.hourly_tuning import experiment_recipes
    from pipeline.settings import SETTINGS
    recipes = experiment_recipes(SETTINGS['hourly_forecast']['model'])
    assert len(recipes) == len({recipe['name'] for recipe in recipes}) == 28
    pruning = [recipe for recipe in recipes if recipe['name'].startswith('prune_')]
    assert [recipe['params']['gamma'] for recipe in pruning] == [0, 1000, 10000]
    assert len({tuple(sorted((k, v) for k, v in recipe['params'].items() if k != 'gamma')) for recipe in pruning}) == 1


def test_tuning_never_admits_test_targets():
    from pipeline.decision.hourly_tuning import development_splits
    target = pd.DatetimeIndex(np.concatenate([
        pd.date_range('2024-12-01', periods=600, freq='h', tz='UTC').to_numpy(),
        pd.date_range('2025-01-01', periods=600, freq='h', tz='UTC').to_numpy(),
        pd.date_range('2025-07-01', periods=600, freq='h', tz='UTC').to_numpy(),
    ]))
    meta = pd.DataFrame({'target_open_time':target, 'cutoff_time':target,
                         'target_close_time':target + pd.Timedelta(hours=1)})
    masks = development_splits(meta)
    assert all(mask.sum() == 600 for mask in masks.values())
    meta.loc[0, 'target_open_time'] = pd.Timestamp('2026-01-01', tz='UTC')
    with pytest.raises(ValueError, match='Test rows'):
        development_splits(meta)


def test_snapshot_filter_excludes_2026_before_building_features(tmp_path):
    from pipeline.decision.hourly_tuning import load_development_snapshot
    path = tmp_path / 'raw.csv'
    pd.DataFrame({'open_time':['2025-12-31T23:00:00Z','2026-01-01T00:00:00Z'],
                  'close_price':['100','DO_NOT_USE_TEST_PRICE']}).to_csv(path,index=False)
    frame = load_development_snapshot(path)
    assert len(frame) == 1
    assert frame.open_time.max() < pd.Timestamp('2026-01-01',tz='UTC')
    assert 'DO_NOT_USE_TEST_PRICE' not in frame.close_price.values


def test_target_transform_inverts_and_preserves_raw_mae_weighting():
    from pipeline.decision.hourly_tuning import inverse_target_scale
    features = pd.DataFrame({'return_std_24':[.001,.01,0.]})
    y = pd.Series([.01,-.02,.001])
    for transform in ['raw','bps','vol24']:
        scale = inverse_target_scale(transform,features)
        np.testing.assert_allclose((y/scale)*scale,y)
        errors = np.abs((y - .0001) / scale - y / scale)
        assert np.average(errors,weights=scale) * scale.mean() == pytest.approx(.0001)


def test_experimental_inference_needs_169_candles_but_no_future_label():
    from pipeline.decision.hourly_engineering import build_experimental_inputs, feature_sets
    raw=candles(169)
    sets=build_experimental_inputs(raw)
    for features in sets.values():
        assert features.notna().all(axis=1).sum()==1
        assert np.isfinite(features.iloc[-1]).all()
    assert feature_sets(raw)[0]['compact'].empty  # Train needs the additional label.


def test_optuna_search_recipe_has_valid_conditional_gamma_and_fixed_target():
    from pipeline.decision.hourly_optuna import search_recipe
    from pipeline.settings import SETTINGS
    class Trial:
        number=0
        def __init__(self,objective):
            self.objective=objective
        def suggest_categorical(self,name,choices):
            return self.objective if name=='objective' else choices[0]
        def suggest_int(self,name,low,high,**kwargs):
            return low
        def suggest_float(self,name,low,high,**kwargs):
            return low
    for objective in ['reg:squarederror','reg:absoluteerror']:
        recipe=search_recipe(Trial(objective),SETTINGS['hourly_forecast']['model'])
        assert recipe['target_transform']=='bps'
        assert recipe['params']['objective']==objective
        assert recipe['params']['gamma']==0
        assert recipe['params']['n_jobs']==2
        assert recipe['params']['n_estimators']==1200
        assert recipe['params']['early_stopping_rounds']==50


def test_optuna_budget_is_bounded_before_reading_data():
    from pipeline.decision.hourly_optuna import run_optuna
    for count in [0,201]:
        with pytest.raises(ValueError,match='Bounded trial count'):
            run_optuna(None,trials=count)


def test_negative_control_shuffles_training_label_blocks_not_values():
    from pipeline.decision.hourly_optuna import block_shuffle
    original=np.arange(72)
    shuffled=block_shuffle(original,42)
    assert not np.array_equal(shuffled,original)
    np.testing.assert_array_equal(np.sort(shuffled),original)
    np.testing.assert_array_equal(shuffled,block_shuffle(original,42))
    assert np.diff(shuffled.reshape(3,24),axis=1).min()==1
