"""Causal replay for precomputed forecast-support observations.

The runner deliberately accepts frozen evidence rows instead of querying today's
warehouse. This prevents a policy backtest from silently becoming non-causal.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from collections import Counter
from typing import Any, Iterable

from .contracts import PortfolioState
from .policy import DailyQuantilePolicy


@dataclass(frozen=True)
class BacktestObservation:
    observed_at: datetime
    symbol: str
    market_price_usdt: float
    support: dict[str, Any]
    actual_target_close_usdt: float | None = None


class PolicyBacktester:
    def __init__(self, policy_config: dict[str, Any]):
        self.config = dict(policy_config)
        self.policy = DailyQuantilePolicy(policy_config)

    def run(
        self,
        observations: Iterable[BacktestObservation],
        *,
        initial_cash_usdt: float = 100_000.0,
    ) -> dict[str, Any]:
        rows = sorted(observations, key=lambda row: row.observed_at)
        if not rows:
            raise ValueError("backtest requires at least one frozen observation")
        cash = float(initial_cash_usdt)
        quantity = 0.0
        average_entry = None
        realized = 0.0
        peak = cash
        trades: list[dict[str, Any]] = []
        curve: list[dict[str, Any]] = []
        action_counts = {name: 0 for name in ("BUY", "SELL", "HOLD", "NO_TRADE")}
        hold_reasons: Counter[str] = Counter()
        hold_context_reasons: Counter[str] = Counter()
        hold_risk_flags: Counter[str] = Counter()
        no_trade_reasons: Counter[str] = Counter()
        action_utility = {
            side: {
                "action_count": 0,
                "evaluated_count": 0,
                "unavailable_outcome_count": 0,
                "directionally_useful_count": 0,
                "directionally_harmful_or_flat_count": 0,
                "directionally_neutral_flat_count": 0,
                "slippage_evaluated_count": 0,
                "profitable_after_slippage_count": 0,
                "unprofitable_after_slippage_count": 0,
                "invested_context_count": 0,
                "cash_context_count": 0,
                "estimated_next_day_effect_usdt": 0.0,
            }
            for side in ("BUY", "SELL", "HOLD")
        }
        first_price = float(rows[0].market_price_usdt)
        slippage = float(self.config["slippage_bps"]) / 10_000.0

        for observation in rows:
            observed = observation.observed_at.astimezone(UTC)
            price = float(observation.market_price_usdt)
            if price <= 0:
                raise ValueError("market prices must be positive")
            equity_before = cash + quantity * price
            peak = max(peak, equity_before)
            value = quantity * price
            state = PortfolioState(
                portfolio_id="backtest", user_key="backtest",
                initial_cash_usdt=initial_cash_usdt, cash_usdt=cash,
                equity_usdt=equity_before, realized_pnl_usdt=realized,
                maximum_drawdown=min(0.0, equity_before / peak - 1.0),
                symbol=observation.symbol, position_quantity=quantity,
                average_entry_price_usdt=average_entry, current_price_usdt=price,
                position_value_usdt=value,
                position_fraction=value / equity_before if equity_before else 0.0,
                price_observed_at=observed,
            )
            decision = self.policy.evaluate(observation.support, state, now=observed)
            action_counts[decision.action] += 1
            if decision.action == "HOLD":
                hold_reasons[self._primary_hold_reason(decision.reasons)] += 1
                hold_context_reasons.update(decision.reasons or ("unspecified",))
                hold_risk_flags.update(decision.risk_flags)
            elif decision.action == "NO_TRADE":
                no_trade_reasons.update(decision.reasons or ("unspecified",))
            trade_record = None
            utility_record = None
            if decision.action == "BUY" and decision.order_notional_usdt > 0:
                notional = min(decision.order_notional_usdt, cash)
                fill = price * (1.0 + slippage)
                bought = notional / fill
                new_quantity = quantity + bought
                average_entry = (
                    quantity * (average_entry or 0.0) + notional
                ) / new_quantity
                quantity, cash = new_quantity, cash - notional
                trade_record = self._trade(
                    observed, decision, bought, price, fill, notional,
                    observation.actual_target_close_usdt,
                )
                trades.append(trade_record)
                utility_record = trade_record
            elif decision.action == "SELL" and decision.order_notional_usdt > 0 and quantity > 0:
                fill = price * (1.0 - slippage)
                sold = min(quantity, decision.order_notional_usdt / fill)
                notional = sold * fill
                realized += sold * (fill - (average_entry or fill))
                quantity, cash = quantity - sold, cash + notional
                if quantity <= 1e-12:
                    quantity, average_entry = 0.0, None
                trade_record = self._trade(
                    observed, decision, sold, price, fill, notional,
                    observation.actual_target_close_usdt,
                )
                trades.append(trade_record)
                utility_record = trade_record
            elif decision.action == "HOLD":
                utility_record = self._hold_utility(
                    state, observation.actual_target_close_usdt
                )
            if decision.action in action_utility:
                self._accumulate_action_utility(
                    action_utility[decision.action], utility_record
                )
            equity = cash + quantity * price
            peak = max(peak, equity)
            buy_hold_equity = initial_cash_usdt * price / first_price
            actual_target = observation.actual_target_close_usdt
            actual_return = (
                None if actual_target is None
                else float(actual_target) / price - 1.0
            )
            forecast = observation.support.get("forecast", {})
            curve.append({
                "observed_at": observed.isoformat(), "market_price_usdt": price,
                "cash_usdt": cash, "position_quantity": quantity,
                "equity_usdt": equity, "drawdown": min(0.0, equity / peak - 1.0),
                "buy_hold_equity_usdt": buy_hold_equity,
                "position_fraction": quantity * price / equity if equity else 0.0,
                "action": decision.action, "signed_score": decision.signed_score,
                "support_score": decision.support_score,
                "target_position_fraction": decision.target_position_fraction,
                "decision_reasons": "|".join(decision.reasons),
                "risk_flags": "|".join(decision.risk_flags),
                "actual_target_close_usdt": actual_target,
                "actual_target_return": actual_return,
                # Keep the frozen forecast next to its realized outcome so the
                # UI can compare direction/magnitude without reconstructing it
                # from the policy score (which also contains market signals).
                "forecast_return_q10": float(forecast["return_q10"]),
                "forecast_return_q50": float(forecast["return_q50"]),
                "forecast_return_q90": float(forecast["return_q90"]),
                "action_directional_utility": (
                    None if utility_record is None
                    else utility_record["directional_utility"]
                ),
                "action_after_slippage_utility": (
                    None if utility_record is None
                    else utility_record["after_slippage_utility"]
                ),
                "hold_context": (
                    None if utility_record is None
                    else utility_record.get("hold_context")
                ),
            })

        final_equity = curve[-1]["equity_usdt"]
        buy_hold_equity = initial_cash_usdt * rows[-1].market_price_usdt / first_price
        total_return = final_equity / initial_cash_usdt - 1.0
        buy_hold_return = buy_hold_equity / initial_cash_usdt - 1.0
        return {
            "policy_id": self.config["policy_id"],
            "policy_version": self.config["version"],
            "policy_sha256": self.config.get("sha256"),
            "fee_simulation": False,
            "slippage_bps": self.config["slippage_bps"],
            "observation_count": len(rows),
            "trade_count": len(trades),
            "action_counts": action_counts,
            "hold_reason_counts": dict(sorted(hold_reasons.items())),
            "hold_context_reason_counts": dict(sorted(hold_context_reasons.items())),
            "hold_risk_flag_counts": dict(sorted(hold_risk_flags.items())),
            "no_trade_reason_counts": dict(sorted(no_trade_reasons.items())),
            "start_observed_at": rows[0].observed_at.astimezone(UTC).isoformat(),
            "end_observed_at": rows[-1].observed_at.astimezone(UTC).isoformat(),
            "start_market_price_usdt": first_price,
            "end_market_price_usdt": float(rows[-1].market_price_usdt),
            "initial_cash_usdt": initial_cash_usdt,
            "final_equity_usdt": final_equity,
            "profit_loss_usdt": final_equity - initial_cash_usdt,
            "total_return": total_return,
            "total_return_percent": total_return * 100.0,
            "maximum_drawdown": min(row["drawdown"] for row in curve),
            "average_position_fraction": sum(
                row["position_fraction"] for row in curve
            ) / len(curve),
            "buy_hold_final_equity_usdt": buy_hold_equity,
            "buy_hold_profit_loss_usdt": buy_hold_equity - initial_cash_usdt,
            "buy_hold_return": buy_hold_return,
            "buy_hold_return_percent": buy_hold_return * 100.0,
            "excess_return_vs_buy_hold": total_return - buy_hold_return,
            "excess_return_vs_buy_hold_percent": (total_return - buy_hold_return) * 100.0,
            "turnover_usdt": sum(row["notional_usdt"] for row in trades),
            "forecast_direction_diagnostics": self._direction_diagnostics(rows),
            "policy_action_utility": {
                side: self._finalize_action_utility(values)
                for side, values in action_utility.items()
            },
            "trades": trades,
            "equity_curve": curve,
            "limitations": [
                "valid only when each support payload was generated causally at observed_at",
                "simulates configured slippage but no exchange fee",
                "final equity is mark-to-market; an open position is not force-liquidated",
                "buy-and-hold benchmark does not include slippage or exchange fees",
            ],
        }

    @staticmethod
    def _direction_diagnostics(rows: list[BacktestObservation]) -> dict[str, Any]:
        counts = {
            "predicted_up_actual_up": 0,
            "predicted_down_actual_up": 0,
            "predicted_up_actual_down_or_flat": 0,
            "predicted_down_actual_down_or_flat": 0,
        }
        unavailable = 0
        for row in rows:
            if row.actual_target_close_usdt is None:
                unavailable += 1
                continue
            predicted_return = float(row.support["forecast"]["return_q50"])
            predicted_up = predicted_return > 0.0
            actual_up = float(row.actual_target_close_usdt) > float(row.market_price_usdt)
            if predicted_up and actual_up:
                counts["predicted_up_actual_up"] += 1
            elif not predicted_up and actual_up:
                counts["predicted_down_actual_up"] += 1
            elif predicted_up and not actual_up:
                counts["predicted_up_actual_down_or_flat"] += 1
            else:
                counts["predicted_down_actual_down_or_flat"] += 1
        evaluated = sum(counts.values())
        correct = (
            counts["predicted_up_actual_up"]
            + counts["predicted_down_actual_down_or_flat"]
        )
        predicted_up_count = (
            counts["predicted_up_actual_up"]
            + counts["predicted_up_actual_down_or_flat"]
        )
        predicted_down_count = evaluated - predicted_up_count
        return {
            "evaluated_count": evaluated,
            "unavailable_outcome_count": unavailable,
            "down_includes_flat": True,
            "counts": counts,
            "rates_over_evaluated": {
                key: (value / evaluated if evaluated else None)
                for key, value in counts.items()
            },
            "rates_percent_over_evaluated": {
                key: (value / evaluated * 100.0 if evaluated else None)
                for key, value in counts.items()
            },
            "directional_accuracy": correct / evaluated if evaluated else None,
            "predicted_up_correct_rate": (
                counts["predicted_up_actual_up"] / predicted_up_count
                if predicted_up_count else None
            ),
            "predicted_down_correct_rate": (
                counts["predicted_down_actual_down_or_flat"] / predicted_down_count
                if predicted_down_count else None
            ),
        }

    @staticmethod
    def _primary_hold_reason(reasons: tuple[str, ...]) -> str:
        for candidate in (
            "no_position_to_sell",
            "support_below_trade_threshold",
            "within_rebalance_tolerance",
        ):
            if candidate in reasons:
                return candidate
        if "bullish_support_exceeds_threshold" in reasons:
            return "target_position_already_satisfied"
        return "unspecified"

    @staticmethod
    def _trade(
        observed, decision, quantity, reference_price, fill, notional,
        actual_target_close_usdt=None,
    ):
        actual = (
            None if actual_target_close_usdt is None
            else float(actual_target_close_usdt)
        )
        if actual is None:
            directional_utility = after_slippage_utility = "unavailable"
            next_day_effect = None
        elif decision.action == "BUY":
            directional_utility = (
                "useful" if actual > reference_price else "harmful_or_flat"
            )
            next_day_effect = quantity * (actual - fill)
            after_slippage_utility = (
                "profitable" if next_day_effect > 0 else "unprofitable_or_flat"
            )
        else:
            directional_utility = (
                "useful" if actual < reference_price else "harmful_or_flat"
            )
            # Counterfactual benefit of having sold this quantity before the
            # target close. It is avoided loss/missed gain, not short P&L.
            next_day_effect = quantity * (fill - actual)
            after_slippage_utility = (
                "profitable" if next_day_effect > 0 else "unprofitable_or_flat"
            )
        return {
            "observed_at": observed.isoformat(), "side": decision.action,
            "quantity": quantity, "fill_price_usdt": fill,
            "reference_price_usdt": reference_price,
            "notional_usdt": notional, "signed_score": decision.signed_score,
            "actual_target_close_usdt": actual,
            "directional_utility": directional_utility,
            "after_slippage_utility": after_slippage_utility,
            "estimated_next_day_effect_usdt": next_day_effect,
        }

    @staticmethod
    def _hold_utility(state: PortfolioState, actual_target_close_usdt):
        actual = (
            None if actual_target_close_usdt is None
            else float(actual_target_close_usdt)
        )
        invested = state.position_quantity > 1e-12
        context = "invested" if invested else "cash"
        if actual is None:
            directional = "unavailable"
            effect = None
        elif actual == state.current_price_usdt:
            directional = "neutral_flat"
            effect = 0.0
        elif invested:
            directional = (
                "useful" if actual > state.current_price_usdt else "harmful_or_flat"
            )
            effect = state.position_quantity * (actual - state.current_price_usdt)
        else:
            # Staying in cash is useful when it avoids a decline and harmful
            # when it misses an increase. Actual portfolio P&L remains zero.
            directional = (
                "useful" if actual < state.current_price_usdt else "harmful_or_flat"
            )
            effect = 0.0
        return {
            "actual_target_close_usdt": actual,
            "directional_utility": directional,
            "after_slippage_utility": "not_applicable",
            "estimated_next_day_effect_usdt": effect,
            "hold_context": context,
        }

    @staticmethod
    def _accumulate_action_utility(values, utility):
        values["action_count"] += 1
        if utility is None or utility["actual_target_close_usdt"] is None:
            values["unavailable_outcome_count"] += 1
            return
        values["evaluated_count"] += 1
        context = utility.get("hold_context")
        if context is not None:
            values[f"{context}_context_count"] += 1
        if utility["directional_utility"] == "useful":
            values["directionally_useful_count"] += 1
        elif utility["directional_utility"] == "neutral_flat":
            values["directionally_neutral_flat_count"] += 1
        else:
            values["directionally_harmful_or_flat_count"] += 1
        if utility["after_slippage_utility"] == "profitable":
            values["slippage_evaluated_count"] += 1
            values["profitable_after_slippage_count"] += 1
        elif utility["after_slippage_utility"] == "unprofitable_or_flat":
            values["slippage_evaluated_count"] += 1
            values["unprofitable_after_slippage_count"] += 1
        values["estimated_next_day_effect_usdt"] += float(
            utility["estimated_next_day_effect_usdt"]
        )

    @staticmethod
    def _finalize_action_utility(values):
        result = dict(values)
        evaluated = int(result["evaluated_count"])
        result["directionally_useful_rate"] = (
            result["directionally_useful_count"] / evaluated
            if evaluated else None
        )
        result["directionally_harmful_or_flat_rate"] = (
            result["directionally_harmful_or_flat_count"] / evaluated
            if evaluated else None
        )
        result["directionally_neutral_flat_rate"] = (
            result["directionally_neutral_flat_count"] / evaluated
            if evaluated else None
        )
        slippage_evaluated = int(result["slippage_evaluated_count"])
        result["profitable_after_slippage_rate"] = (
            result["profitable_after_slippage_count"] / slippage_evaluated
            if slippage_evaluated else None
        )
        result["unprofitable_after_slippage_rate"] = (
            result["unprofitable_after_slippage_count"] / slippage_evaluated
            if slippage_evaluated else None
        )
        result["mean_estimated_next_day_effect_usdt"] = (
            result["estimated_next_day_effect_usdt"] / evaluated
            if evaluated else None
        )
        return result
