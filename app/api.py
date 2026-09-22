from __future__ import annotations

import os

from fastapi import FastAPI


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://crypto:crypto@localhost:5432/crypto_dw")

app = FastAPI(title="Crypto DW DSS API")


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


@app.get("/assets")
def assets() -> list[dict]:
    return fetch_all("select symbol, name from dim_asset order by symbol")


@app.get("/prices/{symbol}")
def prices(symbol: str, limit: int = 100) -> list[dict]:
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
