"""Prospective safeguards must reject hindsight, overwrite and changed artifacts."""
import json
import math
from pathlib import Path

import pandas as pd
import pytest

from pipeline.decision import hourly_future as f


def test_seal_is_exclusive_and_detects_tampering(tmp_path):
    path = tmp_path/'record.json'
    f.seal(path, {'prediction': .001})
    with pytest.raises(FileExistsError):
        f.seal(path, {'prediction': .002})
    assert f.unseal(path) == {'prediction': .001}
    path.chmod(0o644)
    path.write_text(json.dumps({'payload': {'prediction': .002}, 'sha256': 'wrong'}))
    with pytest.raises(ValueError, match='digest'):
        f.unseal(path)


def test_late_forecast_does_not_fetch_or_backfill(tmp_path, monkeypatch):
    target = 500*f.HOUR
    plan = dict(start_ms=target-f.HOUR, end_ms=target+f.HOUR, prediction_delay_limit_seconds=120)
    monkeypatch.setattr(f, 'klines', lambda *a: pytest.fail('late forecast fetched candles'))
    assert f.record_forecast(tmp_path, plan, target+120001) == 'deadline_missed'
    assert not (tmp_path/'forecasts').exists()
    assert f.record_forecast(tmp_path, plan, target+f.HOUR) == 'outside_window'


def test_forecast_only_requests_previous_context_and_is_idempotent(tmp_path, monkeypatch):
    target = 500*f.HOUR
    plan = dict(start_ms=target, end_ms=target+f.HOUR, prediction_delay_limit_seconds=120,
                api='fake', model_sha256='model')
    (tmp_path/'plan.json').write_text('locked')
    calls = []
    def candles(base, start, count):
        calls.append((start, count))
        return [['closed']], pd.DataFrame({'close_price': [100.]})
    monkeypatch.setattr(f, 'klines', candles)
    monkeypatch.setattr(f, 'predict_candidate', lambda *a: .001)
    monkeypatch.setattr(f, 'clock', lambda *a: target+61000)
    monkeypatch.setattr(f.time, 'time', lambda: (target+61000)/1000)
    assert f.record_forecast(tmp_path, plan, target+60000) == 'recorded'
    assert calls == [(target-169*f.HOUR, 169)]
    record = f.unseal(tmp_path/'forecasts'/f'{target}.json')
    assert record['issued_server_ms'] < record['target_close_ms']
    assert f.record_forecast(tmp_path, plan, target+62000) == 'already_recorded'
    assert len(calls) == 1


def test_forecast_finishing_late_is_rejected(tmp_path, monkeypatch):
    target = 500*f.HOUR
    plan = dict(start_ms=target, end_ms=target+f.HOUR, prediction_delay_limit_seconds=120, api='fake')
    monkeypatch.setattr(f, 'klines', lambda *a: ([], pd.DataFrame({'close_price': [100.]})))
    monkeypatch.setattr(f, 'predict_candidate', lambda *a: .001)
    monkeypatch.setattr(f, 'clock', lambda *a: target+120001)
    with pytest.raises(ValueError, match='deadline'):
        f.record_forecast(tmp_path, plan, target+60000)


def test_labels_cannot_be_fetched_before_close(tmp_path, monkeypatch):
    (tmp_path/'forecasts').mkdir()
    f.seal(tmp_path/'forecasts/0.json', dict(target_open_ms=0, target_close_ms=f.HOUR))
    monkeypatch.setattr(f, 'klines', lambda *a: pytest.fail('label fetched too early'))
    assert f.collect_labels(tmp_path, {}, f.HOUR+59999) == 0


def test_changed_frozen_asset_fails(tmp_path, monkeypatch):
    (tmp_path/'model').write_bytes(b'original')
    f.seal(tmp_path/'plan.json', dict(assets={'model': f.digest(b'original')}))
    (tmp_path/'model').write_bytes(b'changed')
    with pytest.raises(ValueError, match='asset changed'):
        f.verify(tmp_path)


def test_scoring_is_blocked_until_end(tmp_path, monkeypatch):
    monkeypatch.setattr(f, 'verify', lambda *a: dict(api='fake', end_ms=10*f.HOUR))
    monkeypatch.setattr(f, 'clock', lambda *a: 9*f.HOUR)
    with pytest.raises(ValueError, match='No interim scoring'):
        f.score(tmp_path)


def test_low_coverage_cannot_pass(tmp_path, monkeypatch):
    (tmp_path/'forecasts').mkdir()
    plan = dict(api='fake', start_ms=0, end_ms=2*f.HOUR, expected_hours=2,
                minimum_coverage=.95, target_threshold_relative_mae=.95)
    monkeypatch.setattr(f, 'verify', lambda *a: plan)
    monkeypatch.setattr(f, 'clock', lambda *a: 3*f.HOUR)
    monkeypatch.setattr(f, 'collect_labels', lambda *a: 0)
    result = f.score(tmp_path)
    assert result['decision'] == 'inconclusive_coverage'
    assert result['coverage'] == 0
    assert result['missing_forecasts'] == [0, f.HOUR]


def test_final_score_uses_paired_pooled_errors_and_frozen_reference(tmp_path, monkeypatch):
    plan = dict(api='fake', start_ms=0, end_ms=2*f.HOUR, expected_hours=2,
                minimum_coverage=.95, target_threshold_relative_mae=.95, model_sha256='model')
    f.seal(tmp_path/'plan.json', plan)
    plan_hash = f.digest((tmp_path/'plan.json').read_bytes())
    for i, (actual, predicted) in enumerate([(.01, .005), (-.02, -.015)]):
        target = i*f.HOUR
        path = tmp_path/'forecasts'/f'{target}.json'
        f.seal(path, dict(target_open_ms=target, issued_server_ms=target+60000,
            input_last_close_ms=target-1, model_sha256='model', input_klines=[],
            input_sha256=f.digest(f.canonical([])), plan_sha256=plan_hash,
            predicted_log_return=predicted, reference_close=100.))
        f.seal(tmp_path/'labels'/path.name, dict(target_open_ms=target,
            observed_server_ms=target+f.HOUR+60000, close=100*math.exp(actual),
            forecast_sha256=f.digest(path.read_bytes())))
    monkeypatch.setattr(f, 'verify', lambda *a: plan)
    monkeypatch.setattr(f, 'clock', lambda *a: 3*f.HOUR)
    monkeypatch.setattr(f, 'collect_labels', lambda *a: 0)
    result = f.score(tmp_path)
    assert result['relative_mae'] == pytest.approx(1/3)
    assert result['mae'] == pytest.approx(.005)
    assert result['zero_mae'] == pytest.approx(.015)
    assert result['decision'] == 'target_met'
    assert f.score(tmp_path) == result
