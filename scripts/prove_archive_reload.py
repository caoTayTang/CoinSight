"""Load one cached Binance archive twice and assert warehouse idempotency.

Use a disposable/demo database without concurrent historical loaders.
"""
import argparse
import hashlib
import json
from pathlib import Path

from pipeline.settings import DATABASE_URL
from pipeline.batch.staging_writer import StagingRepository
from pipeline.batch.warehouse_loader import run


def fingerprint(database_url):
    import psycopg2
    digest = hashlib.sha256()
    count = 0
    with psycopg2.connect(database_url) as conn, conn.cursor() as cursor:
        for table in ('dw.fact_ohlcv_daily', 'dw.fact_ohlcv_hourly'):
            cursor.execute(f'select row_to_json(f)::text from {table} f order by asset_key, date_key, source_key' +
                           (', time_key' if table.endswith('hourly') else ''))
            for row in cursor:
                digest.update((row[0] + '\n').encode())
                count += 1
    return {'rows': count, 'sha256': digest.hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--interval', required=True, choices=['1h', '1d'])
    parser.add_argument('--database-url', default=DATABASE_URL)
    args = parser.parse_args()
    repository = StagingRepository(args.database_url)
    files = [(args.symbol.upper(), args.interval, args.archive)]
    first_extract, _ = repository.load(files, replace=False)
    first = run(args.database_url, extract_batch_id=first_extract)
    before = fingerprint(args.database_url)
    second_extract, _ = repository.load(files, replace=False)
    second = run(args.database_url, extract_batch_id=second_extract)
    after = fingerprint(args.database_url)
    assert second['rows_loaded'] == 0, 'Reload changed facts'
    assert before == after, 'Fact rows or metadata changed on reload'
    print(json.dumps({'result': 'PASS', 'first_load': first, 'reload': second,
                      'before': before, 'after': after}, indent=2))


if __name__ == '__main__':
    main()
