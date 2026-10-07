"""Extract Binance spot klines into staging.stg_ohlcv.

Bootstrap uses monthly archives and completed days of the current month.
Daily runs inspect only the previous UTC day's archives and stage only changed
files. Archive checksums and load status make retries idempotent.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import hashlib
from pathlib import Path

from pipeline.batch.binance_archive_format import (
    QUOTE_ASSET, kline_url, parse_kline_csv, plan_periods, read_zip_csv,
)
from pipeline.batch.binance_archive_downloader import download_archive, download_period
from pipeline.batch.staging_writer import StagingRepository
from pipeline.settings import (
    BATCH_INTERVALS, BATCH_START_MONTH, BATCH_SYMBOLS, BINANCE_DATA_URL,
    BATCH, DATABASE_URL, RAW_DIR,
)


SOURCE_CODE = "binance"

















def parse_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def extract_daily(
    symbols: list[str], intervals: list[str], day: date, raw_dir: Path,
    database_url: str = DATABASE_URL,
) -> dict:
    """Stage only revised or not-yet-loaded archives for one completed UTC day."""
    if day >= datetime.now(timezone.utc).date():
        raise ValueError("daily extraction requires a completed UTC day")
    files = []
    for symbol in symbols:
        symbol = symbol.upper()
        for interval in intervals:
            url = kline_url(BINANCE_DATA_URL, symbol, interval, day.isoformat())
            path = raw_dir / SOURCE_CODE / f"{symbol}{QUOTE_ASSET}" / interval / url.rsplit("/", 1)[1]
            archive = download_archive(url, path, refresh=True)
            if archive is None:
                raise FileNotFoundError(f"Binance has not published {url}")
            count = len(parse_kline_csv(read_zip_csv(archive)))
            expected = {"1h": 24, "1d": 1}[interval]
            if count != expected:
                raise ValueError(f"{archive.name}: expected {expected} candles, found {count}")
            files.append((symbol, interval, archive))

    loaded = StagingRepository(database_url).loaded_checksums(
        [path.name for _, _, path in files]
    )
    pending = [
        item for item in files
        if loaded.get(item[2].name) != hashlib.sha256(item[2].read_bytes()).hexdigest()
    ]
    if not pending:
        return {"batch_id": None, "rows_staged": 0, "archives": 0}
    batch_id, total = StagingRepository(database_url).load(pending, replace=False)
    return {"batch_id": batch_id, "rows_staged": total, "archives": len(pending)}


def extract(
    symbols: list[str],
    intervals: list[str],
    start_month: str,
    raw_dir: Path,
    workers: int | None = None,
    load: bool = True,
    database_url: str = DATABASE_URL,
) -> dict:
    """Download the planned archives and, when load is set, stage them."""
    workers = workers if workers is not None else BATCH["workers"]
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
        batch_id, total = StagingRepository(database_url).load(files)
        print(f"batch {batch_id}: loaded {total} rows into staging.stg_ohlcv")
        summary.update(batch_id=batch_id, rows_staged=total)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbols", default=BATCH_SYMBOLS, help="comma-separated, e.g. BTC,ETH")
    parser.add_argument("--intervals", default=BATCH_INTERVALS, help="comma-separated: 1d,1h")
    parser.add_argument("--start", default=BATCH_START_MONTH, help="first month, YYYY-MM")
    parser.add_argument("--raw-dir", default=RAW_DIR)
    parser.add_argument("--workers", type=int, default=BATCH["workers"])
    parser.add_argument("--no-load", action="store_true", help="download only")
    parser.add_argument("--day", help="incremental daily run for completed UTC day, YYYY-MM-DD")
    args = parser.parse_args()

    if args.day:
        if args.no_load:
            parser.error("--day cannot be combined with --no-load")
        print(extract_daily(parse_list(args.symbols), parse_list(args.intervals),
                            date.fromisoformat(args.day), Path(args.raw_dir)))
    else:
        extract(parse_list(args.symbols), parse_list(args.intervals), args.start,
                Path(args.raw_dir), args.workers, load=not args.no_load)


if __name__ == "__main__":
    main()
