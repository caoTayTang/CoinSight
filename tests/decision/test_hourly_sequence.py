import importlib.util
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from pipeline.decision.hourly_sequence import sequence_inputs,sequence_asset_weights


def test_auxiliary_loss_weight_has_declared_asset_mass():
    btc=sequence_asset_weights([.001,.002],.5,100)
    aux=sequence_asset_weights([.005,.01,.02],.5/7,100)
    assert btc.sum()==pytest.approx(50)
    assert aux.sum()==pytest.approx(100*.5/7)
    assert btc[1]/btc[0]==pytest.approx(2)


def test_auxiliary_loss_weight_rejects_noncausal_missing_scale():
    with pytest.raises(ValueError,match='volatility'):
        sequence_asset_weights([.001,np.nan],.5,100)


def candles():
    n=500
    rng=np.random.default_rng(42)
    close=100*np.exp(np.cumsum(rng.normal(0,.003,n)))
    return pd.DataFrame(dict(open_time=pd.date_range('2024-01-01',periods=n,freq='h',tz='UTC'),
        open_price=close*.9999,high_price=close*1.001,low_price=close*.999,close_price=close,
        volume_quote=rng.uniform(100,200,n),trade_count=rng.integers(10,100,n)))


def test_169_candles_suffice_without_label_or_outside_history():
    raw=candles()
    end=raw.open_time.iloc[-1]
    for include_eth in (False,True):
        full,scale=sequence_inputs(raw,raw,[end],include_eth)
        last,last_scale=sequence_inputs(raw.tail(169),raw.tail(169),[end],include_eth)
        np.testing.assert_array_equal(full,last)
        np.testing.assert_array_equal(scale,last_scale)
        assert full.shape==(1,168,16 if include_eth else 10)


def test_future_mutation_cannot_change_sequence_inputs():
    raw=candles()
    end=raw.open_time.iloc[300]
    before,scale=sequence_inputs(raw,raw,[end],True)
    changed=raw.copy()
    changed.loc[301:,['open_price','high_price','low_price','close_price']]*=3
    after,new_scale=sequence_inputs(changed,changed,[end],True)
    np.testing.assert_array_equal(before,after)
    np.testing.assert_array_equal(scale,new_scale)


def test_gap_cannot_be_silently_padded():
    raw=candles()
    with pytest.raises(ValueError,match='gaps'):
        sequence_inputs(raw,raw.drop(index=400),[raw.open_time.iloc[-1]],True)


@pytest.mark.skipif(importlib.util.find_spec('torch') is None,reason='Optional sequence research dependency')
@pytest.mark.parametrize('architecture',['tcn','lstm'])
def test_cpu_network_shape_and_state_reload(architecture):
    # Match production research isolation: do not mix HiGHS and Torch native pools
    # in one pytest process on macOS (the combination can hang in convolution).
    program='''
import sys
import numpy as np
import torch
from pipeline.decision.hourly_sequence import make_network
torch.set_num_threads(2)
torch.set_num_interop_threads(1)
model=make_network(10,sys.argv[1])
x=torch.randn(3,168,10)
np.testing.assert_array_equal(model(x).detach().numpy(),np.zeros(3))
loss=(model(x)-torch.tensor([.1,-.2,.3])).abs().mean()
loss.backward()
assert model.head.bias.grad is not None
reloaded=make_network(10,sys.argv[1])
reloaded.load_state_dict(model.state_dict())
torch.testing.assert_close(model(x),reloaded(x),rtol=0,atol=0)
'''
    subprocess.run([sys.executable,'-c',program,architecture],check=True,timeout=30)
