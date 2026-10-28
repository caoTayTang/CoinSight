"""Orchestrate immutable forecast evidence, policy evaluation and persistence."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from .policy import DailyQuantilePolicy
from .policy_store import PolicyStore
from .repository import PaperTradingRepository


def evidence_sha256(value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


class TradeDecisionService:
    def __init__(self, repository=None, policy_store=None):
        self.repository = repository or PaperTradingRepository()
        self.policy_store = policy_store or PolicyStore()

    def create(
        self,
        user_key: str,
        portfolio_id: str,
        support: dict,
        policy_name: str = "daily_quantile_v1",
    ) -> dict:
        symbol = str(support.get("symbol", "")).upper()
        if symbol not in ("BTC", "ETH"):
            raise ValueError("paper decision supports BTC and ETH only")
        evaluated = self.evaluate(user_key, portfolio_id, support, policy_name)
        return self.repository.save_decision(
            user_key, portfolio_id, support, evaluated["policy"], evaluated["draft"],
            evaluated["evidence_sha256"], evaluated["execution"],
        )

    def evaluate(
        self,
        user_key: str,
        portfolio_id: str,
        support: dict,
        policy_name: str = "daily_quantile_v1",
    ) -> dict:
        symbol = str(support.get("symbol", "")).upper()
        if symbol not in ("BTC", "ETH"):
            raise ValueError("paper decision supports BTC and ETH only")
        default = self.policy_store.load(policy_name)
        policy_config = self.repository.active_policy(user_key, default)["config"]
        state = self.repository.state(user_key, portfolio_id, symbol)
        evaluated_at = datetime.now(UTC)
        observed_at = state.price_observed_at.astimezone(UTC)
        price_age_seconds = (evaluated_at - observed_at).total_seconds()
        draft = DailyQuantilePolicy(policy_config).evaluate(
            support, state, now=evaluated_at
        )
        execution = {
            "evaluated_at": evaluated_at,
            "price_usdt": state.current_price_usdt,
            "price_observed_at": observed_at,
            "price_age_seconds": price_age_seconds,
            "current_position_fraction": state.position_fraction,
        }
        return {
            "status": "ready",
            "symbol": symbol,
            "portfolio": {
                "portfolio_id": state.portfolio_id,
                "cash_usdt": state.cash_usdt,
                "equity_usdt": state.equity_usdt,
                "position_quantity": state.position_quantity,
                "position_fraction": state.position_fraction,
                "current_price_usdt": state.current_price_usdt,
                "price_observed_at": state.price_observed_at.isoformat(),
            },
            "decision": draft.to_dict(),
            "draft": draft,
            "policy": policy_config,
            "execution": execution,
            "evidence_sha256": evidence_sha256(support),
            "forecast": support.get("forecast"),
            "recent_performance": support.get("recent_performance"),
            "limitations": [
                "paper simulation only",
                "support_score is deterministic and not a probability",
                "no fee simulation; configured slippage is applied only when a paper order is confirmed",
            ],
        }

    def preview(self, user_key: str, portfolio_id: str, decision_id: str) -> dict:
        config = self._decision_policy(user_key, portfolio_id, decision_id)
        return self.repository.preview(
            user_key, portfolio_id, decision_id, config["slippage_bps"],
            config["max_price_age_seconds"],
        ).to_dict()

    def execute(
        self, user_key: str, portfolio_id: str, decision_id: str, idempotency_key: str,
        expected_source_candle_time: datetime,
    ) -> dict:
        config = self._decision_policy(user_key, portfolio_id, decision_id)
        return self.repository.execute(
            user_key, portfolio_id, decision_id, idempotency_key, config["slippage_bps"],
            expected_source_candle_time, config["max_price_age_seconds"],
        )

    def active_policy(self, user_key: str) -> dict:
        return self.repository.active_policy(
            user_key, self.policy_store.load("daily_quantile_v1")
        )

    def save_policy(self, user_key: str, value: dict) -> dict:
        return self.repository.save_policy(
            user_key, self.policy_store.normalize_user_config(value)
        )

    def reset_policy(self, user_key: str) -> dict:
        return self.repository.reset_policy(
            user_key, self.policy_store.load("daily_quantile_v1")
        )

    def normalize_policy(self, value: dict) -> dict:
        return self.policy_store.normalize_user_config(value)

    def _decision_policy(self, user_key: str, portfolio_id: str, decision_id: str) -> dict:
        decision = self.repository.decision(user_key, portfolio_id, decision_id)
        frozen = decision.get("policy_config")
        if isinstance(frozen, dict) and frozen:
            return self.policy_store.validate(frozen)
        # Compatibility for decisions created before migration 013.
        return self.policy_store.load("daily_quantile_v1")
