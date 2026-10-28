import pytest

from warehouse_agents import tools
from warehouse_agents.run_context import CURRENT_USER


@pytest.mark.asyncio
async def test_trade_decision_is_advisory_and_uses_server_user(monkeypatch):
    calls = {}

    class Repository:
        def list_portfolios(self, user):
            calls["list_user"] = user
            return [{"portfolio_id": "00000000-0000-0000-0000-000000000001"}]

    class Service:
        def __init__(self, repository):
            self.repository = repository

        def evaluate(self, user, portfolio_id, support):
            calls.update(user=user, portfolio_id=portfolio_id, support=support)
            return {
                "status": "ready", "draft": object(),
                "decision": {"action": "BUY", "executable": True},
            }

    async def forecast_support(**kwargs):
        return {"status": "ready", "symbol": kwargs["symbol"]}

    monkeypatch.setattr(tools, "PaperTradingRepository", Repository)
    monkeypatch.setattr(tools, "TradeDecisionService", Service)
    monkeypatch.setattr(tools, "forecast_support", forecast_support)
    token = CURRENT_USER.set("u_0123456789abcdef")
    try:
        result = await tools.trade_decision(symbol="BTC")
    finally:
        CURRENT_USER.reset(token)

    assert calls["list_user"] == "u_0123456789abcdef"
    assert calls["user"] == "u_0123456789abcdef"
    assert result["decision"]["action"] == "BUY"
    assert result["decision"]["paper_order_eligible"] is True
    assert result["decision"]["executable"] is False
    assert result["executable"] is False
    assert result["execution_path"] == "confirm_in_paper_trading_dashboard"
    assert "draft" not in result


@pytest.mark.asyncio
async def test_trade_decision_requires_authenticated_context():
    token = CURRENT_USER.set(None)
    try:
        result = await tools.trade_decision(symbol="BTC")
    finally:
        CURRENT_USER.reset(token)
    assert result["status"] == "unavailable"
    assert result["reason"] == "authenticated_user_context_required"
