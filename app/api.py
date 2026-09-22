from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://crypto:crypto@localhost:5432/crypto_dw")

app = FastAPI(title="Crypto DW DSS API")
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def fetch_all(sql: str, params: tuple = ()) -> list[dict]:
    import psycopg2

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/assets")
def assets() -> list[dict]:
    return fetch_all("select symbol, name from dim_asset order by symbol")


@app.get("/prices/{symbol}")
def prices(symbol: str, limit: int = Query(100, ge=1, le=1000)) -> list[dict]:
    return fetch_all(
        """
        select symbol, ts, price_usd, volume_usd
        from fact_price
        where symbol = %s
        order by ts desc
        limit %s
        """,
        (symbol.upper(), limit),
    )


@app.get("/live-metrics/{symbol}")
def live_metrics(symbol: str, limit: int = Query(100, ge=1, le=1000)) -> list[dict]:
    return fetch_all(
        """
        select symbol, window_start, window_end, avg_price_usd,
               price_volatility, total_volume, event_count, updated_at
        from fact_live_metric
        where symbol = %s
        order by window_end desc
        limit %s
        """,
        (symbol.upper(), limit),
    )


@app.get("/overview")
def overview() -> list[dict]:
    return fetch_all(
        """
        select a.symbol, a.name,
               latest.ts as latest_ts,
               latest.price_usd as latest_price_usd,
               previous.price_usd as previous_price_usd,
               stats.observation_count,
               stats.first_ts,
               stats.last_ts,
               stats.avg_volume_usd,
               live.window_end as live_window_end,
               live.avg_price_usd as live_avg_price_usd,
               live.price_volatility as live_price_volatility,
               live.event_count as live_event_count,
               live.updated_at as live_updated_at
        from dim_asset a
        left join lateral (
            select ts, price_usd
            from fact_price
            where symbol = a.symbol
            order by ts desc
            limit 1
        ) latest on true
        left join lateral (
            select price_usd
            from fact_price
            where symbol = a.symbol
            order by ts desc
            offset 1 limit 1
        ) previous on true
        left join lateral (
            select count(*) as observation_count,
                   min(ts) as first_ts,
                   max(ts) as last_ts,
                   avg(volume_usd) as avg_volume_usd
            from fact_price
            where symbol = a.symbol
        ) stats on true
        left join lateral (
            select window_end, avg_price_usd, price_volatility,
                   event_count, updated_at
            from fact_live_metric
            where symbol = a.symbol
            order by updated_at desc, window_end desc
            limit 1
        ) live on true
        order by a.symbol
        """
    )
