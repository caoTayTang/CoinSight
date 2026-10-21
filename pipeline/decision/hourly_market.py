"""Closed-candle crypto basket context; a fixed auxiliary asset universe."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import time
from urllib.error import HTTPError,URLError
from urllib.request import urlopen

import numpy as np
import pandas as pd

from pipeline.batch.binance_archive_format import parse_kline_csv,read_zip_csv
from pipeline.decision.hourly_cross_asset import build_cross_inputs
from pipeline.decision.hourly_future import digest,seal

MARKET_SYMBOLS=('BNB','SOL','XRP','DOGE','ADA','LTC')


def market_inputs(btc,assets):
    frames=[];returns={}
    for symbol,raw in sorted(assets.items()):
        frame=build_cross_inputs(btc,raw)
        frame=frame.rename(columns={c:c.replace('eth',symbol.lower()) for c in frame})
        frames.append(frame)
        returns[symbol]=frame[f'{symbol.lower()}_log_return_1']
    result=pd.concat(frames,axis=1)
    matrix=pd.DataFrame(returns)
    count=matrix.notna().sum(axis=1)
    enough=count.ge(3)
    result['basket_known_assets']=count
    result['basket_return_mean']=matrix.mean(axis=1).where(enough)
    result['basket_return_median']=matrix.median(axis=1).where(enough)
    result['basket_return_dispersion']=matrix.std(axis=1,ddof=0).where(enough)
    result['basket_breadth']=matrix.gt(0).sum(axis=1).div(count.where(count.ne(0))).where(enough)
    return result


def load_market_assets(output,cache):
    output,cache=Path(output),Path(cache)
    tasks=[(symbol,str(month)) for symbol in MARKET_SYMBOLS
           for month in pd.period_range('2022-12','2025-12',freq='M')]
    def fetch(url):
        for attempt in range(3):
            try:
                with urlopen(url,timeout=20) as response:
                    return response.read()
            except (HTTPError,URLError,TimeoutError):
                if attempt==2:
                    raise
                time.sleep(.3*(attempt+1))
    def load(task):
        symbol,month=task
        filename=f'{symbol}USDT-1h-{month}.zip'
        folder=cache/symbol
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/filename
        checksum=folder/(filename+'.CHECKSUM')
        url=f'https://data.binance.vision/data/spot/monthly/klines/{symbol}USDT/1h/{filename}'
        if not checksum.exists():
            checksum.write_bytes(fetch(url+'.CHECKSUM'))
        expected=checksum.read_text().split()[0]
        if not path.exists():
            data=fetch(url)
            if digest(data)!=expected:
                raise ValueError('Market download checksum mismatch')
            temporary=path.with_suffix('.pending')
            temporary.write_bytes(data)
            temporary.replace(path)
        if digest(path.read_bytes())!=expected:
            raise ValueError('Market archive changed')
        frame=pd.DataFrame(parse_kline_csv(read_zip_csv(path)))
        frame['open_time']=pd.to_datetime(frame.open_time,utc=True)
        if not frame.open_time.dt.strftime('%Y-%m').eq(month).all():
            raise ValueError('Market archive month mismatch')
        return symbol,frame,dict(symbol=symbol,url=url,path=str(path.resolve()),sha256=expected,rows=len(frame))
    results=[]
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures=[executor.submit(load,task) for task in tasks]
        for i,handle in enumerate(as_completed(futures),1):
            results.append(handle.result())
            if i%50==0 or i==len(tasks):
                print(f'Market sources checked {i}/{len(tasks)}',flush=True)
    seal(output/'market_sources.json',sorted([r[2] for r in results],key=lambda r:r['url']))
    assets={symbol:pd.concat([r[1] for r in results if r[0]==symbol],ignore_index=True).sort_values('open_time')
            for symbol in MARKET_SYMBOLS}
    for frame in assets.values():
        if frame.open_time.duplicated().any() or frame.open_time.ge(pd.Timestamp('2026-01-01',tz='UTC')).any():
            raise ValueError('Duplicate or test market candle')
    return assets
