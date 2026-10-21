"""Explicit scoped archive backfill; preserve unrelated staging batches."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from pipeline.batch.binance_archive_downloader import download_period
from pipeline.batch.binance_archive_format import plan_periods
from pipeline.batch.staging_writer import StagingRepository
from pipeline.batch.warehouse_loader import run
from pipeline.settings import BINANCE_DATA_URL, DATABASE_URL


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbols', default='BTC,ETH,SOL,ADA,DOGE,SHIB')
    parser.add_argument('--start', default='2024-01', help='First month YYYY-MM')
    parser.add_argument('--interval', choices=['1d', '1h'], default='1d')
    parser.add_argument('--raw-dir', type=Path, default=Path('data/raw'))
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--database-url', default=DATABASE_URL)
    args = parser.parse_args()
    symbols = list(dict.fromkeys(s.strip().upper() for s in args.symbols.split(',') if s.strip()))
    if not symbols or args.workers < 1:
        parser.error('Non-empty symbols and positive workers required')
    today = datetime.now(timezone.utc).date()
    tasks = [(symbol, period) for symbol in symbols for period in plan_periods(args.start, today)]
    def download(task):
        symbol, period = task
        return download_period(BINANCE_DATA_URL, args.raw_dir, symbol, args.interval, period, today)
    files = []
    missing = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for (symbol, period), paths in zip(tasks, executor.map(download, tasks)):
            if not paths:
                missing.append((symbol, period))
            files.extend((symbol, args.interval, path) for path in paths)
    if not files:
        raise ValueError('No archives available; nothing was staged or loaded')
    print(f'{len(files)} archives; unpublished periods: {missing}', flush=True)
    extract_id, count = StagingRepository(args.database_url).load(files, replace=False)
    print(f'Extract batch {extract_id}: {count} staged rows', flush=True)
    print(run(args.database_url, extract_batch_id=extract_id))


if __name__ == '__main__':
    main()
