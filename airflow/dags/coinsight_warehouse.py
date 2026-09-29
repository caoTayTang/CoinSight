"""Daily batch load of the CoinSight data warehouse.

extract_binance -> transform_load -> quality_report

1. extract_binance: download new Binance archives (cached ones are reused)
   and reload staging.stg_ohlcv.
2. transform_load: run data quality rules, upsert dimensions and facts, and
   refresh the mart materialized views. The task fails, and the warehouse is
   left untouched, when too many staged rows are rejected.
3. quality_report: log every check recorded for the batch.

Binance publishes the previous UTC day's archive during the early hours, so
the DAG runs at 03:00 UTC.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from airflow.sdk import dag, task


@dag(
    dag_id="coinsight_warehouse_daily",
    schedule="0 3 * * *",
    start_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=10)},
    tags=["coinsight", "warehouse"],
    doc_md=__doc__,
)
def coinsight_warehouse_daily():
    # Pipeline modules are imported inside tasks to keep DAG parsing fast.

    @task
    def extract_binance() -> dict:
        from pathlib import Path

        from pipeline.config import BATCH_INTERVALS, BATCH_START_MONTH, BATCH_SYMBOLS, RAW_DIR
        from pipeline.extract_binance import extract, parse_list

        summary = extract(
            parse_list(BATCH_SYMBOLS),
            parse_list(BATCH_INTERVALS),
            BATCH_START_MONTH,
            Path(RAW_DIR),
        )
        return {"batch_id": summary["batch_id"], "rows_staged": summary["rows_staged"]}

    @task
    def transform_load(extract_summary: dict) -> dict:
        from pipeline.batch_etl import run

        print(f"staged by extract batch {extract_summary['batch_id']}")
        return run()

    @task
    def quality_report(load_summary: dict) -> None:
        from pipeline.batch_etl import quality_summary

        checks = quality_summary(load_summary["batch_id"])
        failed = [check for check in checks if not check["passed"]]
        print(
            f"batch {load_summary['batch_id']}: {len(checks)} checks, "
            f"{len(failed)} with findings, {load_summary['rows_rejected']} rows rejected"
        )
        for check in checks:
            status = "ok" if check["passed"] else f"{check['failed_rows']} rows"
            print(f"  [{check['severity']}] {check['check_name']}: {status}")

    quality_report(transform_load(extract_binance()))


coinsight_warehouse_daily()
