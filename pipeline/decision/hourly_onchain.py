"""Delayed daily Coin Metrics network features, with retrospective revision caveat."""
import numpy as np
import pandas as pd

NETWORK=('AdrActCnt','AdrBalCnt','BlkCnt','FeeTotNtv','HashRate','IssTotNtv','TxCnt','TxTfrCnt')
FLOWS=('FlowInExNtv','FlowOutExNtv','SplyExNtv')


def onchain_inputs(daily,cutoffs,delay_hours=48,flows=False):
    if delay_hours<48: raise ValueError('Need at least 48h from start of daily bucket')
    d=daily.copy();d['time']=pd.to_datetime(d.time,utc=True)
    # Entire 2026 source rows are excluded before feature construction.
    d=d[d.time.lt(pd.Timestamp('2026-01-01',tz='UTC'))].sort_values('time').set_index('time')
    if d.index.duplicated().any() or not d.index.equals(d.index.floor('D')): raise ValueError('Invalid daily grid')
    d=d.reindex(pd.date_range(d.index.min(),d.index.max(),freq='D'))
    cols=NETWORK+(FLOWS if flows else ())
    x=pd.DataFrame(index=d.index)
    for col in cols:
        v=pd.to_numeric(d[col],errors='raise')
        if (v.dropna()<0).any(): raise ValueError('Negative count/flow')
        z=np.log1p(v)
        x[f'chain_{col}_log']=z
        x[f'chain_{col}_change1']=z-z.shift(1)
        x[f'chain_{col}_change7']=z-z.shift(7)
        x[f'chain_{col}_relative30']=z-z.rolling(30,min_periods=24).mean()
    # Respect provider completion times if later than conservative bucket delay.
    completion=pd.to_datetime(d.AssetEODCompletionTime,unit='s',utc=True)
    available=pd.Series(d.index+pd.Timedelta(hours=delay_hours),index=d.index)
    available=available.where(completion.isna()|(available>=completion),completion)
    right=x.assign(available_at=available).dropna(subset=['available_at']).sort_values('available_at')
    cutoff=pd.DatetimeIndex(cutoffs)
    if cutoff.tz is None: raise ValueError('Need timezone-aware cutoffs')
    left=pd.DataFrame({'cutoff':cutoff,'position':range(len(cutoff))}).sort_values('cutoff')
    merged=pd.merge_asof(left,right,left_on='cutoff',right_on='available_at',direction='backward',tolerance=pd.Timedelta(hours=30))
    out=merged.sort_values('position')[list(x.columns)]
    out.index=getattr(cutoffs,'index',pd.RangeIndex(len(cutoff)))
    return out
