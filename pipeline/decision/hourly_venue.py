"""Causal cross-venue hourly inputs; BTC-USD / BTC-USDT basis includes quote effects."""
import numpy as np
import pandas as pd
from pipeline.decision.hourly_features import prepare_grid


def parse_coinbase(rows):
    if not isinstance(rows,list) or any(not isinstance(r,list) or len(r)!=6 for r in rows):
        raise ValueError('Invalid Coinbase candle response')
    frame=pd.DataFrame(rows,columns=['timestamp','low','high','open','close','volume'])
    frame=frame.astype(float)
    if not np.isfinite(frame.to_numpy()).all() or not frame.timestamp.mod(3600).eq(0).all():
        raise ValueError('Invalid Coinbase timestamp/value')
    if frame.timestamp.duplicated().any(): raise ValueError('Duplicate Coinbase timestamp')
    if not (frame[['low','high','open','close']].gt(0).all(axis=1)&frame.volume.ge(0)&
            frame.high.ge(frame[['low','open','close']].max(axis=1))&
            frame.low.le(frame[['high','open','close']].min(axis=1))).all():
        raise ValueError('Invalid Coinbase OHLCV')
    frame['open_time']=pd.to_datetime(frame.timestamp,unit='s',utc=True)
    return frame.drop(columns='timestamp').sort_values('open_time').reset_index(drop=True)


def venue_inputs(btc,coinbase,extra_lag=0):
    if extra_lag not in (0,1): raise ValueError('Only preplanned lags 0/1 supported')
    _,b,bv=prepare_grid(btc)
    c=coinbase.copy();c.open_time=pd.to_datetime(c.open_time,utc=True)
    if c.open_time.duplicated().any() or not c.open_time.eq(c.open_time.dt.floor('h')).all():
        raise ValueError('Invalid Coinbase grid')
    c=c.set_index('open_time').sort_index().reindex(b.index)
    valid=np.isfinite(c[['low','high','open','close','volume']]).all(axis=1)&c.close.gt(0)
    c=c.where(valid)
    r=np.log(c.close/c.close.shift(1));basis=np.log(c.close/b.close_price)
    x=pd.DataFrame(index=b.index)
    x['cb_return1']=r
    for w in (6,24,168): x[f'cb_momentum{w}']=np.log(c.close/c.close.shift(w))
    x['cb_volatility24']=r.rolling(24,min_periods=24).std(ddof=0)
    x['cb_range']=(c.high-c.low)/c.open
    volume=np.log1p(c.volume);sd=volume.rolling(168,min_periods=168).std(ddof=0)
    x['cb_volume_z168']=(volume-volume.rolling(168,min_periods=168).mean())/sd.replace(0,np.nan)
    x['venue_basis']=basis
    for w in (1,6,24): x[f'venue_basis_change{w}']=basis-basis.shift(w)
    x['venue_basis_center24']=basis-basis.rolling(24,min_periods=24).mean()
    x['venue_basis_center168']=basis-basis.rolling(168,min_periods=168).mean()
    full=(valid&bv).rolling(169,min_periods=169).sum().eq(169)
    return x.replace([np.inf,-np.inf],np.nan).where(full).shift(extra_lag)
