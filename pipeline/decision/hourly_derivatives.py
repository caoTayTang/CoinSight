"""Causal futures/spot basis and previously settled funding features."""
from concurrent.futures import ThreadPoolExecutor
import io
from pathlib import Path
from urllib.request import urlopen
import zipfile

import numpy as np
import pandas as pd

from pipeline.decision.hourly_features import prepare_grid
from pipeline.decision.hourly_future import digest, seal


def build_derivatives(btc, futures, funding):
    _,spot,_=prepare_grid(btc)
    _,future,_=prepare_grid(futures)
    future=future.reindex(spot.index)
    basis=np.log(future.close_price/spot.close_price)
    result=pd.DataFrame(index=spot.index)
    result['fut_basis']=basis
    result['fut_basis_change_1']=basis.diff()
    result['fut_basis_mean_24']=basis.rolling(24,min_periods=24).mean()
    result['fut_basis_deviation_24']=basis-result.fut_basis_mean_24
    result['fut_basis_std_24']=basis.rolling(24,min_periods=24).std(ddof=0)
    result['fut_momentum_6']=np.log(future.close_price/future.close_price.shift(6))
    result['fut_volume_spot_log_ratio']=np.log1p(future.volume_quote)-np.log1p(spot.volume_quote)
    volume_mean=future.volume_quote.rolling(24,min_periods=24).mean()
    result['fut_relative_volume_24']=(future.volume_quote/volume_mean.where(volume_mean.ne(0))).where(volume_mean.ne(0),0).where(volume_mean.notna())
    raw=futures.set_index('open_time').reindex(spot.index)
    buy=raw.taker_buy_quote.astype(float)
    volume=future.volume_quote
    if ((buy<0)|(buy>volume+1e-8)).any():
        raise ValueError('Invalid futures taker buy volume')
    result['fut_taker_imbalance']=(2*buy/volume.where(volume.ne(0))-1).where(volume.ne(0),0).where(volume.notna())
    funding=funding.copy().sort_values('calc_time')
    if funding.calc_time.duplicated().any() or not np.isfinite(funding.last_funding_rate.astype(float)).all():
        raise ValueError('Invalid funding history')
    funding['rate_change']=funding.last_funding_rate.diff()
    # input open is one hour BEFORE prediction cutoff: funding receives >=1h delay.
    lookup=pd.merge_asof(pd.DataFrame({'open_time':spot.index}),funding,left_on='open_time',right_on='calc_time',
                         direction='backward',tolerance=pd.Timedelta(hours=16))
    lookup.index=spot.index
    result['funding_settled_lagged']=lookup.last_funding_rate
    result['funding_settled_change']=lookup.rate_change
    result['funding_age_hours']=(lookup.open_time-lookup.calc_time).dt.total_seconds()/3600
    return result.replace([np.inf,-np.inf],np.nan)


def load_derivatives(output):
    output=Path(output)
    cache=output/'derivatives_archives'
    cache.mkdir(exist_ok=True)
    tasks=[(kind,month) for kind in ('klines','fundingRate')
           for month in pd.period_range('2023-12','2025-12',freq='M').astype(str)]
    def read(task):
        kind,month=task
        name=f'BTCUSDT-1h-{month}.zip' if kind=='klines' else f'BTCUSDT-fundingRate-{month}.zip'
        segment='klines/BTCUSDT/1h' if kind=='klines' else 'fundingRate/BTCUSDT'
        url=f'https://data.binance.vision/data/futures/um/monthly/{segment}/{name}'
        path=cache/(kind+'-'+name)
        with urlopen(url+'.CHECKSUM',timeout=30) as response:
            expected=response.read().decode().split()[0]
        if not path.exists():
            with urlopen(url,timeout=30) as response:
                content=response.read()
            if digest(content)!=expected:
                raise ValueError('Derivative download checksum mismatch')
            path.write_bytes(content)
        if digest(path.read_bytes())!=expected:
            raise ValueError('Derivative cache checksum mismatch')
        with zipfile.ZipFile(path) as archive:
            names=[n for n in archive.namelist() if n.endswith('.csv')]
            if len(names)!=1:
                raise ValueError('Expected one derivative CSV')
            data=pd.read_csv(io.BytesIO(archive.read(names[0])))
        if kind=='klines':
            frame=data.rename(columns={'open':'open_price','high':'high_price','low':'low_price',
                'close':'close_price','quote_volume':'volume_quote','count':'trade_count',
                'taker_buy_quote_volume':'taker_buy_quote'})
            frame['open_time']=pd.to_datetime(frame.open_time.astype('int64'),unit='ms',utc=True)
            stamp=frame.open_time
        else:
            frame=data
            frame['calc_time']=pd.to_datetime(frame.calc_time.astype('int64'),unit='ms',utc=True)
            frame['last_funding_rate']=frame.last_funding_rate.astype(float)
            stamp=frame.calc_time
        if not stamp.dt.strftime('%Y-%m').eq(month).all():
            raise ValueError('Unexpected derivative archive month')
        return kind,frame,dict(url=url,sha256=expected,path=str(path.relative_to(output)))
    with ThreadPoolExecutor(max_workers=4) as executor:
        results=list(executor.map(read,tasks))
    seal(output/'derivatives_sources.json',[r[2] for r in results])
    futures=pd.concat([r[1] for r in results if r[0]=='klines'],ignore_index=True)
    funding=pd.concat([r[1] for r in results if r[0]=='fundingRate'],ignore_index=True)
    if futures.open_time.ge(pd.Timestamp('2026-01-01',tz='UTC')).any() or funding.calc_time.ge(pd.Timestamp('2026-01-01',tz='UTC')).any():
        raise ValueError('Derivative test data forbidden')
    return futures,funding
