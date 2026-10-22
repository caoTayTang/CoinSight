import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from warehouse_agents import tools


def candles(hours=336, drift=0.0, seed=1):
    rng = np.random.default_rng(seed)
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.004, hours)))
    open_ = np.concatenate([[100], close[:-1]])
    return pd.DataFrame(
        {
            'open_time': [start + timedelta(hours=i) for i in range(hours)],
            'open_price': open_,
            'high_price': np.maximum(open_, close) * 1.002,
            'low_price': np.minimum(open_, close) * 0.998,
            'close_price': close,
            'volume_quote': rng.uniform(1e6, 2e6, hours),
            'trade_count': rng.integers(1000, 2000, hours),
        }
    )


def test_psi_flags_a_shifted_feature_only():
    reference = {'x': {'inner_edges': [-1.0, 0.0, 1.0], 'bin_fractions': [0.25, 0.25, 0.25, 0.25]}}
    same = pd.DataFrame({'x': np.random.default_rng(0).uniform(-2, 2, 400)})
    shifted = pd.DataFrame({'x': np.full(400, 5.0)})
    assert tools.psi_table(same, reference)[0]['heuristic_drift_flag'] is False
    assert tools.psi_table(shifted, reference)[0]['heuristic_drift_flag'] is True


def test_forecast_drift_uses_the_serving_features(tmp_path, monkeypatch):
    from pipeline.decision.hourly_engineering import build_experimental_inputs

    names = list(build_experimental_inputs(candles())['compact'].columns[:6])
    profile = {n: {'inner_edges': [0.0], 'bin_fractions': [0.5, 0.5]} for n in names}
    path = tmp_path / 'reference_profile.json'
    path.write_text(
        json.dumps(
            {
                'model_id': 'm',
                'feature_set': 'compact',
                'period': {},
                'rows': 1,
                'features': profile,
                'not_covered': ['eth_x'],
            }
        )
    )
    monkeypatch.setattr(tools, 'FORECAST_PROFILE', str(path))
    result = tools.forecast_drift(candles(1000))
    assert result['status'] == 'available' and result['features_checked'] == 6
    assert result['window_feature_rows'] == 720 and all('long_window' in v for v in result['top_features'])
    assert result['not_covered'] == ['eth_x']
    monkeypatch.setattr(tools, 'FORECAST_PROFILE', str(tmp_path / 'missing.json'))
    assert tools.forecast_drift(candles())['status'] == 'unavailable'


@pytest.mark.asyncio
async def test_live_performance_reports_reliability(monkeypatch):
    def query(sql, params=()):
        if 'model_performance' in sql:
            return [
                {
                    'model_id': 'm',
                    'model_version': 'v',
                    'symbol': 'BTC',
                    'window_label': '24h',
                    'n': 20,
                    'mae': Decimal('0.002'),
                    'baseline_mae': 0.0021,
                    'relative_mae': 0.95,
                    'directional_accuracy': 0.55,
                    'first_target': 'a',
                    'last_target': 'b',
                }
            ]
        return [{'recorded': 21, 'scored': 20, 'recording_since': '2026-10-21'}]

    monkeypatch.setattr(tools, 'query', query)
    result = await tools.live_performance()
    assert (
        result['status'] == 'available'
        and result['reliable'] is False
        and result['windows'][0]['mae'] == 0.002
    )
    monkeypatch.setattr(
        tools,
        'query',
        lambda sql, params=(): []
        if 'model_performance' in sql
        else [{'recorded': 1, 'scored': 0, 'recording_since': None}],
    )
    assert (await tools.live_performance())['status'] == 'insufficient_data'
