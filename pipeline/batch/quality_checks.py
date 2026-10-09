"""Row and batch-level data quality checks for staged OHLCV."""
from __future__ import annotations

from dataclasses import dataclass

STAGING_TABLE = "staging.stg_ohlcv"


GRAIN = ("source_code", "symbol", "candle_interval", "open_time")


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


def check_quality(cursor, batch_id: int, extract_batch_id: int | None = None) -> dict:
    """Build stg_valid, record every check, and return row counts."""
    scope = " where batch_id = %(extract_batch_id)s" if extract_batch_id is not None else ""
    params = {"extract_batch_id": extract_batch_id} if extract_batch_id is not None else None
    rows_read = scalar(cursor, f"select count(*) from {STAGING_TABLE}{scope}", params)

    for rule in ROW_RULES:
        failed = scalar(
            cursor,
            f"select count(*) from {STAGING_TABLE} where not coalesce({rule.predicate}, false)"
            + (" and batch_id = %(extract_batch_id)s" if extract_batch_id is not None else ""),
            params,
        )
        record_check(cursor, batch_id, rule.name, "error", failed, rule.description)

    all_rules = " and ".join(f"coalesce({rule.predicate}, false)" for rule in ROW_RULES)
    cursor.execute("drop table if exists stg_passed, stg_valid")
    cursor.execute(
        f"create temp table stg_passed as select * from {STAGING_TABLE} where {all_rules}"
        + (" and batch_id = %(extract_batch_id)s" if extract_batch_id is not None else ""),
        params,
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
