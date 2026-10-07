"""Binance Spot archive naming, date planning and CSV decoding."""
from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
import io
from pathlib import Path
import zipfile

QUOTE_ASSET = "USDT"
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

def kline_url(base_url: str, symbol: str, interval: str, period: str) -> str:
    pair = f"{symbol.upper()}{QUOTE_ASSET}"
    frequency = "monthly" if len(period) == 7 else "daily"
    return (
        f"{base_url.rstrip('/')}/data/spot/{frequency}/klines/"
        f"{pair}/{interval}/{pair}-{interval}-{period}.zip"
    )


def month_days(year: int, month: int, until: date) -> list[str]:
    day = date(year, month, 1)
    days = []
    while day.month == month and day < until:
        days.append(day.isoformat())
        day += timedelta(days=1)
    return days


def plan_periods(start_month: str, today: date | None = None) -> list[str]:
    """Monthly periods before the current month, then completed days of it."""
    today = today or datetime.now(timezone.utc).date()
    year, month = (int(part) for part in start_month.split("-"))
    periods = []
    while (year, month) < (today.year, today.month):
        periods.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return periods + month_days(today.year, today.month, today)


def read_zip_csv(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one CSV in {path.name}, found {len(names)}")
        return archive.read(names[0]).decode()


def parse_kline_csv(text: str) -> list[dict]:
    rows = []
    for fields in csv.reader(io.StringIO(text)):
        if not fields or not fields[0].strip().isdigit():
            continue  # blank line or header row
        if len(fields) < 9:
            raise ValueError("kline row has fewer than 9 fields")

        # Binance switched open_time from milliseconds to microseconds in 2025.
        raw_time = int(fields[0])
        if raw_time >= 10**14:
            open_time = EPOCH + timedelta(microseconds=raw_time)
        else:
            open_time = EPOCH + timedelta(milliseconds=raw_time)

        rows.append(
            {
                "open_time": open_time,
                "open_price": fields[1],
                "high_price": fields[2],
                "low_price": fields[3],
                "close_price": fields[4],
                "volume_base": fields[5],
                "volume_quote": fields[7],
                "trade_count": fields[8],
            }
        )
    return rows
