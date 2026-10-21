"""Archived futures depth bands, quality checked against already closed spot prices."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import io
import threading
import time
from urllib.error import HTTPError,URLError
from urllib.request import urlopen
import zipfile

import numpy as np
import pandas as pd

from pipeline.decision.hourly_future import digest,seal

BANDS=(-5.,-2.,-1.,1.,2.,5.)


def summarize_day(raw,reference,day):
    raw=raw.copy()
    stamp=raw['timestamp']
    if pd.api.types.is_numeric_dtype(stamp) or stamp.astype(str).str.isdigit().all():
        values=stamp.astype('int64')
        unit='s' if values.max()<10**11 else ('ms' if values.max()<10**14 else 'us')
        raw['timestamp']=pd.to_datetime(values,unit=unit,utc=True)
    else:
        raw['timestamp']=pd.to_datetime(stamp,utc=True)
    start=pd.Timestamp(day,tz='UTC')
    if not raw.timestamp.between(start,start+pd.Timedelta(days=1),inclusive='left').all():
        raise ValueError('Unexpected book depth date')
    for field in ('percentage','depth','notional'):
        raw[field]=pd.to_numeric(raw[field],errors='coerce')
    raw=raw[raw.percentage.isin(BANDS)].copy()
    original_rows=len(raw)
    conflicts=raw.groupby(['timestamp','percentage'])[['depth','notional']].nunique(dropna=False).gt(1).any(axis=1)
    bad_times=conflicts[conflicts].index.get_level_values('timestamp').unique()
    raw=raw[~raw.timestamp.isin(bad_times)].drop_duplicates(['timestamp','percentage'])
    valid=np.isfinite(raw[['depth','notional']]).all(axis=1)&raw.depth.gt(0)&raw.notional.gt(0)
    raw.loc[~valid,['depth','notional']]=np.nan
    depth=raw.pivot(index='timestamp',columns='percentage',values='depth').reindex(columns=BANDS)
    notional=raw.pivot(index='timestamp',columns='percentage',values='notional').reindex(columns=BANDS)
    timestamps=depth.index
    observed=pd.merge_asof(pd.DataFrame({'timestamp':timestamps}),reference,
                          left_on='timestamp',right_on='available_time',direction='backward',
                          tolerance=pd.Timedelta(hours=2))
    observed.index=timestamps
    implied=notional/depth
    # Band-weighted prices can differ from mid, but gross errors exceed the 20% margin.
    ratios=implied.div(observed.close_price,axis=0)
    healthy=depth.notna().all(axis=1)&notional.notna().all(axis=1)&ratios.ge(.8).all(axis=1)&ratios.le(1.2).all(axis=1)
    features=pd.DataFrame(index=timestamps)
    for band in (1.,2.,5.):
        name=str(int(band))
        features['book_qty_imbalance_'+name]=(depth[-band]-depth[band])/(depth[-band]+depth[band])
        features['book_notional_imbalance_'+name]=(notional[-band]-notional[band])/(notional[-band]+notional[band])
    for band in (1.,5.):
        features['book_log_notional_'+str(int(band))]=np.log1p(notional[-band]+notional[band])
    features['book_bid_depth_slope']=np.log(depth[-5.]/depth[-1.])
    features['book_ask_depth_slope']=np.log(depth[5.]/depth[1.])
    features['book_band_price_spread']=np.log(implied[1.]/implied[-1.])
    features=features.where(healthy).replace([np.inf,-np.inf],np.nan)
    # A bin ending at t contains events <=t; counts permit exact cross-day recombination.
    sums=features.resample('5min',label='right',closed='right').sum(min_count=1)
    counts=features.resample('5min',label='right',closed='right').count()
    result=pd.concat([sums.add_prefix('sum__'),counts.add_prefix('count__')],axis=1)
    quality=dict(day=day,raw_band_rows=original_rows,conflicting_timestamps=len(bad_times),
                 snapshot_count=len(healthy),healthy_snapshots=int(healthy.sum()),invalid_snapshots=int((~healthy).sum()))
    return result,quality


def book_inputs(btc,aggregates,delay_minutes=10):
    if delay_minutes not in (10,60):
        raise ValueError('Only preregistered latency margins are supported')
    aggregates=aggregates.groupby(level=0).sum(min_count=1).sort_index()
    names=[c.removeprefix('sum__') for c in aggregates if c.startswith('sum__')]
    values=pd.DataFrame({name:aggregates['sum__'+name]/aggregates['count__'+name].where(aggregates['count__'+name].gt(0))
                         for name in names},index=aggregates.index)
    values=values.asfreq('5min')
    for name in ['book_qty_imbalance_1','book_qty_imbalance_5','book_log_notional_1']:
        values[name+'_mean_1h']=values[name].rolling(12,min_periods=12).mean()
        values[name+'_std_1h']=values[name].rolling(12,min_periods=12).std(ddof=0)
        values[name+'_change_1h']=values[name]-values[name].shift(12)
    values.index.name='book_time'
    # An unhealthy bin is missing information; do not forward-fill its fields.
    raw=btc.copy().sort_values('open_time')
    left=pd.DataFrame({'open_time':pd.to_datetime(raw.open_time,utc=True)})
    left['allowed_time']=left.open_time+pd.Timedelta(hours=1)-pd.Timedelta(minutes=delay_minutes)
    aligned=pd.merge_asof(left,values.reset_index(),left_on='allowed_time',right_on='book_time',
                         direction='backward',tolerance=pd.Timedelta(minutes=15))
    aligned.index=pd.DatetimeIndex(left.open_time)
    result=aligned[list(values.columns)].copy()
    result['book_available']=result.book_qty_imbalance_1.notna().astype(float)
    result['book_age_minutes']=(aligned.open_time+pd.Timedelta(hours=1)-aligned.book_time).dt.total_seconds()/60
    return result


def load_bookdepth(output,cache,btc,max_bytes=512*1024*1024):
    output,cache=Path(output),Path(cache)
    cache.mkdir(parents=True,exist_ok=True)
    reference=btc[['open_time','close_price']].copy()
    reference['available_time']=pd.to_datetime(reference.open_time,utc=True)+pd.Timedelta(hours=1)
    reference=reference[['available_time','close_price']].sort_values('available_time')
    used=0;guard=threading.Lock()
    days=pd.date_range('2023-12-30','2025-12-31',freq='D').strftime('%Y-%m-%d').tolist()
    def fetch(url):
        for attempt in range(3):
            try:
                with urlopen(url,timeout=20) as response:
                    return response.read()
            except HTTPError as error:
                if error.code==404 or attempt==2: raise
                time.sleep(.3*(attempt+1))
            except (URLError,TimeoutError):
                if attempt==2: raise
                time.sleep(.3*(attempt+1))
    def load(day):
        nonlocal used
        name=f'BTCUSDT-bookDepth-{day}.zip'
        path,checksum=cache/name,cache/(name+'.CHECKSUM')
        url=f'https://data.binance.vision/data/futures/um/daily/bookDepth/BTCUSDT/{name}'
        try:
            if not checksum.exists(): checksum.write_bytes(fetch(url+'.CHECKSUM'))
            expected=checksum.read_text().split()[0]
        except HTTPError as error:
            if error.code!=404: raise
            return None,dict(url=url,status='missing_404',day=day,bytes=0)
        if path.exists():
            size=path.stat().st_size
            with guard:
                used+=size
                if used>max_bytes: raise ValueError('Book depth dataset exceeds 512 MiB study limit')
        else:
            content=fetch(url)
            if len(content)>5*1024*1024: raise ValueError('Unexpectedly large daily book archive')
            if digest(content)!=expected: raise ValueError('Book depth download checksum mismatch')
            with guard:
                used+=len(content)
                if used>max_bytes: raise ValueError('Book depth dataset exceeds 512 MiB study limit')
            temporary=path.with_suffix('.pending')
            temporary.write_bytes(content);temporary.replace(path)
        if digest(path.read_bytes())!=expected: raise ValueError('Book depth archive changed')
        with zipfile.ZipFile(path) as archive:
            names=[n for n in archive.namelist() if n.endswith('.csv')]
            if len(names)!=1: raise ValueError('Expected one book depth CSV')
            raw=pd.read_csv(archive.open(names[0]))
        if set(raw.columns)!={'timestamp','percentage','depth','notional'}:
            raise ValueError('Unexpected book depth schema')
        aggregate,quality=summarize_day(raw,reference,day)
        return aggregate,dict(url=url,status='verified',path=str(path.resolve()),sha256=expected,bytes=path.stat().st_size,**quality)
    chunks=[];manifest=[]
    with ThreadPoolExecutor(max_workers=4) as executor:
        handles=[executor.submit(load,day) for day in days]
        for i,handle in enumerate(as_completed(handles),1):
            chunk,entry=handle.result()
            if chunk is not None: chunks.append(chunk)
            manifest.append(entry)
            if i%100==0 or i==len(days):
                print(f'Book depth sources checked {i}/{len(days)}; compressed bytes={used}',flush=True)
    seal(output/'bookdepth_sources.json',sorted(manifest,key=lambda r:r['url']))
    if not chunks: raise ValueError('No book depth history available')
    aggregate=pd.concat(chunks).sort_index()
    aggregate.to_csv(output/'bookdepth_5m_aggregates.csv',float_format='%.17g')
    return aggregate
