import numpy as np
import pandas as pd

from research.hourly.research_hourly_calibration import optimal_shrink,past_mask


def test_weighted_median_solves_scalar_absolute_error():
    p=np.array([-2.,-1.,1.,2.])
    y=.7*p
    assert optimal_shrink(y,p)==.7
    assert optimal_shrink(-y,p)==0.
    assert optimal_shrink(4*p,p)==2.
    assert optimal_shrink(y,np.zeros(4))==0.


def test_label_publication_lag_excludes_recent_and_future_labels():
    opened=pd.date_range('2025-06-30 20:00',periods=6,freq='h',tz='UTC')
    meta=pd.DataFrame(dict(target_open_time=opened,target_close_time=opened+pd.Timedelta(hours=1)))
    mask=past_mask(meta,pd.Timestamp('2025-07-01',tz='UTC'),30)
    np.testing.assert_array_equal(mask,[True,True,True,False,False,False])
