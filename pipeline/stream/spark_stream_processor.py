from __future__ import annotations

import os
import json

from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    avg,
    col,
    coalesce,
    count,
    from_json,
    lit,
    max as max_,
    stddev_pop,
    sum as sum_,
    to_timestamp,
    when,
    window,
)
from pyspark.sql.types import DoubleType, StringType, StructField, StructType

from pipeline.settings import STREAM, LIVE
from pipeline.stream.stream_sink_writer import StreamRepository


EVENT_SCHEMA = StructType(
    [
        StructField("event_id", StringType(), False),
        StructField("symbol", StringType(), False),
        StructField("name", StringType(), False),
        StructField("event_time", StringType(), False),
        StructField("close_time", StringType(), True),
        StructField("open_price", DoubleType(), False),
        StructField("high_price", DoubleType(), False),
        StructField("low_price", DoubleType(), False),
        StructField("close_price", DoubleType(), False),
        StructField("volume", DoubleType(), False),
        StructField("source", StringType(), False),
        StructField("mode", StringType(), True),
        StructField("schema_version", StringType(), True),
        StructField("pair", StringType(), True),
        StructField("interval", StringType(), True),
        StructField("quote_asset", StringType(), True),
        StructField("volume_base", DoubleType(), True),
    ]
)


def main() -> None:
    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    topic = os.getenv("KAFKA_TOPIC", "crypto-prices")
    stream_mode = os.getenv("STREAM_MODE", "replay")
    if stream_mode not in {"live", "replay"}:
        raise ValueError("STREAM_MODE must be live or replay")
    database_url = os.getenv(
        "DATABASE_URL", "postgresql://crypto:crypto@postgres:5432/crypto_dw"
    )
    checkpoint = os.getenv("STREAM_CHECKPOINT", "/checkpoints/live-metrics")

    repository = StreamRepository(database_url)

    spark = (
        SparkSession.builder.appName("crypto-live-metrics")
        .config("spark.sql.shuffle.partitions", str(STREAM["shuffle_partitions"]))
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    from pyspark.sql.streaming import StreamingQueryListener
    from pipeline.telemetry import operation

    class ProgressTrace(StreamingQueryListener):
        def onQueryStarted(self, event):
            with operation('spark.query.started', {'spark.query_id': str(event.id),
                                                  'spark.query_name': event.name or 'unnamed'}):
                pass

        def onQueryProgress(self, event):
            progress = json.loads(event.progress.json)
            attributes = {
                'spark.query_id': progress['id'], 'spark.query_name': progress.get('name') or 'unnamed',
                'spark.batch_id': progress['batchId'], 'spark.input_rows': progress['numInputRows'],
                'spark.input_rows_per_second': progress.get('inputRowsPerSecond', 0),
                'spark.processed_rows_per_second': progress.get('processedRowsPerSecond', 0),
                'spark.trigger_duration_ms': progress.get('durationMs', {}).get('triggerExecution', 0),
            }
            watermark = progress.get('eventTime', {}).get('watermark')
            if watermark:
                attributes['spark.watermark'] = watermark
            with operation('spark.query.progress', attributes):
                pass

        def onQueryTerminated(self, event):
            from opentelemetry.trace import Status, StatusCode
            with operation('spark.query.terminated', {'spark.query_id': str(event.id)}) as span:
                if event.exception:
                    span.set_status(Status(StatusCode.ERROR))
                    span.set_attribute('spark.failed', True)

        def onQueryIdle(self, event):
            pass

    spark.streams.addListener(ProgressTrace())

    kafka_rows = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", bootstrap_servers)
        .option("subscribe", topic)
        .option("includeHeaders", "true")
        .option("startingOffsets", "earliest")
        .option("failOnDataLoss", "false")
        .load()
    )

    if stream_mode == "live":
        raw = (
            kafka_rows.select(
                from_json(col("value").cast("string"), EVENT_SCHEMA).alias("event"),
                col("topic"), col("partition"), col("offset"), col("headers"),
            )
            .select("event.*", "topic", "partition", "offset", "headers")
            .filter((col("mode") == "live") & (col("interval") == LIVE["interval"])
                    & (col("quote_asset") == "USDT") & (col("schema_version") == "1"))
            .withColumn("open_time", to_timestamp("event_time"))
            .withColumn("closed_at", to_timestamp("close_time"))
            .filter(col("event_id").isNotNull() & col("open_time").isNotNull()
                    & col("closed_at").isNotNull() & col("symbol").isNotNull()
                    & col("pair").isNotNull() & col("volume_base").isNotNull()
                    & (col("open_price") > 0) & (col("close_price") > 0)
                    & (col("volume") >= 0) & (col("volume_base") >= 0))
        )


        (
            raw.writeStream.queryName("coinsight_raw_candles").outputMode("append")
            .option("checkpointLocation", checkpoint + "-raw-v1")
            .foreachBatch(repository.persist_candles).start()
        )

    events = (
        kafka_rows.select(from_json(col("value").cast("string"), EVENT_SCHEMA).alias("event"))
        .select("event.*")
        .withColumn("mode", coalesce(col("mode"), when(col("source") == "kaggle-replay", lit("replay"))))
        .filter(col("mode") == stream_mode)
        .withColumn("event_time", to_timestamp("event_time"))
        .withColumn("observed_at", coalesce(to_timestamp("close_time"), col("event_time")))
        .filter(col("event_id").isNotNull())
        .filter(col("symbol").isNotNull())
        .filter(col("event_time").isNotNull())
        .filter(col("close_price") > 0)
        .filter(col("volume") >= 0)
        .withWatermark("event_time", STREAM["watermark"])
        .dropDuplicates(["event_id"])
        # REST backfill and WebSocket deliver the same market series. Keep their
        # transport in Kafka, but aggregate them under one market source.
        .withColumn(
            "source",
            when(col("source").isin("binance-ws", "binance-rest-backfill"), lit("binance-spot"))
            .otherwise(col("source")),
        )
    )

    metrics = (
        events.groupBy(
            "symbol",
            "name",
            "source",
            "mode",
            window("event_time", STREAM["metric_window"], STREAM["metric_slide"]),
        )
        .agg(
            avg("close_price").alias("avg_price_usd"),
            stddev_pop("close_price").alias("price_volatility"),
            sum_("volume").alias("total_volume"),
            count("event_id").alias("event_count"),
            max_("observed_at").alias("last_event_time"),
        )
    )


    (
        metrics.writeStream.queryName("coinsight_rolling_metrics").outputMode("update")
        .option("checkpointLocation", checkpoint)
        .foreachBatch(repository.upsert_batch)
        .start()
    )
    spark.streams.awaitAnyTermination()


if __name__ == "__main__":
    main()
