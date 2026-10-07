from io import BytesIO
import json
from argparse import Namespace
from urllib.error import HTTPError

import pytest

from pipeline.stream.binance_live_client import (
    BinanceBackoffError, backfill_candles, fetch_closed_candle, live_event,
    load_state, normalize_kline, normalize_websocket_message, save_state, stream_url,
)


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

    monkeypatch.setattr("pipeline.stream.binance_live_client.urlopen", fake_urlopen)

    event = fetch_closed_candle("BTC", "https://example.test", 1)

    assert event["event_time"] == "2024-01-01T00:00:00+00:00"
    assert event["close_price"] == 11.0


def test_fetch_closed_candle_honors_retry_after(monkeypatch):
    def rate_limited(request, timeout):
        raise HTTPError(request.full_url, 429, "Too Many Requests", {"Retry-After": "45"}, None)

    monkeypatch.setattr("pipeline.stream.binance_live_client.urlopen", rate_limited)

    with pytest.raises(BinanceBackoffError) as error:
        fetch_closed_candle("BTC", "https://example.test", 1)

    assert error.value.retry_after == 45


def test_websocket_uses_only_closed_minute_candles():
    candle = {
        "t": 1704067200000, "T": 1704067259999, "s": "BTCUSDT", "i": "1m",
        "o": "42000", "h": "42500", "l": "41800", "c": "42300",
        "v": "12.5", "q": "528750", "n": 42, "x": False,
    }
    message = {"stream": "btcusdt@kline_1m", "data": {"e": "kline", "s": "BTCUSDT", "k": candle}}
    assert normalize_websocket_message(message) is None
    candle["x"] = True
    event = normalize_websocket_message(message)
    assert event["pair"] == "BTCUSDT"
    assert event["mode"] == "live"
    assert event["source"] == "binance-ws"
    assert event["volume"] == 528750.0
    assert event["event_id"] == "binance:spot:BTCUSDT:1m:2024-01-01T00:00:00+00:00"
    assert stream_url(["BTC", "ETH"], "wss://stream.binance.com:9443") == (
        "wss://stream.binance.com:9443/stream?streams=btcusdt@kline_1m/ethusdt@kline_1m"
    )


def test_rest_backfill_uses_same_id_and_state_survives_restart(tmp_path, monkeypatch):
    row = [1704067200000, "42000", "42500", "41800", "42300", "12.5", 1704067259999, "528750"]
    monkeypatch.setattr("pipeline.stream.binance_live_client.urlopen", lambda *_args, **_kwargs: BytesIO(json.dumps([row]).encode()))
    monkeypatch.setattr("pipeline.stream.binance_live_client.time.time", lambda: 1704067320)
    [event] = list(backfill_candles("BTC", 1704067140000, "https://example.test", 1))
    assert event["event_id"] == live_event("BTC", row, "binance-ws")["event_id"]
    state_path = tmp_path / "state.json"
    save_state(state_path, {"BTC": 1704067200000})
    assert load_state(state_path)["BTC"] == 1704067200000


def test_websocket_disconnect_reconnects_instead_of_exiting(tmp_path, monkeypatch):
    from websocket import WebSocketConnectionClosedException
    from pipeline.stream import binance_live_client as live_producer

    attempts = []
    delays = []

    class FakeProducer:
        def __init__(self, **_kwargs):
            pass

        def flush(self):
            pass

        def close(self):
            pass

    def connect(*_args, **_kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise WebSocketConnectionClosedException("connection lost")
        raise KeyboardInterrupt

    monkeypatch.setattr("kafka.KafkaProducer", FakeProducer)
    monkeypatch.setattr("websocket.create_connection", connect)
    monkeypatch.setattr(live_producer.time, "sleep", delays.append)
    monkeypatch.setattr(live_producer, "parse_args", lambda: Namespace(
        bootstrap_servers="unused", topic="unused", symbols="BTC",
        api_url="unused", ws_url="unused", poll_seconds=2,
        request_timeout=1, state_file=str(tmp_path / "state.json"),
    ))

    live_producer.main()

    assert len(attempts) == 2
    assert delays == [2]
