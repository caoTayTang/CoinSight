"""Transform staged OHLCV candles and load them into the warehouse.

Flow: staging.stg_ohlcv -> data quality checks -> dw dimensions -> dw facts
-> refreshed mart materialized views.

Rows that fail a row rule are rejected and never reach the warehouse. If the
share of rejected rows exceeds the threshold, the whole batch is aborted.
Every check result is written to meta.dq_result, and each run is logged in
meta.etl_batch. Loading is an upsert, so rerunning the same staging data does
not create duplicates.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

try:
    from .config import DATABASE_URL
except ImportError:
    from config import DATABASE_URL


STAGING_TABLE = "staging.stg_ohlcv"
GRAIN = ("source_code", "symbol", "candle_interval", "open_time")
DEFAULT_REJECT_THRESHOLD = 0.05
# Refreshed in the load transaction, so marts never show a half-loaded batch.
MATERIALIZED_VIEWS = (
    "mart.mv_asset_period_summary",
    "mart.mv_category_performance",
    "mart.mv_hourly_activity",
)


class DataQualityError(Exception):
    pass


@dataclass(frozen=True)
class RowRule:
    name: str
    predicate: str
    description: str


@dataclass(frozen=True)
class BatchCheck:
    name: str
    sql: str
    description: str


ROW_RULES = [
    RowRule(
        "not_null",
        "symbol is not null and open_price is not null and high_price is not null "
        "and low_price is not null and close_price is not null "
        "and volume_quote is not null",
        "symbol, prices and quote volume are present",
    ),
    RowRule(
        "positive_price",
        "least(open_price, high_price, low_price, close_price) > 0",
        "all prices are greater than zero",
    ),
    RowRule(
        "ohlc_consistency",
        "high_price >= greatest(open_price, close_price, low_price) "
        "and low_price <= least(open_price, close_price)",
        "high is the maximum and low the minimum of the candle",
    ),
    RowRule(
        "non_negative_volume",
        "volume_quote >= 0 and coalesce(volume_base, 0) >= 0 "
        "and coalesce(trade_count, 0) >= 0",
        "volumes and trade count are not negative",
    ),
    RowRule(
        "interval_alignment",
        "open_time = date_trunc("
        "case candle_interval when '1d' then 'day' else 'hour' end, open_time, 'UTC')",
        "candles start exactly on a UTC day or hour boundary",
    ),
    RowRule(
        "known_source",
        "source_code in (select source_code from dw.dim_source)",
        "source is registered in dw.dim_source",
    ),
    RowRule(
        "date_in_calendar",
        "(open_time at time zone 'UTC')::date between "
        "(select min(full_date) from dw.dim_date) and (select max(full_date) from dw.dim_date)",
        "candle date is covered by dw.dim_date",
    ),
]

# Warnings: recorded for monitoring, rows are still loaded.
BATCH_CHECKS = [
    BatchCheck(
        "duplicate_grain",
        f"select count(*) - count(distinct ({', '.join(GRAIN)})) from stg_passed",
        "duplicate candles for the same grain; the latest extracted copy is kept",
    ),
    BatchCheck(
        "zero_volume",
        "select count(*) from stg_valid where volume_quote = 0",
        "candles without any trading",
    ),
    BatchCheck(
        "continuity_gaps",
        """
        select count(*) from (
            select open_time - lag(open_time) over (
                partition by source_code, symbol, candle_interval order by open_time
            ) as gap, candle_interval
            from stg_valid
        ) gaps
        where gap > case candle_interval
            when '1d' then interval '1 day' else interval '1 hour' end
        """,
        "places where one or more candles are missing between two candles",
    ),
    BatchCheck(
        "freshness",
        """
        select count(*) from (
            select symbol from stg_valid
            group by symbol
            having max(open_time) < now() - interval '2 days'
        ) stale
        """,
        "symbols whose latest candle is older than two days",
    ),
    BatchCheck(
        "daily_hourly_reconciliation",
        """
        select count(*) from stg_valid d
        join (
            select source_code, symbol,
                   date_trunc('day', open_time, 'UTC') as day,
                   sum(volume_quote) as volume_quote
            from stg_valid
            where candle_interval = '1h'
            group by 1, 2, 3
            having count(*) = 24
        ) h on h.source_code = d.source_code and h.symbol = d.symbol
           and h.day = d.open_time
        where d.candle_interval = '1d'
          and abs(d.volume_quote - h.volume_quote) > 0.01 * greatest(d.volume_quote, 1)
        """,
        "complete days whose daily volume differs from the sum of hourly volume by over 1%",
    ),
]

MEASURES = (
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume_base",
    "volume_quote",
    "trade_count",
)


def upsert_fact_sql(
    table: str, keys: list[str], key_exprs: list[str], grain: list[str], interval: str
) -> str:
    columns = keys + list(MEASURES) + ["batch_id"]
    select = key_exprs + [f"v.{measure}" for measure in MEASURES] + ["%(batch_id)s"]
    changed = ", ".join(f"f.{measure}" for measure in MEASURES)
    incoming = ", ".join(f"excluded.{measure}" for measure in MEASURES)
    updates = ", ".join(f"{measure} = excluded.{measure}" for measure in MEASURES)
    return f"""
        insert into {table} as f ({', '.join(columns)})
        select {', '.join(select)}
        from stg_valid v
        join dw.dim_asset a on a.symbol = v.symbol
        join dw.dim_source s on s.source_code = v.source_code
        where v.candle_interval = '{interval}'
        on conflict ({', '.join(grain)}) do update set
            {updates}, batch_id = excluded.batch_id, loaded_at = now()
        where ({changed}) is distinct from ({incoming})
    """


DATE_KEY = "to_char(v.open_time at time zone 'UTC', 'YYYYMMDD')::integer"

UPSERT_DAILY = upsert_fact_sql(
    "dw.fact_ohlcv_daily",
    ["asset_key", "date_key", "source_key"],
    ["a.asset_key", DATE_KEY, "s.source_key"],
    ["asset_key", "date_key", "source_key"],
    "1d",
)
UPSERT_HOURLY = upsert_fact_sql(
    "dw.fact_ohlcv_hourly",
    ["asset_key", "date_key", "time_key", "source_key", "open_time"],
    [
        "a.asset_key",
        DATE_KEY,
        "extract(hour from v.open_time at time zone 'UTC')::smallint",
        "s.source_key",
        "v.open_time",
    ],
    ["asset_key", "date_key", "time_key", "source_key"],
    "1h",
)


def scalar(cursor, sql: str, params: dict | None = None) -> int:
    cursor.execute(sql, params)
    return cursor.fetchone()[0]


def record_check(cursor, batch_id: int, name: str, severity: str, failed: int, details: str) -> None:
    cursor.execute(
        """
        insert into meta.dq_result (
            batch_id, check_name, target_table, severity, failed_rows, passed, details
        ) values (%s, %s, %s, %s, %s, %s, %s)
        """,
        (batch_id, name, STAGING_TABLE, severity, failed, failed == 0, details),
    )


def check_quality(cursor, batch_id: int) -> dict:
    """Build stg_valid, record every check, and return row counts."""
    rows_read = scalar(cursor, f"select count(*) from {STAGING_TABLE}")

    for rule in ROW_RULES:
        failed = scalar(
            cursor,
            f"select count(*) from {STAGING_TABLE} where not coalesce({rule.predicate}, false)",
        )
        record_check(cursor, batch_id, rule.name, "error", failed, rule.description)

    all_rules = " and ".join(f"coalesce({rule.predicate}, false)" for rule in ROW_RULES)
    cursor.execute("drop table if exists stg_passed, stg_valid")
    cursor.execute(
        f"create temp table stg_passed as select * from {STAGING_TABLE} where {all_rules}"
    )
    cursor.execute(
        f"""
        create temp table stg_valid as
        select distinct on ({', '.join(GRAIN)}) *
        from stg_passed
        order by {', '.join(GRAIN)}, extracted_at desc, batch_id desc
        """
    )
    rows_passed = scalar(cursor, "select count(*) from stg_passed")

    for check in BATCH_CHECKS:
        failed = scalar(cursor, check.sql)
        record_check(cursor, batch_id, check.name, "warning", failed, check.description)

    cursor.execute(
        "select candle_interval, count(*) from stg_valid group by candle_interval"
    )
    accepted = dict(cursor.fetchall())
    return {
        "rows_read": rows_read,
        "rows_rejected": rows_read - rows_passed,
        "daily_rows": accepted.get("1d", 0),
        "hourly_rows": accepted.get("1h", 0),
    }


def load_warehouse(cursor, batch_id: int) -> int:
    # New symbols get a placeholder name; curated attributes live in 03_seed.sql.
    cursor.execute(
        """
        insert into dw.dim_asset (symbol, name)
        select distinct symbol, symbol from stg_valid
        on conflict (symbol) do nothing
        """
    )
    loaded = 0
    for statement in (UPSERT_DAILY, UPSERT_HOURLY):
        cursor.execute(statement, {"batch_id": batch_id})
        loaded += cursor.rowcount
    for view in MATERIALIZED_VIEWS:
        cursor.execute(f"refresh materialized view {view}")
    return loaded


def run(database_url: str = DATABASE_URL, reject_threshold: float = DEFAULT_REJECT_THRESHOLD) -> dict:
    import psycopg2

    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into meta.etl_batch (pipeline, source_code)
                values ('batch_etl', 'staging')
                returning batch_id
                """
            )
            batch_id = cursor.fetchone()[0]
        connection.commit()

        try:
            with connection.cursor() as cursor:
                summary = check_quality(cursor, batch_id)
            connection.commit()  # keep check results even if the batch is aborted

            rows_read, rejected = summary["rows_read"], summary["rows_rejected"]
            if rows_read and rejected / rows_read > reject_threshold:
                raise DataQualityError(
                    f"{rejected} of {rows_read} staged rows failed quality rules "
                    f"(threshold {reject_threshold:.0%})"
                )

            with connection.cursor() as cursor:
                summary["rows_loaded"] = load_warehouse(cursor, batch_id)
                cursor.execute(
                    """
                    update meta.etl_batch
                    set status = 'success', finished_at = now(),
                        rows_extracted = %s, rows_loaded = %s, rows_rejected = %s
                    where batch_id = %s
                    """,
                    (rows_read, summary["rows_loaded"], rejected, batch_id),
                )
            connection.commit()
        except Exception as error:
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    update meta.etl_batch
                    set status = 'failed', finished_at = now(), message = %s
                    where batch_id = %s
                    """,
                    (str(error)[:1000], batch_id),
                )
            connection.commit()
            raise
    finally:
        connection.close()

    summary["batch_id"] = batch_id
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--reject-threshold",
        type=float,
        default=DEFAULT_REJECT_THRESHOLD,
        help="maximum share of rejected rows before the batch is aborted",
    )
    args = parser.parse_args()

    summary = run(DATABASE_URL, args.reject_threshold)
    print(
        f"batch {summary['batch_id']}: read {summary['rows_read']}, "
        f"rejected {summary['rows_rejected']}, accepted {summary['daily_rows']} daily "
        f"and {summary['hourly_rows']} hourly, changed {summary['rows_loaded']} fact rows"
    )


if __name__ == "__main__":
    main()
