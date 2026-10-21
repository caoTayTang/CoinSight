import numpy as np
import pandas as pd
import pytest
from pipeline.decision.hourly_news import news_inputs


def source():
    return pd.DataFrame({'bucket_start':pd.date_range('2024-01-01',periods=200,freq='h',tz='UTC'),
                         'value':np.arange(200,dtype=float),'norm':1000.})


def test_completed_bucket_delay_and_future_mutation():
    frame=source();cutoff=pd.Series(pd.date_range('2024-01-08',periods=10,freq='h',tz='UTC'),index=range(10,20))
    before=news_inputs(frame,cutoff)
    changed=frame.copy();changed.loc[changed.bucket_start>=cutoff.iloc[-1]-pd.Timedelta(hours=2),'value']=999
    pd.testing.assert_frame_equal(before,news_inputs(changed,cutoff))
    expected=frame.set_index('bucket_start').loc[cutoff.iloc[0]-pd.Timedelta(hours=3),'value']/1000
    assert before.iloc[0].news_share==expected
    assert before.index.equals(cutoff.index)
    with pytest.raises(ValueError): news_inputs(frame,cutoff,delay_hours=2)


def test_missing_bucket_is_unknown_and_stale_source_not_carried():
    frame=source().drop(index=190)
    cutoffs=pd.DatetimeIndex([pd.Timestamp('2024-01-01',tz='UTC')+pd.Timedelta(hours=h) for h in (193,210)])
    result=news_inputs(frame,cutoffs)
    assert np.isnan(result.iloc[0].news_share)
    assert result.iloc[0].news_coverage24<1
    assert result.iloc[1].isna().all()


def test_reject_duplicate_invalid_or_naive_news():
    frame=source();cutoffs=pd.date_range('2024-01-08',periods=2,freq='h',tz='UTC')
    with pytest.raises(ValueError): news_inputs(pd.concat([frame,frame.iloc[:1]]),cutoffs)
    frame.loc[0,'norm']=0
    with pytest.raises(ValueError): news_inputs(frame,cutoffs)
    with pytest.raises(ValueError): news_inputs(source(),cutoffs.tz_localize(None))
