import numpy as np
import pandas as pd
import pytest
from pipeline.decision.hourly_venue import parse_coinbase,venue_inputs


def candles(n=400):
    t=pd.date_range('2024-01-01',periods=n,freq='h',tz='UTC');p=100*np.exp(np.arange(n)*.0001+np.sin(np.arange(n)/11)*.01)
    btc=pd.DataFrame(dict(open_time=t,open_price=p,high_price=p*1.01,low_price=p*.99,close_price=p,
                          volume_quote=1000.,trade_count=100))
    cb=pd.DataFrame(dict(open_time=t,open=p*1.001,high=p*1.011,low=p*.991,close=p*1.001,
                         volume=10+np.arange(n)%7))
    return btc,cb


def test_venue_causality_complete_context_and_extra_lag():
    btc,cb=candles();x=venue_inputs(btc,cb)
    assert x.iloc[168:].notna().all().all()
    pd.testing.assert_frame_equal(x.iloc[:250],venue_inputs(btc.iloc[:250],cb.iloc[:250]))
    changed=cb.copy();changed.loc[250:,['low','high','open','close']]*=2
    pd.testing.assert_frame_equal(x.iloc[:250],venue_inputs(btc,changed).iloc[:250])
    pd.testing.assert_frame_equal(x.shift(1),venue_inputs(btc,cb,1))
    np.testing.assert_allclose(x.iloc[168:].venue_basis,np.log(1.001),atol=1e-14)


def test_missing_coinbase_hour_stays_unknown_for_context():
    btc,cb=candles();x=venue_inputs(btc,cb.drop(index=200))
    assert x.iloc[200:369].isna().all().all()
    assert x.iloc[369:].notna().all().all()


def test_coinbase_parser_mapping_and_rejects_bad_candles():
    row=[1704067200,90,110,95,105,12]
    frame=parse_coinbase([row]);assert frame.iloc[0]['open']==95 and frame.iloc[0]['close']==105
    assert frame.iloc[0]['volume']==12
    for rows in ([row,row],[[1704067201,90,110,95,105,12]],[[1704067200,90,100,95,105,12]],[[1,2]]):
        with pytest.raises(ValueError): parse_coinbase(rows)
