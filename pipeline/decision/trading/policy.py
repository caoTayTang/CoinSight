"""Pure deterministic decision policy; it performs no I/O and never places orders."""
from __future__ import annotations

from datetime import UTC, datetime
import math
from typing import Any

from .contracts import DecisionDraft, PortfolioState


def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _finite(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


class DailyQuantilePolicy:
    """Turn forecast evidence into a long-only target position.

    The score is a deterministic support score, not a calibrated probability.
    """

    def __init__(self, config: dict[str, Any]):
        self.config = dict(config)

    def evaluate(
        self,
        support: dict[str, Any],
        portfolio: PortfolioState,
        *,
        now: datetime | None = None,
    ) -> DecisionDraft:
        now = (now or datetime.now(UTC)).astimezone(UTC)
        risk_flags: list[str] = []
        reasons: list[str] = []
        if support.get("status") != "ready":
            return self._blocked("forecast_support_unavailable", current_fraction=portfolio.position_fraction)
        if not support.get("data_readiness", {}).get("is_complete", False):
            return self._blocked("forecast_input_grid_incomplete", current_fraction=portfolio.position_fraction)

        forecast = support["forecast"]
        performance = support["recent_performance"]
        market = support["market_statistics"]
        trend = support["hourly_trend"]
        q10 = _finite(forecast["return_q10"], "return_q10")
        q50 = _finite(forecast["return_q50"], "return_q50")
        q90 = _finite(forecast["return_q90"], "return_q90")
        if not q10 <= q50 <= q90:
            return self._blocked("invalid_quantile_order", current_fraction=portfolio.position_fraction)
        target_close = datetime.fromisoformat(str(forecast["target_close"]).replace("Z", "+00:00"))
        if target_close <= now:
            return self._blocked("forecast_target_already_closed", current_fraction=portfolio.position_fraction)
        age = (now - portfolio.price_observed_at.astimezone(UTC)).total_seconds()
        if age < -5 or age > int(self.config["max_price_age_seconds"]):
            return self._blocked("execution_price_stale", current_fraction=portfolio.position_fraction)
        samples = int(performance.get("sample_count", 0))
        if samples < int(self.config["min_performance_samples"]):
            return self._blocked("insufficient_recent_performance_samples", current_fraction=portfolio.position_fraction)

        interval_width = max(q90 - q10, 1e-6)
        scale = max(interval_width / 2.0, 0.005)
        median_direction = math.tanh(q50 / scale)
        if q10 > 0:
            interval_position = 1.0
            reasons.append("forecast_interval_above_zero")
        elif q90 < 0:
            interval_position = -1.0
            reasons.append("forecast_interval_below_zero")
        else:
            interval_position = _clip(q50 / interval_width)
            risk_flags.append("forecast_interval_crosses_zero")

        accuracy = _finite(performance.get("directional_accuracy", 0.5), "directional_accuracy")
        sample_weight = min(1.0, samples / 30.0)
        reliability = _clip((accuracy - 0.5) / 0.10, 0.0, 1.0) * sample_weight
        direction_sign = 1.0 if q50 > 0 else -1.0 if q50 < 0 else 0.0
        reliability_direction = direction_sign * reliability
        trend_sign = 1.0 if trend.get("direction") == "up" else -1.0 if trend.get("direction") == "down" else 0.0
        trend_strength = _clip(_finite(trend.get("regression_r_squared", 0.0), "trend_r2"), 0.0, 1.0)
        trend_alignment = trend_sign * trend_strength
        daily_vol = max(_finite(market.get("realized_volatility", 0.0), "daily_volatility"), 1e-6)
        momentum = math.tanh(_finite(market.get("cumulative_return", 0.0), "cumulative_return") / max(daily_vol * math.sqrt(max(1, int(market.get("sample_count", 1)))), 0.02))
        up_balance = _clip((_finite(market.get("up_day_ratio", 0.5), "up_day_ratio") - 0.5) * 2.0)

        signed = _clip(
            0.30 * median_direction
            + 0.25 * interval_position
            + 0.20 * reliability_direction
            + 0.15 * trend_alignment
            + 0.07 * momentum
            + 0.03 * up_balance
        )
        relative_mae = performance.get("relative_mae")
        if relative_mae is not None and _finite(relative_mae, "relative_mae") >= 1.0:
            signed *= 0.9
            risk_flags.append("mae_does_not_beat_zero_return")
        annualized_vol = _finite(market.get("annualized_volatility", 0.0), "annualized_volatility")
        market_drawdown = _finite(market.get("maximum_drawdown", 0.0), "maximum_drawdown")
        if annualized_vol > float(self.config["max_annualized_volatility"]):
            signed *= 0.7
            risk_flags.append("high_market_volatility")
        if market_drawdown < -float(self.config["max_market_drawdown_fraction"]):
            signed *= 0.7
            risk_flags.append("deep_market_drawdown")

        threshold = float(self.config["trade_threshold"])
        max_asset = float(self.config["max_asset_fraction"])
        max_order = float(self.config["max_order_fraction"])
        tolerance = float(self.config["rebalance_tolerance"])
        support_score = abs(signed)
        if portfolio.maximum_drawdown <= -float(self.config["max_portfolio_drawdown_fraction"]):
            risk_flags.append("portfolio_drawdown_limit")
            target_fraction = 0.0
            reasons.append("risk_exit")
        elif signed >= threshold:
            target_fraction = min(max_asset, max_asset * support_score)
            reasons.append("bullish_support_exceeds_threshold")
        elif signed <= -threshold:
            target_fraction = 0.0
            reasons.append("bearish_support_exceeds_threshold")
        else:
            target_fraction = portfolio.position_fraction
            reasons.append("support_below_trade_threshold")

        delta_fraction = target_fraction - portfolio.position_fraction
        if abs(delta_fraction) <= tolerance:
            action = "HOLD"
            notional = 0.0
            if abs(delta_fraction) > 1e-12:
                reasons.append("within_rebalance_tolerance")
            elif signed <= -threshold and portfolio.position_quantity <= 0:
                reasons.append("no_position_to_sell")
        elif delta_fraction > 0:
            action = "BUY"
            notional = min(
                delta_fraction * portfolio.equity_usdt,
                max_order * portfolio.equity_usdt,
                portfolio.cash_usdt,
            )
            if notional <= 0:
                return self._blocked(
                    "insufficient_paper_cash", risk_flags,
                    current_fraction=portfolio.position_fraction,
                )
        else:
            action = "SELL"
            notional = min(
                -delta_fraction * portfolio.equity_usdt,
                max_order * portfolio.equity_usdt,
                portfolio.position_value_usdt,
            )
            if notional <= 0 or portfolio.position_quantity <= 0:
                action, notional = "HOLD", 0.0
                reasons.append("no_position_to_sell")

        components = {
            "median_direction": median_direction,
            "interval_position": interval_position,
            "direction_reliability": reliability_direction,
            "trend_alignment": trend_alignment,
            "momentum": momentum,
            "up_day_balance": up_balance,
        }
        return DecisionDraft(
            action=action,
            support_score=support_score,
            signed_score=signed,
            target_position_fraction=target_fraction,
            order_notional_usdt=notional,
            reasons=tuple(reasons),
            risk_flags=tuple(risk_flags),
            components=components,
            executable=action in ("BUY", "SELL") and notional > 0,
        )

    @staticmethod
    def _blocked(reason: str, flags=(), current_fraction=0.0) -> DecisionDraft:
        return DecisionDraft(
            action="NO_TRADE", support_score=0.0, signed_score=0.0,
            target_position_fraction=current_fraction, order_notional_usdt=0.0,
            reasons=(reason,), risk_flags=tuple(flags), executable=False,
        )
