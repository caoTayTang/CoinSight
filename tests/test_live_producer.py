from io import BytesIO
import json

import pytest

from pipeline.live_producer import fetch_closed_candle, normalize_kline


def test_normalize_kline_matches_stream_contract():
    event = normalize_kline(
        "btc",
        [
            1704067200000,
            "42000.00",
            "42500.00",
            "41800.00",
            "42300.00",
            "12.5",
            1704067259999,
            "528750.00",
        ],
    )

    assert event == {
        "event_id": "BTC:2024-01-01T00:00:00+00:00",
        "symbol": "BTC",
        "name": "Bitcoin",
        "event_time": "2024-01-01T00:00:00+00:00",
        "open_price": 42000.0,
        "high_price": 42500.0,
        "low_price": 41800.0,
        "close_price": 42300.0,
        "volume": 528750.0,
        "source": "binance-rest",
    }


def test_normalize_kline_rejects_invalid_range():
    with pytest.raises(ValueError, match="high price"):
        normalize_kline(
            "BTC",
            [1704067200000, "10", "8", "9", "9.5", "1", 1704067259999, "10"],
        )


def test_fetch_closed_candle_skips_current_candle(monkeypatch):
    closed = [1704067200000, "10", "12", "9", "11", "1", 1704067259999, "100"]
    current = [1704067260000, "11", "13", "10", "12", "1", 1704067319999, "120"]

    def fake_urlopen(request, timeout):
        return BytesIO(json.dumps([closed, current]).encode("utf-8"))

    monkeypatch.setattr("pipeline.live_producer.urlopen", fake_urlopen)

    event = fetch_closed_candle("BTC", "https://example.test", 1)

    assert event["event_time"] == "2024-01-01T00:00:00+00:00"
    assert event["close_price"] == 11.0
