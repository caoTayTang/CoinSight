"""PostgreSQL sinks for Spark micro-batches."""
from __future__ import annotations
from opentelemetry import trace
from pipeline.telemetry import traced, link_kafka_rows, current_trace_id


class StreamRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    @traced("spark.candles.commit")
    def persist_candles(self, batch, batch_id: int) -> None:
        import psycopg2
        from psycopg2.extras import execute_values

        rows = batch.collect()
        trace.get_current_span().set_attribute("pipeline.rows_received", len(rows))
        if not rows:
            return
        link_kafka_rows(rows)
        values = [(
            row.event_id, row.symbol, row.pair, row.open_time, row.closed_at,
            row.open_price, row.high_price, row.low_price, row.close_price,
            row.volume_base, row.volume, row.source, row.topic, row.partition,
            row.offset,
        ) for row in rows]
        with psycopg2.connect(self.database_url) as connection, connection.cursor() as cursor:
            execute_values(cursor,
                "insert into dw.dim_asset (symbol, name) values %s "
                "on conflict (symbol) do nothing",
                list({(row.symbol, row.name) for row in rows}),
            )
            execute_values(cursor,
                """insert into dw.fact_candle_minute_live (
                    event_id, symbol, pair, open_time, close_time, open_price,
                    high_price, low_price, close_price, volume_base, volume_quote,
                    transport, kafka_topic, kafka_partition, kafka_offset
                ) values %s on conflict (pair, open_time) do nothing""",
                values,
            )
        print(f"stored {len(values)} raw candles from batch {batch_id} trace={current_trace_id()}", flush=True)
    @traced("spark.metrics.commit")
    def upsert_batch(self, batch, batch_id: int) -> None:
        import psycopg2

        rows = batch.collect()
        trace.get_current_span().set_attribute("pipeline.rows_received", len(rows))
        if not rows:
            return

        assets = [(row.symbol, row.name) for row in rows]
        metric_rows = [
            (
                row.symbol,
                row.window.start,
                row.window.end,
                float(row.avg_price_usd),
                float(row.price_volatility or 0.0),
                float(row.total_volume),
                int(row.event_count),
            )
            for row in rows
        ]
        sourced_rows = [
            (
                row.symbol, row.mode, row.source, row.window.start, row.window.end,
                float(row.avg_price_usd), float(row.price_volatility or 0.0),
                float(row.total_volume), int(row.event_count),
                row.last_event_time,
            )
            for row in rows
        ]

        with psycopg2.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into dim_asset (symbol, name) values (%s, %s)
                    on conflict (symbol) do update set name = excluded.name
                    """,
                    assets,
                )
                cursor.executemany(
                    """
                    insert into fact_live_metric (
                        symbol, window_start, window_end, avg_price_usd,
                        price_volatility, total_volume, event_count
                    ) values (%s, %s, %s, %s, %s, %s, %s)
                    on conflict (symbol, window_start, window_end) do update set
                        avg_price_usd = excluded.avg_price_usd,
                        price_volatility = excluded.price_volatility,
                        total_volume = excluded.total_volume,
                        event_count = excluded.event_count,
                        updated_at = now()
                    """,
                    metric_rows,
                )
                cursor.executemany(
                    """
                    insert into dw.fact_stream_metric_v1 (
                        symbol, mode, source, window_start, window_end,
                        avg_price_usd, price_volatility, total_volume,
                        event_count, last_event_time
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (symbol, mode, source, window_start, window_end)
                    do update set avg_price_usd = excluded.avg_price_usd,
                        price_volatility = excluded.price_volatility,
                        total_volume = excluded.total_volume,
                        event_count = excluded.event_count,
                        last_event_time = excluded.last_event_time, updated_at = now()
                    """,
                    sourced_rows,
                )
        print(f"stored {len(rows)} metric updates from batch {batch_id} trace={current_trace_id()}", flush=True)
