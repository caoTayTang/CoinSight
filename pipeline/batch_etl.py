from __future__ import annotations

import pandas as pd

try:
    from .config import DATABASE_URL, SAMPLE_CSV
    from .contracts import PriceTick, validate_tick
except ImportError:
    from config import DATABASE_URL, SAMPLE_CSV
    from contracts import PriceTick, validate_tick


REQUIRED_COLUMNS = {"symbol", "ts", "price_usd", "volume_usd"}


def load_prices(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["ts"])
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")

    for row in df.itertuples(index=False):
        validate_tick(
            PriceTick(
                symbol=row.symbol,
                ts=row.ts.to_pydatetime(),
                price_usd=float(row.price_usd),
                volume_usd=float(row.volume_usd),
            )
        )
    return df


def upsert_prices(df: pd.DataFrame) -> int:
    import psycopg2

    sql = """
        insert into fact_price (symbol, ts, price_usd, volume_usd)
        values (%s, %s, %s, %s)
        on conflict (symbol, ts) do update set
            price_usd = excluded.price_usd,
            volume_usd = excluded.volume_usd
    """
    rows = [
        (row.symbol, row.ts.to_pydatetime(), float(row.price_usd), float(row.volume_usd))
        for row in df.itertuples(index=False)
    ]
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
    return len(rows)


def main() -> None:
    df = load_prices(SAMPLE_CSV)
    count = upsert_prices(df)
    print(f"loaded {count} price rows")


if __name__ == "__main__":
    main()
