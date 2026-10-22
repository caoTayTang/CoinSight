"""Persist promoted hourly forecasts and their ETL lineage."""
from __future__ import annotations

from datetime import timedelta

from pipeline.decision.types import PredictionResult
from pipeline.settings import DATABASE_URL


class ForecastRepository:
    def __init__(self, database_url: str = DATABASE_URL):
        self.database_url = database_url

    def save(self, prediction: PredictionResult, batch_ids: tuple[int, ...]) -> int:
        import psycopg2

        if not batch_ids:
            raise ValueError("forecast input lineage cannot be empty")
        with psycopg2.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                select forecast_model_key
                from dw.dim_forecast_model
                where run_id = %s and symbol = %s and is_active
                """,
                (prediction.run_id, prediction.symbol),
            )
            model = cursor.fetchone()
            if model is None:
                raise ValueError("forecast model is not the active promoted model for this symbol")
            target_time = prediction.target_time
            latest_input_open_time = target_time - timedelta(hours=1)
            cursor.execute(
                """
                insert into dw.fact_hourly_forecast (
                    symbol, forecast_model_key, latest_input_open_time, cutoff_time, target_time,
                    reference_close_usdt, predicted_log_return, predicted_close_usdt
                ) values (%s,%s,%s,%s,%s,%s,%s,%s)
                on conflict (symbol, target_time, forecast_model_key) do update set
                    reference_close_usdt = excluded.reference_close_usdt,
                    predicted_log_return = excluded.predicted_log_return,
                    predicted_close_usdt = excluded.predicted_close_usdt,
                    generated_at = now()
                returning forecast_id
                """,
                (
                    prediction.symbol, model[0], latest_input_open_time, target_time, target_time,
                    prediction.reference_close_usdt, prediction.predicted_log_return,
                    prediction.predicted_close_usdt,
                ),
            )
            forecast_id = int(cursor.fetchone()[0])
            cursor.executemany(
                """
                insert into meta.forecast_input_lineage (forecast_id, load_batch_id)
                values (%s,%s) on conflict do nothing
                """,
                [(forecast_id, batch_id) for batch_id in batch_ids],
            )
            return forecast_id
