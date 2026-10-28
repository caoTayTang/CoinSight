from datetime import UTC, datetime, timedelta

import pytest

from pipeline.decision.trading.backtest import BacktestObservation, PolicyBacktester
from pipeline.decision.trading.policy_store import PolicyStore


def evidence(now, direction=1):
    return {
        "status": "ready", "data_readiness": {"is_complete": True},
        "forecast": {
            "return_q10": 0.004 * direction, "return_q50": 0.02 * direction,
            "return_q90": 0.04 * direction,
            "target_close": (now + timedelta(days=1)).isoformat(),
        } if direction > 0 else {
            "return_q10": -0.04, "return_q50": -0.02, "return_q90": -0.004,
            "target_close": (now + timedelta(days=1)).isoformat(),
        },
        "recent_performance": {"sample_count": 30, "directional_accuracy": 0.58, "relative_mae": 0.98},
        "market_statistics": {
            "sample_count": 30, "realized_volatility": 0.02, "annualized_volatility": 0.4,
            "maximum_drawdown": -0.1, "cumulative_return": 0.08 * direction,
            "up_day_ratio": 0.6 if direction > 0 else 0.4,
        },
        "hourly_trend": {"direction": "up" if direction > 0 else "down", "regression_r_squared": 0.7},
    }


def test_backtest_buys_then_exits_without_fee():
    start = datetime(2026, 1, 1, 12, tzinfo=UTC)
    rows = [
        BacktestObservation(start, "BTC", 100.0, evidence(start, 1), 110.0),
        BacktestObservation(
            start + timedelta(days=1), "BTC", 110.0,
            evidence(start + timedelta(days=1), -1), 105.0,
        ),
    ]
    result = PolicyBacktester(PolicyStore().load()).run(rows, initial_cash_usdt=10_000)
    assert [trade["side"] for trade in result["trades"]] == ["BUY", "SELL"]
    assert result["fee_simulation"] is False
    assert result["trade_count"] == 2
    assert result["turnover_usdt"] > 0
    assert result["profit_loss_usdt"] == result["final_equity_usdt"] - 10_000
    assert result["total_return_percent"] == result["total_return"] * 100
    assert result["action_counts"] == {
        "BUY": 1, "SELL": 1, "HOLD": 0, "NO_TRADE": 0,
    }
    assert all("buy_hold_equity_usdt" in row for row in result["equity_curve"])
    assert result["equity_curve"][0]["forecast_return_q50"] == 0.02
    assert result["equity_curve"][0]["actual_target_return"] == pytest.approx(0.1)
    assert result["forecast_direction_diagnostics"]["counts"] == {
        "predicted_up_actual_up": 1,
        "predicted_down_actual_up": 0,
        "predicted_up_actual_down_or_flat": 0,
        "predicted_down_actual_down_or_flat": 1,
    }
    assert result["forecast_direction_diagnostics"]["directional_accuracy"] == 1.0
    assert result["policy_action_utility"]["BUY"]["directionally_useful_rate"] == 1.0
    assert result["policy_action_utility"]["SELL"]["directionally_useful_rate"] == 1.0
    assert result["policy_action_utility"]["BUY"]["profitable_after_slippage_rate"] == 1.0
    assert result["policy_action_utility"]["SELL"]["profitable_after_slippage_rate"] == 1.0


def test_backtest_counts_and_logs_hold_reasons():
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    weak = evidence(now, 1)
    weak["forecast"] = {
        "return_q10": -0.02,
        "return_q50": 0.0,
        "return_q90": 0.02,
        "target_close": (now + timedelta(days=1)).isoformat(),
    }
    weak["recent_performance"]["directional_accuracy"] = 0.5
    weak["market_statistics"]["cumulative_return"] = 0.0
    weak["market_statistics"]["up_day_ratio"] = 0.5
    weak["hourly_trend"] = {"direction": "flat", "regression_r_squared": 0.0}
    result = PolicyBacktester(PolicyStore().load()).run([
        BacktestObservation(now, "BTC", 100.0, weak, 99.0)
    ], initial_cash_usdt=10_000)
    assert result["action_counts"]["HOLD"] == 1
    assert result["hold_reason_counts"]["support_below_trade_threshold"] == 1
    assert "support_below_trade_threshold" in result["equity_curve"][0]["decision_reasons"]
    hold = result["policy_action_utility"]["HOLD"]
    assert hold["cash_context_count"] == 1
    assert hold["directionally_useful_rate"] == 1.0
    assert hold["profitable_after_slippage_rate"] is None
