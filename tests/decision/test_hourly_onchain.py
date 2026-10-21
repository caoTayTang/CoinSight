import numpy as np
import pandas as pd
import pytest
from pipeline.decision.hourly_onchain import NETWORK,FLOWS,onchain_inputs


def source():
    dates=pd.date_range('2024-01-01',periods=90,freq='D',tz='UTC')
    d=pd.DataFrame({'time':dates,'AssetEODCompletionTime':(dates+pd.Timedelta(hours=26)).asi8/1e9})
    for col in NETWORK+FLOWS: d[col]=np.arange(90,dtype=float)+10
    return d


def test_daily_completion_delay_and_future_invariance():
    d=source();cut=pd.Series(pd.date_range('2024-02-01',periods=25,freq='h',tz='UTC'))
    got=onchain_inputs(d,cut)
    assert got.iloc[0].chain_TxCnt_log==np.log1p(d.iloc[29].TxCnt)
    other=d.copy();other.loc[other.time>=pd.Timestamp('2024-02-01',tz='UTC'),'TxCnt']=9999
    pd.testing.assert_frame_equal(got,onchain_inputs(other,cut))
    # A late provider completion must postpone use even beyond configured delay.
    d.loc[29,'AssetEODCompletionTime']=pd.Timestamp('2024-02-02',tz='UTC').timestamp()
    assert onchain_inputs(d,cut).iloc[0].chain_TxCnt_log==np.log1p(d.iloc[28].TxCnt)


def test_missing_days_and_invalid_inputs():
    d=source().drop(index=29)
    cut=pd.date_range('2024-02-01',periods=1,freq='h',tz='UTC')
    assert onchain_inputs(d,cut).iloc[0].isna().all()
    with pytest.raises(ValueError): onchain_inputs(source(),cut,delay_hours=24)
    with pytest.raises(ValueError): onchain_inputs(pd.concat([source(),source().iloc[:1]]),cut)
    with pytest.raises(ValueError): onchain_inputs(source(),cut.tz_localize(None))
