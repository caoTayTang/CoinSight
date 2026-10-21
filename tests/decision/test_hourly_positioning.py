import numpy as np
import pandas as pd
import pytest

from pipeline.decision.hourly_positioning import FIELDS,build_positioning


def data():
    n=200
    close=100*np.exp(np.arange(n)*.0001)
    btc=pd.DataFrame(dict(open_time=pd.date_range('2024-01-01',periods=n,freq='h',tz='UTC'),
        open_price=close,high_price=close*1.001,low_price=close*.999,close_price=close,
        volume_quote=np.full(n,100.),trade_count=np.full(n,10)))
    clock=pd.date_range('2023-12-30',periods=3500,freq='5min',tz='UTC')
    metrics=pd.DataFrame({'create_time':clock})
    for i,column in enumerate(FIELDS):
        metrics[column]=1+i+np.arange(len(clock))*.0001
    return btc,metrics


def test_snapshot_is_aged_at_least_one_hour_at_forecast_cutoff():
    btc,metrics=data()
    features=build_positioning(btc,metrics)
    assert features.index.equals(pd.DatetimeIndex(btc.open_time))
    assert features.positioning_age_hours.ge(1).all()
    at=pd.Timestamp('2024-01-02 00:00',tz='UTC')
    expected=metrics.loc[metrics.create_time.eq(at),'sum_open_interest'].iloc[0]
    assert features.loc[at,'oi_log_contracts']==pytest.approx(np.log(expected))


def test_metrics_future_mutation_and_truncation_invariant():
    btc,metrics=data()
    before=build_positioning(btc,metrics)
    cutoff=btc.open_time.iloc[100]
    changed=metrics.copy()
    changed.loc[changed.create_time.gt(cutoff),FIELDS]*=5
    pd.testing.assert_frame_equal(before.loc[:cutoff],build_positioning(btc,changed).loc[:cutoff])
    pd.testing.assert_frame_equal(before.loc[:cutoff],build_positioning(btc[btc.open_time.le(cutoff)],
        metrics[metrics.create_time.le(cutoff)]))


def test_ten_minute_margin_excludes_every_later_snapshot():
    btc,metrics=data()
    result=build_positioning(btc,metrics,delay_minutes=10)
    at=pd.Timestamp('2024-01-02 00:00',tz='UTC')
    allowed=at+pd.Timedelta(minutes=50)
    expected=metrics.loc[metrics.create_time.eq(allowed),'sum_open_interest'].iloc[0]
    assert result.loc[at,'oi_log_contracts']==pytest.approx(np.log(expected))
    assert result.loc[at,'positioning_age_hours']==pytest.approx(1/6)
    changed=metrics.copy()
    changed.loc[changed.create_time.gt(allowed),FIELDS]*=100
    pd.testing.assert_frame_equal(result.loc[:at],build_positioning(btc,changed,delay_minutes=10).loc[:at])


def test_missing_snapshot_preserves_target_rows_without_future_fill():
    btc,metrics=data()
    metrics=metrics[metrics.create_time.lt(pd.Timestamp('2024-01-03',tz='UTC'))]
    result=build_positioning(btc,metrics)
    assert len(result)==len(btc)
    later=result.loc['2024-01-04':]
    assert later.positioning_available.eq(0).all()
    assert later.oi_log_contracts.isna().all()


def test_conflicting_duplicates_fail_and_identical_duplicates_are_harmless():
    btc,metrics=data()
    before=build_positioning(btc,metrics)
    pd.testing.assert_frame_equal(before,build_positioning(btc,pd.concat([metrics,metrics.iloc[[0]]])))
    bad=metrics.iloc[[0]].copy()
    bad['sum_open_interest']+=1
    with pytest.raises(ValueError,match='Conflicting'):
        build_positioning(btc,pd.concat([metrics,bad]))
