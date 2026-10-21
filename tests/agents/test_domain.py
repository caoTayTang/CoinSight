from datetime import datetime, timedelta, timezone
import pytest
from pydantic import ValidationError
from agents.domain import Candle, CandleContext, detect_anomalies


def context():
    cutoff = datetime(2026, 1, 8, tzinfo=timezone.utc)
    return CandleContext(
        cutoff=cutoff,
        candles=[
            Candle(
                open_time=cutoff - timedelta(hours=169 - i),
                open_price=100,
                high_price=101,
                low_price=99,
                close_price=100,
                volume_quote=1000,
                trade_count=10,
            )
            for i in range(169)
        ],
    )


def test_causal_latest_bar_detector_and_excludes_latest_from_baseline():
    ctx = context()
    result = detect_anomalies(ctx)
    assert result['is_anomaly'] is False
    changed = ctx.model_dump()
    changed['candles'][-1].update(close_price=120, high_price=121, volume_quote=100000)
    shock = detect_anomalies(CandleContext.model_validate(changed))
    assert shock['is_anomaly']
    assert shock['checks'][0]['history_median'] == result['checks'][0]['history_median'] == 0
    assert shock['checks'][0]['history_n'] == 167
    assert shock['checks'][1]['history_n'] == 168


def test_context_rejects_gap_future_naive_and_invalid_ohlc():
    base = context().model_dump()
    for mutate in ('gap', 'future', 'naive', 'ohlc'):
        d = context().model_dump()
        if mutate == 'gap':
            d['candles'][30]['open_time'] += timedelta(hours=1)
        if mutate == 'future':
            d['candles'][-1]['open_time'] = d['cutoff']
        if mutate == 'naive':
            d['cutoff'] = d['cutoff'].replace(tzinfo=None)
        if mutate == 'ohlc':
            d['candles'][-1]['close_price'] = 110
        with pytest.raises(ValidationError):
            CandleContext.model_validate(d)
