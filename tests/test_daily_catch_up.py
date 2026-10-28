from datetime import date

import pytest

from pipeline.batch.catch_up_daily import BootstrapRequiredError, tail_plan


def test_tail_plan_repairs_each_symbol_from_its_own_tail():
    tails = {
        "BTC": {"1d": date(2026, 10, 27), "1h": date(2026, 10, 27)},
        "AVAX": {"1d": date(2026, 10, 18), "1h": date(2026, 10, 20)},
    }

    plan = tail_plan(tails, date(2026, 10, 27))

    assert plan[0] == (date(2026, 10, 19), ["AVAX"])
    assert plan[-1] == (date(2026, 10, 27), ["AVAX"])
    assert len(plan) == 9


def test_tail_plan_requires_bootstrap_for_absent_series():
    with pytest.raises(BootstrapRequiredError, match="ETH/1h"):
        tail_plan({"ETH": {"1d": date(2026, 10, 27), "1h": None}}, date(2026, 10, 27))
