"""Daily batch load of the CoinSight data warehouse.

extract_binance -> transform_load -> quality_report

1. extract_binance: inspect only the previous UTC day's 1h/1d archives;
   stage new or revised files, and fail if an expected file is missing.
2. transform_load: run data quality rules, upsert dimensions and facts, and
   refresh the mart materialized views. The task fails, and the warehouse is
   left untouched, when too many staged rows are rejected.
3. quality_report: log every check recorded for the batch.

Binance publishes the previous UTC day's archive during the early hours. The
UTC schedule is configured in pipeline/settings.yaml.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from airflow.sdk import dag, get_current_context, task
from pipeline.telemetry import airflow_task
from pipeline.settings import BATCH


@dag(
    dag_id="coinsight_warehouse_daily",
    schedule=BATCH["daily_schedule_utc"],
    start_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": BATCH["daily_retries"],
                  "retry_delay": timedelta(minutes=BATCH["daily_retry_minutes"])},
    tags=["coinsight", "warehouse"],
    doc_md=__doc__,
)
def coinsight_warehouse_daily():
    # Pipeline modules are imported inside tasks to keep DAG parsing fast.

    @task
    @airflow_task
    def extract_binance() -> dict:
        from pathlib import Path

        from pipeline.settings import BATCH_INTERVALS, BATCH_SYMBOLS, RAW_DIR
        from pipeline.batch.ingest_binance_history import extract_daily, parse_list

        # Logical interval is stable across retries, even when a retry crosses midnight.
        day = get_current_context()["data_interval_end"].date() - timedelta(days=1)
        summary = extract_daily(parse_list(BATCH_SYMBOLS), parse_list(BATCH_INTERVALS),
                                day, Path(RAW_DIR))
        return {"batch_id": summary["batch_id"], "rows_staged": summary["rows_staged"]}

    @task
    @airflow_task
    def transform_load(extract_summary: dict) -> dict:
        from pipeline.batch.warehouse_loader import run

        if extract_summary["batch_id"] is None:
            return {"batch_id": None, "rows_rejected": 0, "rows_loaded": 0}
        print(f"staged by extract batch {extract_summary['batch_id']}")
        return run(extract_batch_id=extract_summary["batch_id"])

    @task
    @airflow_task
    def quality_report(load_summary: dict) -> None:
        from pipeline.batch.warehouse_loader import quality_summary

        if load_summary["batch_id"] is None:
            print("no new or revised archive; warehouse already current")
            return
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
