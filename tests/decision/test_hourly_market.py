import numpy as np
import pandas as pd

from pipeline.decision.hourly_market import market_inputs


def candles(seed):
    rng=np.random.default_rng(seed)
    close=100*np.exp(np.cumsum(rng.normal(0,.003,500)))
    return pd.DataFrame(dict(open_time=pd.date_range('2024-01-01',periods=500,freq='h',tz='UTC'),
        open_price=close,high_price=close*1.001,low_price=close*.999,close_price=close,
        volume_quote=rng.uniform(1000,2000,500),trade_count=rng.integers(100,200,500)))


def test_basket_uses_only_closed_contexts_and_fixed_asset_names():
    btc=candles(1);assets={'ETH':candles(2),'ADA':candles(3),'LTC':candles(4)}
    features=market_inputs(btc,assets)
    assert features.shape==(500,26)
    assert features.basket_known_assets.iloc[168:].eq(3).all()
    cutoff=btc.open_time.iloc[300]
    prefix=market_inputs(btc[btc.open_time.le(cutoff)],
        {name:raw[raw.open_time.le(cutoff)] for name,raw in assets.items()})
    pd.testing.assert_frame_equal(features.loc[:cutoff],prefix)
    changed={name:raw.copy() for name,raw in assets.items()}
    for raw in changed.values():
        raw.loc[raw.open_time.gt(cutoff),['open_price','high_price','low_price','close_price']]*=10
    pd.testing.assert_frame_equal(features.loc[:cutoff],market_inputs(btc,changed).loc[:cutoff])


def test_missing_asset_does_not_fill_from_future_or_drop_btc_rows():
    btc=candles(1);assets={'ETH':candles(2),'ADA':candles(3),'LTC':candles(4)}
    assets['ETH']=assets['ETH'].drop(index=250)
    features=market_inputs(btc,assets)
    assert len(features)==500
    assert features.loc[btc.open_time.iloc[250],'basket_known_assets']==2
    assert np.isnan(features.loc[btc.open_time.iloc[250],'basket_return_mean'])
