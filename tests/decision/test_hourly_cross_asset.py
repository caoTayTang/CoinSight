"""Temporal invariance, paired missingness, and the prospective-completion gate."""
import numpy as np
import pandas as pd
import pytest

from pipeline.decision import hourly_cross_asset as c
from pipeline.decision.hourly_future import digest, seal
from pipeline.decision.hourly_engineering import build_experimental_inputs


def candles(n=400):
    clock = pd.date_range('2024-01-01', periods=n, freq='h', tz='UTC')
    close = 100*np.exp(np.sin(np.arange(n)/11)*.01+np.arange(n)*.0001)
    return pd.DataFrame(dict(open_time=clock, open_price=close, high_price=close*1.001,
        low_price=close*.999, close_price=close, volume_quote=np.full(n, 1000.), trade_count=np.full(n, 100)))


def test_cross_features_causal_and_169_context():
    btc, eth = candles(), candles()
    eth['close_price'] *= 1.1
    eth['open_price'] *= 1.1
    eth['high_price'] *= 1.1
    eth['low_price'] *= 1.1
    full = c.build_cross_inputs(btc, eth)
    assert list(full.columns) == c.EXTRA_COLUMNS
    assert full.iloc[168:].notna().all().all()
    pd.testing.assert_frame_equal(full.iloc[:250], c.build_cross_inputs(btc.iloc[:250], eth.iloc[:250]))
    pd.testing.assert_series_equal(full.iloc[249], c.build_cross_inputs(btc.iloc[81:250], eth.iloc[81:250]).iloc[-1])
    changed = eth.copy()
    changed.loc[250:, ['open_price', 'high_price', 'low_price', 'close_price']] *= 3
    pd.testing.assert_frame_equal(full.iloc[:250], c.build_cross_inputs(btc, changed).iloc[:250])


def test_missing_eth_hour_cannot_be_filled_or_used():
    btc, eth = candles(), candles()
    features = c.build_cross_inputs(btc, eth.drop(index=200))
    assert features.iloc[200:369].isna().all().all()
    assert features.iloc[369:].notna().all().all()


def test_gate_waits_for_actual_final_score(tmp_path):
    seal(tmp_path/'plan.json', dict(end_ms=1000))
    plan = dict(future_study=str(tmp_path), future_plan_sha256=digest((tmp_path/'plan.json').read_bytes()))
    assert c.gate_open(plan) is False
    seal(tmp_path/'final_score.json', dict(scored_server_ms=61000))
    assert c.gate_open(plan) is True


def test_explicit_offline_mode_needs_no_future_study():
    assert c.gate_open({'execution_mode': 'offline_retrospective'}) is True


def test_gate_rejects_premature_result(tmp_path):
    seal(tmp_path/'plan.json', dict(end_ms=1000))
    plan = dict(future_study=str(tmp_path), future_plan_sha256=digest((tmp_path/'plan.json').read_bytes()))
    seal(tmp_path/'final_score.json', dict(scored_server_ms=1001))
    with pytest.raises(ValueError, match='Premature'):
        c.gate_open(plan)


def test_waiting_never_downloads_or_trains(tmp_path, monkeypatch):
    monkeypatch.setattr(c, 'verify', lambda *a: {'future_study': 'pending'})
    monkeypatch.setattr(c, 'gate_open', lambda *a: False)
    monkeypatch.setattr(c, 'read_eth', lambda *a: pytest.fail('downloaded before gate'))
    assert c.execute(tmp_path)['status'] == 'waiting_for_prospective_completion'


def test_four_fold_runner_on_synthetic_data_only(tmp_path, monkeypatch):
    # Exercises eight real fits/reloads without consuming BTC/ETH validation results.
    btc = candles(17544)
    btc.to_csv(tmp_path/'btc_development_snapshot.csv', index=False)
    folds = []
    for quarter in range(4):
        start = pd.Timestamp(year=2025, month=quarter*3+1, day=1, tz='UTC')
        folds.append(dict(name=f'Q{quarter+1}', validation_start=start.isoformat(),
            validation_end=(start+pd.DateOffset(months=3)).isoformat(),
            train_start=(start-pd.DateOffset(years=1)).isoformat()))
    plan = dict(folds=folds, base_feature_names=list(build_experimental_inputs(candles(200))['compact'].columns),
        minimum_paired_coverage_per_quarter=.99, minimum_train_rows=1000, limitation='synthetic test',
        params=dict(n_estimators=2, max_depth=1, n_jobs=2, random_state=42, objective='reg:squarederror'))
    monkeypatch.setattr(c, 'verify', lambda *a: plan)
    monkeypatch.setattr(c, 'gate_open', lambda *a: True)
    monkeypatch.setattr(c, 'read_eth', lambda *a: btc.copy())
    result = c.execute(tmp_path)
    assert result['status'] == 'completed'
    assert len(result['folds']) == 8
    assert result['pooled']['btc_only']['n'] == result['pooled']['btc_eth']['n'] == 8760
    for quarter in range(4):
        left, right = result['folds'][quarter*2:quarter*2+2]
        assert left['train_n'] == right['train_n']
        assert left['n'] == right['n']
        assert left['paired_coverage'] == right['paired_coverage'] == 1
    assert c.execute(tmp_path) == result
