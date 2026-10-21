import numpy as np

from research.hourly.research_hourly_regimes import regime_ids


def test_future_observations_cannot_change_learned_gates():
    vol=np.linspace(.001,.01,100)
    trend=np.sin(np.arange(100))
    train=np.arange(100)<60
    original,cuts=regime_ids(vol,trend,train)
    future_vol=vol.copy();future_vol[60:]*=100
    future_trend=trend.copy();future_trend[60:]+=100
    changed,changed_cuts=regime_ids(future_vol,future_trend,train)
    assert cuts==changed_cuts
    for name in original:
        np.testing.assert_array_equal(original[name][:60],changed[name][:60])
    assert set(original['volatility_trend'])<=set(range(9))
