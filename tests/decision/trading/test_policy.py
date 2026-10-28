from datetime import UTC, datetime, timedelta

import pytest

from pipeline.decision.trading.contracts import PortfolioState
from pipeline.decision.trading.policy import DailyQuantilePolicy
from pipeline.decision.trading.policy_store import PolicyStore


NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)


def portfolio(*, quantity=0.0, fraction=0.0, drawdown=-0.02):
    return PortfolioState(
        portfolio_id="00000000-0000-0000-0000-000000000001",
        user_key="local",
        initial_cash_usdt=100_000.0,
        cash_usdt=100_000.0 if quantity == 0 else 70_000.0,
        equity_usdt=100_000.0,
        realized_pnl_usdt=0.0,
        maximum_drawdown=drawdown,
        symbol="BTC",
        position_quantity=quantity,
        average_entry_price_usdt=60_000.0 if quantity else None,
        current_price_usdt=70_000.0,
        position_value_usdt=fraction * 100_000.0,
        position_fraction=fraction,
        price_observed_at=NOW - timedelta(seconds=30),
    )


def support(q10=0.005, q50=0.02, q90=0.04, accuracy=0.58):
    return {
        "status": "ready",
        "data_readiness": {"is_complete": True},
        "forecast": {
            "return_q10": q10,
            "return_q50": q50,
            "return_q90": q90,
            "target_close": (NOW + timedelta(hours=12)).isoformat(),
        },
        "recent_performance": {
            "sample_count": 30,
            "directional_accuracy": accuracy,
            "relative_mae": 0.98,
        },
        "market_statistics": {
            "sample_count": 30,
            "realized_volatility": 0.025,
            "annualized_volatility": 0.48,
            "maximum_drawdown": -0.12,
            "cumulative_return": 0.08,
            "up_day_ratio": 0.57,
        },
        "hourly_trend": {"direction": "up", "regression_r_squared": 0.55},
    }


@pytest.fixture
def policy():
    return DailyQuantilePolicy(PolicyStore().load())


def test_bullish_evidence_creates_bounded_buy(policy):
    result = policy.evaluate(support(), portfolio(), now=NOW)
    config = PolicyStore().load()
    assert result.action == "BUY"
    assert result.executable is True
    assert 0 < result.order_notional_usdt <= (
        float(config["max_order_fraction"]) * 100_000
    )
    assert result.target_position_fraction <= float(config["max_asset_fraction"])
    assert "forecast_interval_above_zero" in result.reasons


def test_bearish_evidence_reduces_existing_position(policy):
    evidence = support(-0.05, -0.025, -0.004, accuracy=0.57)
    evidence["hourly_trend"] = {"direction": "down", "regression_r_squared": 0.6}
    evidence["market_statistics"]["cumulative_return"] = -0.1
    evidence["market_statistics"]["up_day_ratio"] = 0.4
    result = policy.evaluate(evidence, portfolio(quantity=0.5, fraction=0.35), now=NOW)
    assert result.action == "SELL"
    assert result.executable is True
    assert result.target_position_fraction == 0.0
    assert result.order_notional_usdt <= (
        float(PolicyStore().load()["max_order_fraction"]) * 100_000
    )


def test_missing_grid_and_stale_price_block_trading(policy):
    evidence = support()
    evidence["data_readiness"]["is_complete"] = False
    assert policy.evaluate(evidence, portfolio(), now=NOW).action == "NO_TRADE"
    stale = portfolio()
    stale = PortfolioState(**{**stale.__dict__, "price_observed_at": NOW - timedelta(minutes=10)})
    assert policy.evaluate(support(), stale, now=NOW).reasons == ("execution_price_stale",)


def test_mae_is_a_penalty_not_a_direction_override(policy):
    evidence = support()
    evidence["recent_performance"]["relative_mae"] = 1.04
    result = policy.evaluate(evidence, portfolio(), now=NOW)
    assert result.signed_score > 0
    assert "mae_does_not_beat_zero_return" in result.risk_flags


def test_policy_has_slippage_but_no_fee_configuration():
    config = PolicyStore().load()
    assert config["slippage_bps"] == 5.0
    assert not any("fee" in key.lower() for key in config)
