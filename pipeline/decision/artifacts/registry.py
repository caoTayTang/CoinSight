"""Optional PostgreSQL registry for offline training/evaluation metadata."""
from __future__ import annotations

import json

from pipeline.settings import DATABASE_URL


class ForecastRunRegistry:
    def __init__(self, database_url: str = DATABASE_URL):
        self.database_url = database_url

    def register_run(self, manifest: dict) -> None:
        import psycopg2

        with psycopg2.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                insert into meta.forecast_training_run (
                    run_id, symbol, model_type, snapshot_id, feature_version,
                    status, seed, artifact_manifest
                ) values (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                on conflict (run_id) do update set
                    status = excluded.status,
                    artifact_manifest = excluded.artifact_manifest,
                    finished_at = now()
                """,
                (
                    manifest["run_id"], manifest["symbol"], manifest["model_type"],
                    manifest["snapshot_id"], manifest["feature_version"],
                    manifest["status"], manifest["seed"], json.dumps(manifest),
                ),
            )

    def record_metrics(self, run_id: str, split: str, metrics: dict, period: str = "all") -> None:
        import psycopg2

        with psycopg2.connect(self.database_url) as connection, connection.cursor() as cursor:
            for name, value in metrics.items():
                if value is None or name == "sample_count":
                    continue
                cursor.execute(
                    """
                    insert into meta.forecast_evaluation
                        (run_id, split, period, metric_name, metric_value)
                    values (%s,%s,%s,%s,%s)
                    on conflict (run_id, split, period, metric_name)
                    do update set metric_value = excluded.metric_value, evaluated_at = now()
                    """,
                    (run_id, split, period, name, float(value)),
                )

    def promote(self, run_id: str, artifact_sha256: str, horizon_hours: int = 1) -> int:
        """Atomically make a tested run the sole active model for its symbol/horizon."""
        import psycopg2

        with psycopg2.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                select symbol, model_type, status
                from meta.forecast_training_run where run_id = %s for update
                """,
                (run_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"forecast run is not registered: {run_id}")
            symbol, model_type, status = row
            if status != "tested":
                raise ValueError("only a tested forecast run can be promoted")
            cursor.execute(
                """
                update dw.dim_forecast_model set is_active = false
                where symbol = %s and horizon_hours = %s and is_active
                """,
                (symbol, horizon_hours),
            )
            cursor.execute(
                """
                insert into dw.dim_forecast_model (
                    run_id, symbol, model_type, horizon_hours,
                    artifact_sha256, is_active, promoted_at
                ) values (%s,%s,%s,%s,%s,true,now())
                on conflict (run_id) do update set
                    artifact_sha256 = excluded.artifact_sha256,
                    is_active = true,
                    promoted_at = now()
                returning forecast_model_key
                """,
                (run_id, symbol, model_type, horizon_hours, artifact_sha256),
            )
            model_key = int(cursor.fetchone()[0])
            cursor.execute(
                """
                update meta.forecast_training_run
                set status = 'promoted', finished_at = now() where run_id = %s
                """,
                (run_id,),
            )
            return model_key
