"""Small dependency-free contracts for policy, persistence and API layers."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

Action = Literal["BUY", "SELL", "HOLD", "NO_TRADE"]


@dataclass(frozen=True)
class PortfolioState:
    portfolio_id: str
    user_key: str
    initial_cash_usdt: float
    cash_usdt: float
    equity_usdt: float
    realized_pnl_usdt: float
    maximum_drawdown: float
    symbol: str
    position_quantity: float
    average_entry_price_usdt: float | None
    current_price_usdt: float
    position_value_usdt: float
    position_fraction: float
    price_observed_at: datetime


@dataclass(frozen=True)
class DecisionDraft:
    action: Action
    support_score: float
    signed_score: float
    target_position_fraction: float
    order_notional_usdt: float
    reasons: tuple[str, ...] = ()
    risk_flags: tuple[str, ...] = ()
    components: dict[str, float] = field(default_factory=dict)
    executable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OrderPreview:
    decision_id: str
    portfolio_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: float
    market_price_usdt: float
    fill_price_usdt: float
    notional_usdt: float
    slippage_bps: float
    source_candle_time: datetime
    cash_after_usdt: float
    position_quantity_after: float

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["source_candle_time"] = self.source_candle_time.isoformat()
        return result
