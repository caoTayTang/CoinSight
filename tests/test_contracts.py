from datetime import datetime, timezone

import pytest

from pipeline.contracts import PriceTick, validate_tick


def test_valid_tick_passes():
    tick = PriceTick("BTC", datetime.now(timezone.utc), 1.0, 0.0)
    assert validate_tick(tick) == tick


def test_invalid_price_fails():
    tick = PriceTick("BTC", datetime.now(timezone.utc), 0.0, 1.0)
    with pytest.raises(ValueError, match="price_usd"):
        validate_tick(tick)

