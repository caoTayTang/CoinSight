import numpy as np
import pandas as pd

from pipeline.decision.hourly_bookdepth import BANDS,summarize_day,book_inputs


def data():
    times=pd.date_range('2024-01-01 00:00:30',periods=360,freq='30s',tz='UTC')
    records=[]
    for t in times:
        for band in BANDS:
            qty=1000*abs(band)*(1.2 if band<0 else 1.)
            records.append(dict(timestamp=t,percentage=band,depth=qty,notional=qty*100*(1+band*.001)))
    raw=pd.DataFrame(records)
    reference=pd.DataFrame(dict(available_time=pd.date_range('2023-12-31',periods=30,freq='h',tz='UTC'),close_price=100.))
    btc=pd.DataFrame(dict(open_time=pd.date_range('2024-01-01',periods=3,freq='h',tz='UTC')))
    return raw,reference,btc


def test_depth_timestamp_margin_and_future_invariance():
    raw,reference,btc=data()
    aggregate,quality=summarize_day(raw,reference,'2024-01-01')
    result=book_inputs(btc,aggregate)
    assert quality['invalid_snapshots']==0
    assert result.book_available.eq(1).all()
    assert result.book_age_minutes.ge(10).all()
    allowed=pd.Timestamp('2024-01-01 00:50',tz='UTC')
    changed=raw.copy()
    changed.loc[changed.timestamp.gt(allowed),['depth','notional']]*=5
    later,_=summarize_day(changed,reference,'2024-01-01')
    pd.testing.assert_frame_equal(result.iloc[:1],book_inputs(btc,later).iloc[:1])


def test_implausible_band_price_is_missing_information_not_a_target_filter():
    raw,reference,btc=data()
    raw['notional']*=100
    aggregate,quality=summarize_day(raw,reference,'2024-01-01')
    assert quality['healthy_snapshots']==0
    result=book_inputs(btc,aggregate)
    assert len(result)==len(btc)
    assert result.book_available.eq(0).all()
