import time

from fastapi.testclient import TestClient

from app import api, live_stream


def test_websocket_sends_snapshot_then_committed_change(monkeypatch):
    class Listener:
        def close(self):
            pass

    calls = 0

    def wait_for_change(_connection, _timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"BTC"}
        time.sleep(0.01)
        return set()

    monkeypatch.setattr(live_stream, "connect_listener", Listener)
    monkeypatch.setattr(live_stream, "wait_for_change", wait_for_change)
    monkeypatch.setattr(live_stream, "live_payload", lambda symbol: {
        "type": "live.snapshot", "symbol": symbol, "summary": {"status": "ready"},
        "metric": {"status": "ready"},
    })

    with TestClient(api.app) as client:
        with client.websocket_connect("/v1/assets/BTC/stream") as socket:
            assert socket.receive_json()["symbol"] == "BTC"
            assert socket.receive_json()["summary"]["status"] == "ready"


def test_live_payload_reuses_public_api_envelopes(monkeypatch):
    class Envelope:
        def __init__(self, kind):
            self.kind = kind

        def model_dump(self, mode):
            assert mode == "json"
            return {"kind": self.kind}

    monkeypatch.setattr(api, "live_summary", lambda symbol: Envelope(f"minute:{symbol}"))
    monkeypatch.setattr(api, "live_metric_v1", lambda symbol: Envelope(f"metric:{symbol}"))
    result = live_stream.live_payload("BTC")
    assert result["summary"] == {"kind": "minute:BTC"}
    assert result["metric"] == {"kind": "metric:BTC"}
