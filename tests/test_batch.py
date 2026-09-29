from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import os

import pytest

from pipeline.batch_etl import ROW_RULES, DataQualityError, run
from pipeline.config import DATABASE_URL


INIT_DIR = Path(__file__).parents[1] / "postgres" / "init"


def test_row_rules_are_named_errors():
    names = [rule.name for rule in ROW_RULES]
    assert len(names) == len(set(names))
    assert "ohlc_consistency" in names


def with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{name}"))


@pytest.fixture
def warehouse_url():
    psycopg2 = pytest.importorskip("psycopg2")
    admin_url = with_database(DATABASE_URL, "postgres")
    try:
        admin = psycopg2.connect(admin_url, connect_timeout=2)
    except psycopg2.OperationalError:
        pytest.skip("PostgreSQL is not reachable")
    admin.autocommit = True
    name = f"coinsight_test_{os.getpid()}"
    with admin.cursor() as cursor:
        cursor.execute(f"drop database if exists {name}")
        cursor.execute(f"create database {name}")

    url = with_database(DATABASE_URL, name)
    with psycopg2.connect(url) as connection, connection.cursor() as cursor:
        for script in sorted(INIT_DIR.glob("*.sql")):
            cursor.execute(script.read_text())
    try:
        yield url
    finally:
        with admin.cursor() as cursor:
            cursor.execute(f"drop database if exists {name} with (force)")
        admin.close()


def stage(url: str, rows: list[tuple]) -> None:
    import psycopg2

    with psycopg2.connect(url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "insert into meta.etl_batch (pipeline, source_code, status) "
            "values ('test', 'binance', 'success') returning batch_id"
        )
        batch_id = cursor.fetchone()[0]
        cursor.executemany(
            """
            insert into staging.stg_ohlcv (
                batch_id, source_code, symbol, candle_interval, open_time,
                open_price, high_price, low_price, close_price,
                volume_base, volume_quote, trade_count
            ) values (%s, 'binance', %s, %s, %s, %s, %s, %s, %s, 1, %s, 10)
            """,
            [(batch_id, *row) for row in rows],
        )


def query(url: str, sql: str) -> list[tuple]:
    import psycopg2

    with psycopg2.connect(url) as connection, connection.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchall()


GOOD_ROWS = [
    ("BTC", "1d", "2025-01-01T00:00:00Z", 100, 110, 90, 105, 2400),
    ("BTC", "1d", "2025-01-02T00:00:00Z", 105, 120, 100, 115, 0),
    ("NEWCOIN", "1d", "2025-01-01T00:00:00Z", 1, 2, 0.5, 1.5, 10),
    ("BTC", "1h", "2025-01-01T00:00:00Z", 100, 101, 99, 100, 100),
    ("BTC", "1h", "2025-01-01T01:00:00Z", 100, 102, 99, 101, 100),
]
BAD_ROWS = [
    ("ETH", "1d", "2025-01-01T00:00:00Z", 100, 90, 80, 95, 10),  # high below open
    ("ETH", "1h", "2025-01-01T00:30:00Z", 100, 101, 99, 100, 10),  # not on the hour
]


def test_run_loads_valid_rows_and_records_quality(warehouse_url):
    stage(warehouse_url, GOOD_ROWS + BAD_ROWS + [GOOD_ROWS[0]])

    summary = run(warehouse_url, reject_threshold=0.5)

    assert summary["rows_read"] == 8
    assert summary["rows_rejected"] == 2
    assert summary["daily_rows"] == 3
    assert summary["hourly_rows"] == 2
    assert query(
        warehouse_url,
        "select name from dw.dim_asset where symbol = 'NEWCOIN'",
    ) == [("NEWCOIN",)]
    assert query(
        warehouse_url,
        "select time_key from dw.fact_ohlcv_hourly order by time_key",
    ) == [(0,), (1,)]

    failed = dict(
        query(
            warehouse_url,
            "select check_name, failed_rows from meta.dq_result where not passed",
        )
    )
    assert failed == {
        "ohlc_consistency": 1,
        "interval_alignment": 1,
        "duplicate_grain": 1,
        "zero_volume": 1,
        "freshness": 2,
    }


def test_run_is_idempotent(warehouse_url):
    stage(warehouse_url, GOOD_ROWS)
    run(warehouse_url)
    run(warehouse_url)

    assert query(warehouse_url, "select count(*) from dw.fact_ohlcv_daily") == [(3,)]
    assert query(
        warehouse_url,
        "select status, count(*) from meta.etl_batch "
        "where pipeline = 'batch_etl' group by status",
    ) == [("success", 2)]


def test_run_aborts_when_too_many_rows_are_rejected(warehouse_url):
    stage(warehouse_url, GOOD_ROWS[:1] + BAD_ROWS)

    with pytest.raises(DataQualityError):
        run(warehouse_url, reject_threshold=0.05)

    assert query(warehouse_url, "select count(*) from dw.fact_ohlcv_daily") == [(0,)]
    assert query(
        warehouse_url,
        "select status from meta.etl_batch where pipeline = 'batch_etl'",
    ) == [("failed",)]
    assert query(
        warehouse_url,
        "select count(*) from meta.dq_result where check_name = 'ohlc_consistency'",
    ) == [(1,)]


def test_run_with_empty_staging_succeeds(warehouse_url):
    summary = run(warehouse_url)
    assert summary["rows_read"] == 0


MART_ROWS = [
    ("BTC", "1d", "2025-01-01T00:00:00Z", 100, 100, 100, 100, 10),
    ("BTC", "1d", "2025-01-31T00:00:00Z", 100, 110, 100, 110, 10),
    ("BTC", "1d", "2025-02-01T00:00:00Z", 110, 110, 110, 110, 10),
    ("BTC", "1d", "2025-02-28T00:00:00Z", 110, 121, 110, 121, 10),
    ("DOGE", "1d", "2025-01-01T00:00:00Z", 10, 10, 10, 10, 5),
    ("DOGE", "1d", "2025-02-28T00:00:00Z", 10, 10, 8, 8, 5),
    ("BTC", "1h", "2025-01-01T00:00:00Z", 100, 101, 99, 100, 1),
    ("BTC", "1h", "2025-01-01T09:00:00Z", 100, 102, 99, 101, 1),
]


def test_run_refreshes_olap_marts(warehouse_url):
    stage(warehouse_url, MART_ROWS)
    run(warehouse_url)

    summary = dict(
        query(
            warehouse_url,
            """
            select period_level || coalesce(':' || month, ':' || quarter, ''),
                   round(period_return, 4)::float
            from mart.mv_asset_period_summary where symbol = 'BTC'
            """,
        )
    )
    assert summary == {
        "month:1": 0.1,
        "month:2": 0.1,
        "quarter:1": 0.21,
        "year": 0.21,
        "all": 0.21,
    }

    assert query(
        warehouse_url,
        "select assets, asset_days from mart.mv_category_performance "
        "where category = 'ALL' and grouping_id = 7",
    ) == [(2, 6)]

    assert query(
        warehouse_url,
        "select symbol, gain_rank, loss_rank from mart.v_top_movers "
        "where year = 2025 and quarter = 1 order by gain_rank",
    ) == [("BTC", 1, 2), ("DOGE", 2, 1)]

    assert query(
        warehouse_url,
        "select trading_session, candles from mart.mv_hourly_activity "
        "where symbol = 'ALL' and hour_utc is null order by trading_session",
    ) == [("ALL", 2), ("asia", 1), ("europe", 1)]
