"""Evaluate a pooled direction classifier weekly and publish daily probabilities."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from airflow.sdk import dag, get_current_context, task
from pipeline.telemetry import airflow_task
from pipeline.settings import DSS


@dag(
    dag_id="coinsight_direction_daily",
    schedule=DSS["daily_schedule_utc"],
    start_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": DSS["retries"],
                  "retry_delay": timedelta(minutes=DSS["retry_minutes"])},
    tags=["coinsight", "dss"],
)
def coinsight_direction_daily():
    @task
    @airflow_task
    def update_model() -> dict:
        from pipeline.decision.direction_model import train

        if get_current_context()["data_interval_end"].weekday() != 0:
            return {"status": "skipped", "reason": "Weekly evaluation runs on Monday"}
        result = train()
        print(result)
        return result

    @task
    @airflow_task
    def make_prediction(_training_result: dict) -> dict:
        from pipeline.decision.direction_model import predict

        result = predict()
        print(result)
        return result

    make_prediction(update_model())


coinsight_direction_daily()
