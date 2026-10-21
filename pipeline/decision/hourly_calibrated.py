"""Inference for a frozen local research ensemble; not a production publication path."""
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from pipeline.decision.hourly_cross_asset import build_cross_inputs
from pipeline.decision.hourly_engineering import build_experimental_inputs
from pipeline.decision.hourly_future import digest,unseal


def predict_ensemble(bundle,btc,eth,forecast_cutoff):
    bundle=Path(bundle)
    spec=unseal(bundle/'ensemble.json')
    cutoff=pd.Timestamp(forecast_cutoff)
    if cutoff.tzinfo is None or cutoff!=cutoff.floor('h'):
        raise ValueError('Forecast cutoff must be an aligned timezone-aware hour')
    cutoff=cutoff.tz_convert('UTC')
    frames=[]
    for name,raw in [('BTC',btc),('ETH',eth)]:
        frame=raw.copy()
        frame['open_time']=pd.to_datetime(frame.open_time,utc=True)
        frame=frame.sort_values('open_time')
        expected=pd.date_range(cutoff-pd.Timedelta(hours=169),periods=169,freq='h',tz='UTC')
        if len(frame)!=169 or not pd.DatetimeIndex(frame.open_time).equals(expected):
            raise ValueError(f'{name}: need exactly 169 closed candles before forecast cutoff')
        frames.append(frame)
    btc,eth=frames
    compact=build_experimental_inputs(btc)['compact'].iloc[[-1]]
    features={'compact':compact,'eth':pd.concat([compact,build_cross_inputs(btc,eth).iloc[[-1]]],axis=1)}
    total=0.
    for member in spec['members']:
        path=bundle/member['path']
        if digest(path.read_bytes())!=member['model_sha256']:
            raise ValueError('Research ensemble member hash mismatch')
        frame=features[member['feature_set']]
        if list(frame.columns)!=member['features'] or frame.isna().any().any():
            raise ValueError('Incomplete or incompatible research ensemble input')
        model=joblib.load(path)
        predicted=float(model.predict(frame,thread_count=2)[0])/member['target_divisor']
        total+=member['coefficient']*predicted
    if not np.isfinite(total):
        raise ValueError('Non-finite ensemble forecast')
    return total
