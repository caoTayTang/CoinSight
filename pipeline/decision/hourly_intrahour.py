"""Closed 5-minute BTC candles summarized inside their own completed hour."""
from concurrent.futures import ThreadPoolExecutor
import io
from pathlib import Path
from urllib.request import urlopen
import zipfile

import numpy as np
import pandas as pd

from pipeline.decision.hourly_future import digest, seal


def build_intrahour(frame):
    frame = frame.copy()
    frame['open_time'] = pd.to_datetime(frame.open_time, utc=True)
    if frame.open_time.duplicated().any() or not frame.open_time.eq(frame.open_time.dt.floor('5min')).all():
        raise ValueError('Duplicate or unaligned 5-minute candle')
    frame = frame.sort_values('open_time')
    numeric = ['open_price', 'high_price', 'low_price', 'close_price', 'volume_quote', 'trade_count', 'taker_buy_quote']
    frame[numeric] = frame[numeric].astype(float)
    o, h, l, c, v, trades, buy = (frame[k] for k in numeric)
    valid = (np.isfinite(frame[numeric]).all(axis=1) & o.gt(0) & c.gt(0) & l.gt(0)
             & h.ge(frame[['open_price', 'low_price', 'close_price']].max(axis=1))
             & l.le(frame[['open_price', 'high_price', 'close_price']].min(axis=1))
             & v.ge(0) & trades.ge(0) & trades.eq(np.floor(trades)) & buy.ge(0) & buy.le(v+1e-8))
    frame['valid'] = valid
    frame['hour'] = frame.open_time.dt.floor('h')
    frame['slot'] = frame.open_time.dt.minute//5
    results = []
    for hour, group in frame.groupby('hour', sort=True):
        if len(group) != 12 or not group.valid.all() or list(group.slot) != list(range(12)):
            continue  # Leave this hour missing; caller must not silently drop validation.
        o, h, l, c, v, n, b = (group[k].to_numpy() for k in numeric)
        returns = np.log(c/o)
        volume = v.sum()
        row = {'open_time': hour, 'source_open': o[0], 'source_close': c[-1],
               'source_high': h.max(), 'source_low': l.min(), 'source_volume_quote': volume,
               'source_trade_count': n.sum()}
        for i in range(12):
            row[f'intra_return_slot_{i:02d}'] = returns[i]
        row.update(intra_last15_return=np.log(c[-1]/o[-3]), intra_last30_return=np.log(c[-1]/o[-6]),
                   intra_first30_return=np.log(c[5]/o[0]), intra_realized_vol=float(np.sqrt(np.sum(returns**2))),
                   intra_late_volume_fraction=float(v[-3:].sum()/volume) if volume else 0,
                   intra_taker_imbalance=float(2*b.sum()/volume-1) if volume else 0,
                   intra_late_taker_imbalance=float(2*b[-3:].sum()/v[-3:].sum()-1) if v[-3:].sum() else 0,
                   intra_reversal=float(returns[-3:].sum()-returns[:3].sum()))
        results.append(row)
    return pd.DataFrame(results).set_index('open_time').sort_index()


def load_intrahour(output, btc):
    output = Path(output)
    cache = output/'btc_5m_archives'
    cache.mkdir(exist_ok=True)
    months = pd.period_range('2023-12', '2025-12', freq='M').astype(str)
    def load_month(month):
        filename = f'BTCUSDT-5m-{month}.zip'
        url = f'https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/5m/{filename}'
        path = cache/filename
        checksum = cache/(filename+'.CHECKSUM')
        if not checksum.exists():
            with urlopen(url+'.CHECKSUM', timeout=30) as response:
                checksum.write_bytes(response.read())
        expected = checksum.read_text().split()[0]
        if not path.exists():
            with urlopen(url, timeout=30) as response:
                data = response.read()
            if digest(data) != expected:
                raise ValueError('5m download checksum mismatch')
            path.write_bytes(data)
        if digest(path.read_bytes()) != expected:
            raise ValueError('5m archive checksum mismatch')
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.endswith('.csv')]
            if len(names) != 1:
                raise ValueError('Expected one 5m CSV')
            frame = pd.read_csv(io.BytesIO(archive.read(names[0])), header=None)
        if frame.shape[1] != 12:
            raise ValueError('Invalid 5m schema')
        stamp = frame[0].astype('int64')
        stamp_ms = stamp.where(stamp.lt(10**14), stamp//1000)
        result = pd.DataFrame(dict(open_time=pd.to_datetime(stamp_ms, unit='ms', utc=True),
            open_price=frame[1], high_price=frame[2], low_price=frame[3], close_price=frame[4],
            volume_quote=frame[7], trade_count=frame[8], taker_buy_quote=frame[10]))
        if not result.open_time.dt.strftime('%Y-%m').eq(month).all():
            raise ValueError('Unexpected timestamp in 5m month')
        return result, dict(url=url, sha256=expected)
    with ThreadPoolExecutor(max_workers=4) as executor:
        loaded = list(executor.map(load_month, months))
    raw = pd.concat([r[0] for r in loaded], ignore_index=True)
    if raw.open_time.ge(pd.Timestamp('2026-01-01', tz='UTC')).any():
        raise ValueError('Test 5m candles forbidden')
    seal(output/'intrahour_sources.json', [r[1] for r in loaded])
    features = build_intrahour(raw)
    joined = btc.merge(features, left_on='open_time', right_index=True, how='inner', validate='one_to_one')
    for left, right in [('open_price', 'source_open'), ('high_price', 'source_high'),
                        ('low_price', 'source_low'), ('close_price', 'source_close'),
                        ('volume_quote', 'source_volume_quote'), ('trade_count', 'source_trade_count')]:
        np.testing.assert_allclose(joined[left], joined[right], rtol=1e-12,
                                   atol=.005001 if left == 'volume_quote' else 1e-8)
    # Demonstrate invariance to future candles before allowing any fit.
    cutoff = pd.Timestamp('2025-06-01', tz='UTC')
    pd.testing.assert_frame_equal(features.loc[:cutoff], build_intrahour(raw[raw.open_time.lt(cutoff+pd.Timedelta(hours=1))]))
    features = features[[k for k in features if k.startswith('intra_')]]
    features.to_csv(output/'intrahour_features.csv', float_format='%.17g')
    return features
