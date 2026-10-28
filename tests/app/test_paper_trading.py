from types import SimpleNamespace
from datetime import UTC, datetime
from uuid import UUID

from app import paper_trading


PORTFOLIO = UUID("00000000-0000-0000-0000-000000000001")


def test_create_decision_uses_raw_forecast_evidence(monkeypatch):
    captured = {}
    user = SimpleNamespace(key="u_0123456789abcdef")

    def command(request, user_key):
        assert request.command == "predict"
        assert request.symbol == "ETH"
        assert user_key == user.key
        return {"evidence": {"status": "ready", "symbol": "ETH"}}

    class Service:
        def create(self, user_key, portfolio_id, support):
            captured.update(user_key=user_key, portfolio_id=portfolio_id, support=support)
            return {"decision_id": "decision", "action": "HOLD"}

    monkeypatch.setattr(paper_trading, "command", command)
    monkeypatch.setattr(paper_trading, "service", lambda: Service())
    result = paper_trading.create_decision(
        PORTFOLIO, paper_trading.DecisionCreate(symbol="ETH"), user
    )
    assert result["action"] == "HOLD"
    assert captured["portfolio_id"] == str(PORTFOLIO)
    assert captured["support"]["symbol"] == "ETH"


def test_execute_requires_server_owned_portfolio_and_idempotency(monkeypatch):
    captured = {}
    user = SimpleNamespace(key="u_0123456789abcdef")

    class Service:
        def execute(self, *args):
            captured["args"] = args
            return {"status": "FILLED"}

    monkeypatch.setattr(paper_trading, "service", lambda: Service())
    decision = UUID("00000000-0000-0000-0000-000000000002")
    candle_time = datetime(2026, 10, 27, 12, tzinfo=UTC)
    payload = paper_trading.OrderRequest(
        decision_id=decision, idempotency_key="retry-key-123",
        expected_source_candle_time=candle_time,
    )
    result = paper_trading.execute_order(PORTFOLIO, payload, user)
    assert result["status"] == "FILLED"
    assert captured["args"] == (
        user.key, str(PORTFOLIO), str(decision), "retry-key-123", candle_time,
    )
