"""Read closed Binance candles from the data warehouse."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import pandas as pd

from pipeline.decision.types import utc_datetime
from pipeline.settings import DATABASE_URL


class HourlyCandleRepository:
    def __init__(self, database_url: str = DATABASE_URL, source_code: str = "binance"):
        self.database_url = database_url
        self.source_code = source_code

    def fetch_candles(
        self, symbol: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        import psycopg2

        start, end = utc_datetime(start), utc_datetime(end)
        if start >= end:
            raise ValueError("start must be before end")
        with psycopg2.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                select a.symbol, f.open_time,
                       f.open_price::float8 as open_price,
                       f.high_price::float8 as high_price,
                       f.low_price::float8 as low_price,
                       f.close_price::float8 as close_price,
                       f.volume_quote::float8 as volume_quote,
                       f.trade_count::bigint as trade_count,
                       f.batch_id, f.loaded_at
                from dw.fact_ohlcv_hourly f
                join dw.dim_asset a on a.asset_key = f.asset_key
                join dw.dim_source s on s.source_key = f.source_key
                where s.source_code = %s and a.symbol = %s
                  and f.open_time >= %s and f.open_time < %s
                order by f.open_time
                """,
                (self.source_code, symbol.upper(), start, end),
            )
            columns = [column.name for column in cursor.description]
            frame = pd.DataFrame(cursor.fetchall(), columns=columns)
        if not frame.empty:
            frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
            frame["loaded_at"] = pd.to_datetime(frame["loaded_at"], utc=True)
        return frame

    def fetch_candles_many(
        self, symbols: Sequence[str], start: datetime, end: datetime
    ) -> pd.DataFrame:
        """Fetch several symbol timelines in one consistent warehouse query."""
        import psycopg2

        resolved = sorted({str(symbol).upper() for symbol in symbols})
        start, end = utc_datetime(start), utc_datetime(end)
        if not resolved:
            raise ValueError("symbols must contain at least one symbol")
        if start >= end:
            raise ValueError("start must be before end")
        with psycopg2.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                select a.symbol, f.open_time,
                       f.open_price::float8 as open_price,
                       f.high_price::float8 as high_price,
                       f.low_price::float8 as low_price,
                       f.close_price::float8 as close_price,
                       f.volume_quote::float8 as volume_quote,
                       f.trade_count::bigint as trade_count,
                       f.batch_id, f.loaded_at
                from dw.fact_ohlcv_hourly f
                join dw.dim_asset a on a.asset_key = f.asset_key
                join dw.dim_source s on s.source_key = f.source_key
                where s.source_code = %s and upper(a.symbol) = any(%s)
                  and f.open_time >= %s and f.open_time < %s
                order by a.symbol, f.open_time
                """,
                (self.source_code, resolved, start, end),
            )
            columns = [column.name for column in cursor.description]
            frame = pd.DataFrame(cursor.fetchall(), columns=columns)
        if not frame.empty:
            frame["symbol"] = frame["symbol"].astype(str).str.upper()
            frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
            frame["loaded_at"] = pd.to_datetime(frame["loaded_at"], utc=True)
        return frame

    def fetch_coverage(
        self, symbols: Sequence[str], start: datetime, end: datetime
    ) -> pd.DataFrame:
        rows = []
        for symbol in symbols:
            candles = self.fetch_candles(symbol, start, end)
            rows.append({
                "symbol": symbol.upper(),
                "first_candle": None if candles.empty else candles.open_time.min(),
                "last_candle": None if candles.empty else candles.open_time.max(),
                "row_count": len(candles),
                "duplicate_count": int(candles.open_time.duplicated().sum()) if not candles.empty else 0,
            })
        return pd.DataFrame(rows)

    def fetch_source_batch_ids(
        self, symbol: str, start: datetime, end: datetime
    ) -> list[int]:
        import psycopg2

        with psycopg2.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                select distinct f.batch_id
                from dw.fact_ohlcv_hourly f
                join dw.dim_asset a on a.asset_key = f.asset_key
                join dw.dim_source s on s.source_key = f.source_key
                where s.source_code = %s and a.symbol = %s
                  and f.open_time >= %s and f.open_time < %s
                order by f.batch_id
                """,
                (self.source_code, symbol.upper(), utc_datetime(start), utc_datetime(end)),
            )
            return [int(row[0]) for row in cursor.fetchall()]


class DailyCandleRepository:
    """Read one row per UTC calendar day using the hourly column contract.

    ``open_time`` is the UTC start of the daily candle. Keeping the returned
    columns identical to the hourly repository lets snapshotting, sample
    indexing and model adapters remain frequency-agnostic.
    """

    def __init__(self, database_url: str = DATABASE_URL, source_code: str = "binance"):
        self.database_url = database_url
        self.source_code = source_code

    @staticmethod
    def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
        if not frame.empty:
            frame["symbol"] = frame["symbol"].astype(str).str.upper()
            frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
            frame["loaded_at"] = pd.to_datetime(frame["loaded_at"], utc=True)
        return frame

    def fetch_candles(
        self, symbol: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        frame = self.fetch_candles_many((symbol,), start, end)
        return frame.reset_index(drop=True)

    def fetch_candles_many(
        self, symbols: Sequence[str], start: datetime, end: datetime
    ) -> pd.DataFrame:
        import psycopg2

        resolved = sorted({str(symbol).upper() for symbol in symbols})
        start, end = utc_datetime(start), utc_datetime(end)
        if not resolved:
            raise ValueError("symbols must contain at least one symbol")
        if start >= end:
            raise ValueError("start must be before end")
        with psycopg2.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                select a.symbol, d.full_date::timestamptz as open_time,
                       f.open_price::float8 as open_price,
                       f.high_price::float8 as high_price,
                       f.low_price::float8 as low_price,
                       f.close_price::float8 as close_price,
                       f.volume_quote::float8 as volume_quote,
                       f.trade_count::bigint as trade_count,
                       f.batch_id, f.loaded_at
                from dw.fact_ohlcv_daily f
                join dw.dim_asset a on a.asset_key = f.asset_key
                join dw.dim_date d on d.date_key = f.date_key
                join dw.dim_source s on s.source_key = f.source_key
                where s.source_code = %s and upper(a.symbol) = any(%s)
                  and d.full_date >= %s::date and d.full_date < %s::date
                order by a.symbol, d.full_date
                """,
                (self.source_code, resolved, start, end),
            )
            columns = [column.name for column in cursor.description]
            frame = pd.DataFrame(cursor.fetchall(), columns=columns)
        return self._normalize(frame)

    def fetch_coverage(
        self, symbols: Sequence[str], start: datetime, end: datetime
    ) -> pd.DataFrame:
        rows = []
        for symbol in symbols:
            candles = self.fetch_candles(symbol, start, end)
            rows.append({
                "symbol": symbol.upper(),
                "first_candle": None if candles.empty else candles.open_time.min(),
                "last_candle": None if candles.empty else candles.open_time.max(),
                "row_count": len(candles),
                "duplicate_count": int(candles.open_time.duplicated().sum()) if not candles.empty else 0,
            })
        return pd.DataFrame(rows)

    def fetch_source_batch_ids(
        self, symbol: str, start: datetime, end: datetime
    ) -> list[int]:
        import psycopg2

        with psycopg2.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                select distinct f.batch_id
                from dw.fact_ohlcv_daily f
                join dw.dim_asset a on a.asset_key = f.asset_key
                join dw.dim_date d on d.date_key = f.date_key
                join dw.dim_source s on s.source_key = f.source_key
                where s.source_code = %s and a.symbol = %s
                  and d.full_date >= %s::date and d.full_date < %s::date
                order by f.batch_id
                """,
                (self.source_code, symbol.upper(), utc_datetime(start), utc_datetime(end)),
            )
            return [int(row[0]) for row in cursor.fetchall()]


def candle_repository(frequency: str, **kwargs):
    if frequency == "1h":
        return HourlyCandleRepository(**kwargs)
    if frequency == "1d":
        return DailyCandleRepository(**kwargs)
    raise ValueError(f"unsupported forecasting frequency: {frequency}")
