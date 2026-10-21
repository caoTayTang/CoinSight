import numpy as np

from research.hourly.research_hourly_ensemble import positive_mae_weights


def test_nonnegative_mae_fit_recovers_simple_signal_with_fixed_budget():
    x=np.array([[-2.,0.],[-1.,1.],[0.,-1.],[1.,0.],[2.,1.]])
    y=x[:,0]*.5
    weights=positive_mae_weights(x,y,0.)
    assert np.all(weights>=0)
    assert weights.sum()<=2.+1e-10
    np.testing.assert_allclose(x@weights,y,atol=1e-8)


def test_unhelpful_forecast_can_fall_back_to_zero():
    x=np.array([[-1.],[1.]])
    weights=positive_mae_weights(x,-x[:,0],0.)
    np.testing.assert_allclose(weights,0.,atol=1e-8)
