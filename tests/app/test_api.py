from pathlib import Path
from datetime import date, datetime, timedelta, timezone

from app import api
from app.api import dashboard, health
import pytest


def test_health():
    assert health() == {"status": "ok"}


def test_dashboard_file_exists():
    response = dashboard()
    assert Path(response.path).is_file()


def test_snapshot_includes_batch_and_market_time(monkeypatch):
    observed = datetime.now(timezone.utc).date() - timedelta(days=1)
    monkeypatch.setattr(api, "fetch_all", lambda *_args: [{
        "symbol": "BTC", "as_of_date": observed, "close_price": 70000,
        "volume_quote": 1000000, "source_code": "binance", "batch_id": 42,
        "loaded_at": datetime.now(timezone.utc),
    }])
    response = api.asset_snapshot("btc")
    assert response.status == "ready"
    assert response.provenance.batch_id == 42
    assert response.data.as_of_date == observed
    assert response.data.close_price_usdt == 70000


def test_snapshot_absence_is_explicit(monkeypatch):
    monkeypatch.setattr(api, "fetch_all", lambda *_args: [])
    response = api.asset_snapshot("btc")
    assert response.status == "unavailable"
    assert response.data is None


def test_live_metric_uses_market_event_time_for_freshness(monkeypatch):
    old_event = datetime.now(timezone.utc) - timedelta(minutes=10)
    monkeypatch.setattr(api, "fetch_all", lambda *_args: [{
        "symbol": "BTC", "source": "binance-ws",
        "window_start": old_event - timedelta(days=7),
        "window_end": old_event + timedelta(days=1),
        "last_event_time": old_event,
        "avg_price_usd": 70000, "price_volatility": 50,
        "total_volume": 1000, "event_count": 10,
        "updated_at": datetime.now(timezone.utc),
    }])
    response = api.live_metric_v1("BTC")
    assert response.status == "stale"
    assert response.provenance.observed_at == old_event


def test_empty_successful_batch_is_insufficient_data(monkeypatch):
    monkeypatch.setattr(api, "fetch_all", lambda *_args: [{
        "batch_id": 4, "status": "success", "finished_at": datetime.now(timezone.utc),
        "rows_extracted": 0, "rows_rejected": 0,
    }] if "from meta.etl_batch" in _args[0] else [])
    response = api.data_status()
    assert response.status == "insufficient_data"
    assert response.data.latest_batch_id == 4


def test_live_summary_exposes_coverage_and_staleness(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(api, 'fetch_all', lambda *_: [{
        'window_start': now - timedelta(minutes=8),
        'window_end': now - timedelta(minutes=1),
        'last_candle_at': now - timedelta(minutes=2),
        'first_open': 100, 'last_close': 101,
        'volume_quote': 1000, 'observed_minutes': 7,
    }])
    result = api.live_summary('btc')
    assert result.data.observed_minutes == 7
    assert result.data.change_pct == pytest.approx(1)
    assert result.quality.warnings
