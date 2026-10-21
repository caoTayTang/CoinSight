"""Historical futures positioning with an explicit one-hour information delay."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import io
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
import zipfile

import numpy as np
import pandas as pd

from pipeline.decision.hourly_features import prepare_grid
from pipeline.decision.hourly_future import digest, seal

FIELDS = ['sum_open_interest', 'sum_open_interest_value', 'count_toptrader_long_short_ratio',
          'sum_toptrader_long_short_ratio', 'count_long_short_ratio', 'sum_taker_long_short_vol_ratio']


def build_positioning(btc, metrics, delay_minutes=60):
    """Snapshot predates forecast cutoff by an explicit >=10-minute margin."""
    if delay_minutes not in (10,60):
        raise ValueError('Only preregistered 10 or 60 minute delays are supported')
    _, spot, _ = prepare_grid(btc)
    metrics = metrics.copy().sort_values('create_time')
    metrics['create_time'] = pd.to_datetime(metrics.create_time, utc=True)
    if metrics.create_time.isna().any():
        raise ValueError('Invalid metrics timestamp')
    if metrics.create_time.duplicated().any():
        duplicated = metrics[metrics.create_time.duplicated(keep=False)]
        if duplicated.groupby('create_time')[FIELDS].nunique(dropna=False).gt(1).any().any():
            raise ValueError('Conflicting metrics at the same timestamp')
        metrics = metrics.drop_duplicates('create_time')
    for column in FIELDS:
        metrics[column] = pd.to_numeric(metrics[column], errors='coerce')
        metrics[column] = metrics[column].where(np.isfinite(metrics[column]) & metrics[column].gt(0))
    decision=pd.DataFrame({'open_time':spot.index,
                          'latest_allowed_time':spot.index+pd.Timedelta(hours=1)-pd.Timedelta(minutes=delay_minutes)})
    aligned = pd.merge_asof(decision, metrics,
                            left_on='latest_allowed_time', right_on='create_time', direction='backward',
                            tolerance=pd.Timedelta(hours=2))
    aligned.index = spot.index
    result = pd.DataFrame(index=spot.index)
    result['positioning_age_hours'] = (aligned.open_time+pd.Timedelta(hours=1)-aligned.create_time).dt.total_seconds()/3600
    result['positioning_available'] = aligned.create_time.notna().astype(float)
    oi = np.log(aligned.sum_open_interest)
    result['oi_log_contracts'] = oi
    result['oi_log_usd'] = np.log(aligned.sum_open_interest_value)
    for window in (1, 6, 24):
        result[f'oi_change_{window}'] = oi-oi.shift(window)
    mean = oi.rolling(24, min_periods=24).mean()
    std = oi.rolling(24, min_periods=24).std(ddof=0)
    result['oi_z_24'] = ((oi-mean)/std.where(std.ne(0))).where(std.ne(0),0).where(mean.notna())
    for source,name in [('count_toptrader_long_short_ratio','top_accounts'),
                        ('sum_toptrader_long_short_ratio','top_positions'),
                        ('count_long_short_ratio','all_accounts'),
                        ('sum_taker_long_short_vol_ratio','taker_ratio')]:
        value = np.log(aligned[source])
        result[f'{name}_log_ratio'] = value
        result[f'{name}_change_1'] = value-value.shift(1)
        result[f'{name}_change_24'] = value-value.shift(24)
    result['positioning_top_all_spread'] = result.top_accounts_log_ratio-result.all_accounts_log_ratio
    result['positioning_accounts_positions_spread'] = result.top_accounts_log_ratio-result.top_positions_log_ratio
    price_return = np.log(spot.close_price/spot.close_price.shift(1))
    result['oi_price_direction_interaction'] = result.oi_change_1*np.sign(price_return)
    return result.replace([np.inf,-np.inf],np.nan)


def load_positioning(output, cache, start='2023-12-30', end='2025-12-31'):
    output,cache = Path(output),Path(cache)
    cache.mkdir(parents=True,exist_ok=True)
    days = pd.date_range(start,end,freq='D').strftime('%Y-%m-%d').tolist()
    def fetch(url):
        for attempt in range(3):
            try:
                with urlopen(url,timeout=20) as response:
                    return response.read()
            except HTTPError as error:
                if error.code == 404:
                    raise
                if attempt == 2:
                    raise
            except (URLError,TimeoutError):
                if attempt == 2:
                    raise
            time.sleep(.3*(attempt+1))
    def read(day):
        filename = f'BTCUSDT-metrics-{day}.zip'
        url = f'https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/{filename}'
        path,checksum = cache/filename,cache/(filename+'.CHECKSUM')
        try:
            if not checksum.exists():
                content=fetch(url+'.CHECKSUM')
                temporary=checksum.with_suffix('.pending')
                temporary.write_bytes(content)
                temporary.replace(checksum)
            expected=checksum.read_text().split()[0]
            if not path.exists():
                content=fetch(url)
                if digest(content)!=expected:
                    raise ValueError(f'Metrics checksum mismatch: {day}')
                temporary=path.with_suffix('.pending')
                temporary.write_bytes(content)
                temporary.replace(path)
            if digest(path.read_bytes())!=expected:
                raise ValueError(f'Metrics cache changed: {day}')
        except HTTPError as error:
            if error.code==404:
                return None,dict(day=day,url=url,status='missing_404')
            raise
        with zipfile.ZipFile(path) as archive:
            names=[n for n in archive.namelist() if n.endswith('.csv')]
            if len(names)!=1:
                raise ValueError('Expected one metrics CSV')
            frame=pd.read_csv(io.BytesIO(archive.read(names[0])))
        if set(['create_time','symbol',*FIELDS])-set(frame):
            raise ValueError('Unexpected positioning schema')
        frame['create_time']=pd.to_datetime(frame.create_time,utc=True)
        begin=pd.Timestamp(day,tz='UTC')
        if not frame.symbol.eq('BTCUSDT').all() or not frame.create_time.between(begin,begin+pd.Timedelta(days=1)).all():
            raise ValueError('Unexpected positioning symbol or date')
        return frame,dict(day=day,url=url,status='verified',sha256=expected,path=str(path.resolve()),rows=len(frame))
    frames,manifest=[],[]
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures=[executor.submit(read,day) for day in days]
        for i,handle in enumerate(as_completed(futures),1):
            frame,item=handle.result()
            if frame is not None:
                frames.append(frame)
            manifest.append(item)
            if i%100==0 or i==len(days):
                print(f'Positioning sources checked {i}/{len(days)}',flush=True)
    manifest.sort(key=lambda row:row['day'])
    seal(output/'positioning_sources.json',dict(checked_at=datetime.now(timezone.utc).isoformat(),files=manifest))
    if not frames:
        raise ValueError('No positioning history available')
    frame=pd.concat(frames,ignore_index=True).sort_values('create_time')
    if frame.create_time.ge(pd.Timestamp('2026-01-01',tz='UTC')).any():
        raise ValueError('Positioning test data forbidden')
    return frame
