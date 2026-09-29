"""Extract Binance spot klines into staging.stg_ohlcv.

Completed months are downloaded as monthly archives and the current month as
daily archives from Binance Public Data. Each archive is checked against its
published SHA-256 checksum and cached under RAW_DIR/binance, so reruns only
download new files. Staging is truncate-and-load: every run replaces the
previous Binance rows and records its batch in meta.etl_batch.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

try:
    from .config import (
        BATCH_INTERVALS,
        BATCH_START_MONTH,
        BATCH_SYMBOLS,
        BINANCE_DATA_URL,
        DATABASE_URL,
        RAW_DIR,
    )
except ImportError:
    from config import (
        BATCH_INTERVALS,
        BATCH_START_MONTH,
        BATCH_SYMBOLS,
        BINANCE_DATA_URL,
        DATABASE_URL,
        RAW_DIR,
    )


SOURCE_CODE = "binance"
QUOTE_ASSET = "USDT"
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
STAGING_COLUMNS = (
    "batch_id",
    "source_code",
    "symbol",
    "candle_interval",
    "open_time",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume_base",
    "volume_quote",
    "trade_count",
    "source_file",
)


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


def fetch(url: str, timeout: float = 30) -> bytes | None:
    request = Request(url, headers={"User-Agent": "CoinSight/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as error:
        if error.code == 404:
            return None
        raise


def verify_checksum(path: Path, checksum_text: str) -> None:
    expected = checksum_text.split()[0].lower()
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"checksum mismatch for {path.name}")


def download_archive(url: str, destination: Path) -> Path | None:
    """Return the cached archive, downloading it first; None if not published."""
    if destination.exists():
        return destination

    content = fetch(url)
    if content is None:
        return None
    checksum = fetch(f"{url}.CHECKSUM")
    if checksum is None:
        raise ValueError(f"missing checksum for {url}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    partial.write_bytes(content)
    try:
        verify_checksum(partial, checksum.decode())
    except ValueError:
        partial.unlink()
        raise
    partial.rename(destination)
    return destination


def download_period(
    base_url: str, raw_dir: Path, symbol: str, interval: str, period: str, today: date
) -> list[Path]:
    pair = f"{symbol.upper()}{QUOTE_ASSET}"
    url = kline_url(base_url, symbol, interval, period)
    path = download_archive(url, raw_dir / SOURCE_CODE / pair / interval / url.rsplit("/", 1)[1])
    if path is not None:
        return [path]

    # Binance publishes last month's archive a few days into the new month.
    year, month = (int(part) for part in period.split("-")[:2])
    last_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    if len(period) == 7 and period == last_month:
        return [
            path
            for day in month_days(year, month, today)
            for path in download_period(base_url, raw_dir, symbol, interval, day, today)
        ]
    return []


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


def staging_csv(batch_id: int, symbol: str, interval: str, path: Path) -> tuple[io.StringIO, int]:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    rows = parse_kline_csv(read_zip_csv(path))
    for row in rows:
        writer.writerow(
            [
                batch_id,
                SOURCE_CODE,
                symbol,
                interval,
                row["open_time"].isoformat(),
                row["open_price"],
                row["high_price"],
                row["low_price"],
                row["close_price"],
                row["volume_base"],
                row["volume_quote"],
                row["trade_count"],
                path.name,
            ]
        )
    buffer.seek(0)
    return buffer, len(rows)


def load_staging(files: list[tuple[str, str, Path]], database_url: str) -> tuple[int, int]:
    import psycopg2

    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into meta.etl_batch (pipeline, source_code)
                values ('extract_binance', %s)
                returning batch_id
                """,
                (SOURCE_CODE,),
            )
            batch_id = cursor.fetchone()[0]
        connection.commit()

        try:
            total = 0
            with connection.cursor() as cursor:
                cursor.execute(
                    "delete from staging.stg_ohlcv where source_code = %s", (SOURCE_CODE,)
                )
                copy_sql = (
                    f"copy staging.stg_ohlcv ({', '.join(STAGING_COLUMNS)}) "
                    "from stdin with (format csv)"
                )
                for symbol, interval, path in files:
                    buffer, count = staging_csv(batch_id, symbol, interval, path)
                    cursor.copy_expert(copy_sql, buffer)
                    total += count
                cursor.execute(
                    """
                    update meta.etl_batch
                    set status = 'success', finished_at = clock_timestamp(), rows_extracted = %s
                    where batch_id = %s
                    """,
                    (total, batch_id),
                )
            connection.commit()
        except Exception as error:
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    update meta.etl_batch
                    set status = 'failed', finished_at = clock_timestamp(), message = %s
                    where batch_id = %s
                    """,
                    (str(error)[:1000], batch_id),
                )
            connection.commit()
            raise
    finally:
        connection.close()
    return batch_id, total


def parse_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def extract(
    symbols: list[str],
    intervals: list[str],
    start_month: str,
    raw_dir: Path,
    workers: int = 8,
    load: bool = True,
    database_url: str = DATABASE_URL,
) -> dict:
    """Download the planned archives and, when load is set, stage them."""
    symbols = [symbol.upper() for symbol in symbols]
    today = datetime.now(timezone.utc).date()
    periods = plan_periods(start_month, today)
    tasks = [
        (symbol, interval, period)
        for symbol in symbols
        for interval in intervals
        for period in periods
    ]
    print(f"checking {len(tasks)} archives for {len(symbols)} symbols, {intervals}")

    def run(task: tuple[str, str, str]) -> list[Path]:
        symbol, interval, period = task
        return download_period(BINANCE_DATA_URL, raw_dir, symbol, interval, period, today)

    files: list[tuple[str, str, Path]] = []
    missing: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for (symbol, interval, _), paths in zip(tasks, executor.map(run, tasks)):
            if not paths:
                missing[symbol] = missing.get(symbol, 0) + 1
            files.extend((symbol, interval, path) for path in paths)

    print(f"{len(files)} archives available under {raw_dir / SOURCE_CODE}")
    for symbol, count in sorted(missing.items()):
        print(f"  {symbol}: {count} periods not published (not listed yet or delisted)")

    summary = {"archives": len(files), "missing": missing}
    if load:
        batch_id, total = load_staging(files, database_url)
        print(f"batch {batch_id}: loaded {total} rows into staging.stg_ohlcv")
        summary.update(batch_id=batch_id, rows_staged=total)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbols", default=BATCH_SYMBOLS, help="comma-separated, e.g. BTC,ETH")
    parser.add_argument("--intervals", default=BATCH_INTERVALS, help="comma-separated: 1d,1h")
    parser.add_argument("--start", default=BATCH_START_MONTH, help="first month, YYYY-MM")
    parser.add_argument("--raw-dir", default=RAW_DIR)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--no-load", action="store_true", help="download only")
    args = parser.parse_args()

    extract(
        parse_list(args.symbols),
        parse_list(args.intervals),
        args.start,
        Path(args.raw_dir),
        args.workers,
        load=not args.no_load,
    )


if __name__ == "__main__":
    main()
