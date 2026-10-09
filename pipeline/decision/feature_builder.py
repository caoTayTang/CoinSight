"""Read warehouse candles and build leakage-safe daily model features."""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.settings import DATABASE_URL, DSS

SYMBOLS = tuple(DSS["symbols"])
NUMERIC = ("return_1d", "return_7d", "range_pct", "volume_change", "hourly_range")

def load_features(database_url: str = DATABASE_URL) -> pd.DataFrame:
    """One row per symbol/day; hourly feature uses that same closed UTC day."""
    import psycopg2

    with psycopg2.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute("""
            select a.symbol, d.full_date as day, f.close_price::float as close,
                   f.high_price::float as high, f.low_price::float as low,
                   f.volume_quote::float as volume_quote,
                   h.hourly_range, f.batch_id
            from dw.fact_ohlcv_daily f
            join dw.dim_asset a on a.asset_key = f.asset_key
            join dw.dim_date d on d.date_key = f.date_key
            join dw.dim_source s on s.source_key = f.source_key
            left join (
                select asset_key, date_key, source_key,
                       avg((high_price - low_price) / nullif(open_price, 0))::float
                           as hourly_range
                from dw.fact_ohlcv_hourly
                group by asset_key, date_key, source_key
                having count(*) = 24
            ) h on h.asset_key = f.asset_key and h.date_key = f.date_key
                and h.source_key = f.source_key
            where s.source_code = 'binance' and a.symbol = any(%s)
            order by a.symbol, d.full_date
        """, (list(SYMBOLS),))
        frame = pd.DataFrame(cursor.fetchall(), columns=[item.name for item in cursor.description])
    if frame.empty:
        return frame
    frame["day"] = pd.to_datetime(frame["day"])
    grouped = frame.groupby("symbol", sort=False)
    frame["return_1d"] = grouped["close"].pct_change(1)
    frame["return_7d"] = grouped["close"].pct_change(7)
    frame["range_pct"] = (frame["high"] - frame["low"]) / frame["close"]
    frame["volume_change"] = grouped["volume_quote"].pct_change(1)
    frame["next_close"] = grouped["close"].shift(-1)
    frame["next_day"] = grouped["day"].shift(-1)
    frame["target"] = (frame["next_close"] > frame["close"]).astype(int)
    frame = frame.replace([np.inf, -np.inf], np.nan)
    return frame


def labelled_rows(frame: pd.DataFrame) -> pd.DataFrame:
    rows = frame.dropna(subset=[*NUMERIC, "next_close", "next_day"]).copy()
    # Do not label over gaps: the horizon is exactly one UTC day.
    return rows[(rows["next_day"] - rows["day"]) == pd.Timedelta(days=1)]
