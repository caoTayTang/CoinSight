"""Repair trailing Binance daily/hourly archive coverage per configured asset.

This is intentionally a tail catch-up, not a historical bootstrap: every
requested symbol/interval must already exist in the warehouse.  Only completed
UTC days after each individual tail are downloaded, staged and loaded.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from pipeline.batch.ingest_binance_history import extract_daily, parse_list
from pipeline.batch.warehouse_loader import run as load_warehouse
from pipeline.settings import (
    BATCH_INTERVALS,
    BATCH_SYMBOLS,
    DATABASE_URL,
    RAW_DIR,
)


class BootstrapRequiredError(RuntimeError):
    """Raised when tail repair cannot safely infer where history should start."""


def warehouse_tails(
    symbols: list[str],
    intervals: list[str],
    database_url: str = DATABASE_URL,
) -> dict[str, dict[str, date | None]]:
    """Return the latest loaded UTC date for every symbol/interval pair."""
    import psycopg2

    requested = {symbol.upper(): {interval: None for interval in intervals} for symbol in symbols}
    with psycopg2.connect(database_url) as connection, connection.cursor() as cursor:
        if "1d" in intervals:
            cursor.execute(
                """
                select a.symbol, max(d.full_date)
                from dw.fact_ohlcv_daily f
                join dw.dim_asset a using (asset_key)
                join dw.dim_date d using (date_key)
                join dw.dim_source s using (source_key)
                where s.source_code = 'binance' and a.symbol = any(%s)
                group by a.symbol
                """,
                (list(requested),),
            )
            for symbol, latest in cursor.fetchall():
                requested[symbol]["1d"] = latest
        if "1h" in intervals:
            cursor.execute(
                """
                select a.symbol, max((f.open_time at time zone 'UTC')::date)
                from dw.fact_ohlcv_hourly f
                join dw.dim_asset a using (asset_key)
                join dw.dim_source s using (source_key)
                where s.source_code = 'binance' and a.symbol = any(%s)
                group by a.symbol
                """,
                (list(requested),),
            )
            for symbol, latest in cursor.fetchall():
                requested[symbol]["1h"] = latest
    return requested


def tail_plan(
    tails: dict[str, dict[str, date | None]], through: date
) -> list[tuple[date, list[str]]]:
    """Group symbols by each completed day their warehouse tail is missing."""
    absent = [
        f"{symbol}/{interval}"
        for symbol, interval_tails in tails.items()
        for interval, latest in interval_tails.items()
        if latest is None
    ]
    if absent:
        raise BootstrapRequiredError(
            "tail catch-up requires existing warehouse history for: " + ", ".join(absent)
        )
    if not tails:
        return []
    first_missing = min(
        latest
        for interval_tails in tails.values()
        for latest in interval_tails.values()
        if latest is not None
    ) + timedelta(days=1)
    plan = []
    day = first_missing
    while day <= through:
        missing = sorted(
            symbol
            for symbol, interval_tails in tails.items()
            if any(latest is not None and latest < day for latest in interval_tails.values())
        )
        if missing:
            plan.append((day, missing))
        day += timedelta(days=1)
    return plan


def run(
    symbols: list[str],
    intervals: list[str],
    through: date | None = None,
    raw_dir: Path = Path(RAW_DIR),
    database_url: str = DATABASE_URL,
) -> dict:
    """Load all missing trailing completed days and return an audit summary."""
    today = datetime.now(timezone.utc).date()
    through = through or today - timedelta(days=1)
    if through >= today:
        raise ValueError("through must be a fully completed UTC day")
    symbols = sorted({symbol.upper() for symbol in symbols})
    intervals = list(dict.fromkeys(intervals))
    tails = warehouse_tails(symbols, intervals, database_url)
    plan = tail_plan(tails, through)
    loads = []
    for day, missing_symbols in plan:
        extracted = extract_daily(
            missing_symbols, intervals, day, raw_dir, database_url=database_url
        )
        loaded = None
        if extracted["batch_id"] is not None:
            loaded = load_warehouse(
                database_url=database_url, extract_batch_id=extracted["batch_id"]
            )
        loads.append(
            {
                "day": day.isoformat(),
                "symbols": missing_symbols,
                "extract": extracted,
                "load": loaded,
            }
        )
    return {
        "status": "caught_up" if loads else "already_current",
        "through": through.isoformat(),
        "days_processed": len(loads),
        "loads": loads,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbols", default=BATCH_SYMBOLS)
    parser.add_argument("--intervals", default=BATCH_INTERVALS)
    parser.add_argument("--through", help="last completed UTC day, YYYY-MM-DD")
    parser.add_argument("--raw-dir", default=RAW_DIR)
    args = parser.parse_args()
    through = date.fromisoformat(args.through) if args.through else None
    print(
        run(
            parse_list(args.symbols),
            parse_list(args.intervals),
            through,
            Path(args.raw_dir),
        )
    )


if __name__ == "__main__":
    main()
