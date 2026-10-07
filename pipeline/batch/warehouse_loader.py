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

from pipeline.settings import BATCH, DATABASE_URL
from pipeline.batch.quality_checks import ROW_RULES, BATCH_CHECKS, check_quality


DEFAULT_REJECT_THRESHOLD = BATCH["reject_threshold"]
# Refreshed in the load transaction, so marts never show a half-loaded batch.
MATERIALIZED_VIEWS = tuple(BATCH["mart_views"])


class DataQualityError(Exception):
    pass


# Warnings: recorded for monitoring, rows are still loaded.

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


def run(
    database_url: str = DATABASE_URL,
    reject_threshold: float = DEFAULT_REJECT_THRESHOLD,
    extract_batch_id: int | None = None,
) -> dict:
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
                cursor.execute(
                    """
                    insert into meta.batch_dependency (load_batch_id, extract_batch_id)
                    select distinct %s, batch_id from staging.stg_ohlcv
                    where (%s is null or batch_id = %s)
                    on conflict do nothing
                    """,
                    (batch_id, extract_batch_id, extract_batch_id),
                )
                summary = check_quality(cursor, batch_id, extract_batch_id)
            connection.commit()  # keep check results even if the batch is aborted

            rows_read, rejected = summary["rows_read"], summary["rows_rejected"]
            if extract_batch_id is not None and not rows_read:
                raise DataQualityError(f"extract batch {extract_batch_id} has no staged rows")
            if rows_read and rejected / rows_read > reject_threshold:
                raise DataQualityError(
                    f"{rejected} of {rows_read} staged rows failed quality rules "
                    f"(threshold {reject_threshold:.0%})"
                )

            with connection.cursor() as cursor:
                summary["rows_loaded"] = load_warehouse(cursor, batch_id)
                cursor.execute(
                    """
                    insert into meta.loaded_archive (source_file, sha256, load_batch_id)
                    select distinct on (f.source_file) f.source_file, f.sha256, %s
                    from meta.batch_dependency d
                    join meta.source_file_manifest f on f.extract_batch_id = d.extract_batch_id
                    where d.load_batch_id = %s
                    order by f.source_file, f.extract_batch_id desc
                    on conflict (source_file) do update set
                        sha256 = excluded.sha256,
                        load_batch_id = excluded.load_batch_id,
                        loaded_at = now()
                    """,
                    (batch_id, batch_id),
                )
                if extract_batch_id is not None:
                    cursor.execute(
                        "delete from staging.stg_ohlcv where batch_id = %s",
                        (extract_batch_id,),
                    )
                cursor.execute(
                    """
                    update meta.etl_batch
                    set status = 'success', finished_at = clock_timestamp(),
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
                    set status = 'failed', finished_at = clock_timestamp(), message = %s
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


def quality_summary(batch_id: int, database_url: str = DATABASE_URL) -> list[dict]:
    """Return the recorded quality checks of one batch, failed checks first."""
    import psycopg2

    with psycopg2.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            select check_name, severity, failed_rows, passed
            from meta.dq_result
            where batch_id = %s
            order by passed, severity, check_name
            """,
            (batch_id,),
        )
        columns = [column.name for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


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
