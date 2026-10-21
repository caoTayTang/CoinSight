import numpy as np
import pandas as pd
import pytest

from pipeline.decision.hourly_derivatives import build_derivatives


def data():
    n=200
    close=100*np.exp(np.sin(np.arange(n)/10)*.001)
    btc=pd.DataFrame(dict(open_time=pd.date_range('2024-01-01',periods=n,freq='h',tz='UTC'),
        open_price=close,high_price=close*1.001,low_price=close*.999,close_price=close,
        volume_quote=np.full(n,100.),trade_count=np.full(n,10)))
    futures=btc.copy()
    futures[['open_price','high_price','low_price','close_price']]*=1.0001
    futures['taker_buy_quote']=60.
    funding=pd.DataFrame(dict(calc_time=pd.date_range('2023-12-31',periods=30,freq='8h',tz='UTC'),
        last_funding_rate=np.arange(30)*.00001))
    return btc,futures,funding


def test_settled_funding_has_one_hour_delay_from_forecast_cutoff():
    btc,futures,funding=data()
    result=build_derivatives(btc,futures,funding)
    at07=pd.Timestamp('2024-01-01 07:00',tz='UTC')
    at08=at07+pd.Timedelta(hours=1)
    # Input at 07 predicts target opening 08; settlement at 08 is excluded.
    assert result.loc[at07,'funding_settled_lagged']==pytest.approx(.00003)
    assert result.loc[at08,'funding_settled_lagged']==pytest.approx(.00004)


def test_future_derivative_and_funding_changes_cannot_affect_past():
    btc,futures,funding=data()
    before=build_derivatives(btc,futures,funding)
    cutoff=btc.open_time.iloc[100]
    changed=futures.copy()
    changed.loc[changed.open_time.gt(cutoff),['open_price','high_price','low_price','close_price']]*=2
    later=funding.copy()
    later.loc[later.calc_time.gt(cutoff),'last_funding_rate']+=.01
    pd.testing.assert_frame_equal(before.loc[:cutoff],build_derivatives(btc,changed,later).loc[:cutoff])
    pd.testing.assert_frame_equal(before.loc[:cutoff],build_derivatives(btc[btc.open_time.le(cutoff)],
        futures[futures.open_time.le(cutoff)],funding[funding.calc_time.le(cutoff)]))


def test_duplicate_funding_is_rejected():
    btc,futures,funding=data()
    with pytest.raises(ValueError,match='funding'):
        build_derivatives(btc,futures,pd.concat([funding,funding.iloc[[0]]]))
