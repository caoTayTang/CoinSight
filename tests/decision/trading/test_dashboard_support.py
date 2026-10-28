from pipeline.decision.trading.policy_store import PolicyStore
from pipeline.decision.trading.repository import summarize_trade_outcomes


def test_user_policy_is_normalized_and_versioned_without_mutating_default():
    store = PolicyStore()
    default = store.load()
    custom = store.normalize_user_config({**default, "trade_threshold": 0.17})
    assert custom["trade_threshold"] == 0.17
    assert custom["version"].startswith("v1-user-")
    assert custom["deployment_tier"] == "paper-only"
    assert len(custom["sha256"]) == 64
    assert store.load()["trade_threshold"] == default["trade_threshold"]


def test_accepted_order_analytics_separates_buy_and_sell_utility():
    rows = [
        {
            "order_id": "buy", "side": "BUY", "symbol": "BTC",
            "quantity": 0.1, "fill_price_usdt": 100.0,
            "reference_close_usdt": 100.0, "actual_target_close_usdt": 110.0,
        },
        {
            "order_id": "sell", "side": "SELL", "symbol": "BTC",
            "quantity": 0.2, "fill_price_usdt": 100.0,
            "reference_close_usdt": 100.0, "actual_target_close_usdt": 90.0,
        },
    ]
    result = summarize_trade_outcomes(
        rows, {"initial_cash_usdt": 1_000.0, "equity_usdt": 1_025.0, "realized_pnl_usdt": 5.0}
    )
    assert result["useful_rate"] == 1.0
    assert result["gross_useful_effect_usdt"] == 3.0
    assert result["portfolio_profit_loss_usdt"] == 25.0
    assert result["by_side"]["BUY"]["useful_rate"] == 1.0
    assert result["by_side"]["SELL"]["useful_rate"] == 1.0
