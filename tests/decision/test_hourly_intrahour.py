import numpy as np
import pandas as pd
import pytest

from pipeline.decision.hourly_intrahour import build_intrahour


def candles():
    close=100*np.exp(np.arange(48)*.0001)
    return pd.DataFrame(dict(open_time=pd.date_range('2024-01-01',periods=48,freq='5min',tz='UTC'),
        open_price=close*.9999,high_price=close*1.001,low_price=close*.999,
        close_price=close,volume_quote=np.full(48,100.),trade_count=np.full(48,10),
        taker_buy_quote=np.full(48,60.)))


def test_only_completed_hour_used_and_future_mutation_invariant():
    raw=candles()
    before=build_intrahour(raw)
    changed=raw.copy()
    changed.loc[24:,['open_price','high_price','low_price','close_price']]*=2
    pd.testing.assert_frame_equal(before.iloc[:2],build_intrahour(changed).iloc[:2])
    assert before.filter(like='intra_').shape==(4,20)
    np.testing.assert_allclose(before.intra_taker_imbalance,.2)
    np.testing.assert_allclose(before.intra_late_volume_fraction,.25)


def test_missing_or_invalid_subcandle_does_not_create_hour():
    raw=candles()
    before=build_intrahour(raw)
    missing=build_intrahour(raw.drop(index=15))
    assert before.index[1] not in missing.index
    raw.loc[15,'taker_buy_quote']=101
    invalid=build_intrahour(raw)
    assert before.index[1] not in invalid.index


def test_duplicate_subcandle_rejected():
    raw=candles()
    with pytest.raises(ValueError,match='Duplicate'):
        build_intrahour(pd.concat([raw,raw.iloc[[0]]]))
