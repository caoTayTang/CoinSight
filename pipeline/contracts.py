from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PriceTick:
    symbol: str
    ts: datetime
    price_usd: float
    volume_usd: float


def validate_tick(tick: PriceTick) -> PriceTick:
    if not tick.symbol.strip():
        raise ValueError("symbol is required")
    if tick.price_usd <= 0:
        raise ValueError("price_usd must be positive")
    if tick.volume_usd < 0:
        raise ValueError("volume_usd must be non-negative")
    return tick

