"""Daily batch load of the CoinSight data warehouse.

extract_binance -> transform_load -> quality_report

The scheduled task compares each configured symbol/interval warehouse tail
with the previous completed UTC day. It repairs every missing trailing day,
then runs the normal quality checks and warehouse upserts for each extract.

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
    def catch_up_binance() -> dict:
        from pipeline.settings import BATCH_INTERVALS, BATCH_SYMBOLS
        from pipeline.batch.catch_up_daily import run
        from pipeline.batch.ingest_binance_history import parse_list

        # Logical interval is stable across retries, even when a retry crosses midnight.
        day = get_current_context()["data_interval_end"].date() - timedelta(days=1)
        summary = run(
            parse_list(BATCH_SYMBOLS), parse_list(BATCH_INTERVALS), through=day
        )
        print(
            f"warehouse tail status={summary['status']} "
            f"through={summary['through']} days={summary['days_processed']}"
        )
        return summary

    catch_up_binance()


coinsight_warehouse_daily()
