import numpy as np
import pandas as pd

from research.hourly.research_hourly_transfer import normalized_features


def test_transfer_normalization_does_not_learn_offsets_from_validation():
    frame=pd.DataFrame(dict(return_std_24=[.001,.002,.003,.004],log_return=[.001,.002,.003,.004],
        log_volume=[10.,12.,20.,30.],log_trade_count=[3.,4.,9.,10.],log_quote_per_trade=[7.,8.,9.,10.]))
    train=np.array([True,True,False,False])
    before,scale,offsets=normalized_features(frame,train)
    changed=frame.copy()
    changed.loc[~train,['log_volume','log_trade_count','log_quote_per_trade']]+=100
    after,new_scale,new_offsets=normalized_features(changed,train)
    assert offsets==new_offsets
    pd.testing.assert_frame_equal(before.loc[train],after.loc[train])
    np.testing.assert_array_equal(scale,new_scale)
    np.testing.assert_allclose(before.log_return,1.)
