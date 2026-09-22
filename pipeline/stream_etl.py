from __future__ import annotations

import os

from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    avg,
    col,
    count,
    from_json,
    stddev_pop,
    sum as sum_,
    to_timestamp,
    window,
)
from pyspark.sql.types import DoubleType, StringType, StructField, StructType


EVENT_SCHEMA = StructType(
    [
        StructField("event_id", StringType(), False),
        StructField("symbol", StringType(), False),
        StructField("name", StringType(), False),
        StructField("event_time", StringType(), False),
        StructField("open_price", DoubleType(), False),
        StructField("high_price", DoubleType(), False),
        StructField("low_price", DoubleType(), False),
        StructField("close_price", DoubleType(), False),
        StructField("volume", DoubleType(), False),
        StructField("source", StringType(), False),
    ]
)


def main() -> None:
    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    topic = os.getenv("KAFKA_TOPIC", "crypto-prices")
    database_url = os.getenv(
        "DATABASE_URL", "postgresql://crypto:crypto@postgres:5432/crypto_dw"
    )
    checkpoint = os.getenv("STREAM_CHECKPOINT", "/checkpoints/live-metrics")

    spark = (
        SparkSession.builder.appName("crypto-live-metrics")
        .config("spark.sql.shuffle.partitions", "2")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    kafka_rows = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", bootstrap_servers)
        .option("subscribe", topic)
        .option("startingOffsets", "earliest")
        .option("failOnDataLoss", "false")
        .load()
    )

    events = (
        kafka_rows.select(from_json(col("value").cast("string"), EVENT_SCHEMA).alias("event"))
        .select("event.*")
        .withColumn("event_time", to_timestamp("event_time"))
        .filter(col("event_id").isNotNull())
        .filter(col("symbol").isNotNull())
        .filter(col("event_time").isNotNull())
        .filter(col("close_price") > 0)
        .filter(col("volume") >= 0)
        .withWatermark("event_time", "1 day")
        .dropDuplicates(["event_id"])
    )

    metrics = (
        events.groupBy(
            "symbol",
            "name",
            window("event_time", "7 days", "1 day"),
        )
        .agg(
            avg("close_price").alias("avg_price_usd"),
            stddev_pop("close_price").alias("price_volatility"),
            sum_("volume").alias("total_volume"),
            count("event_id").alias("event_count"),
        )
    )

    def upsert_batch(batch, batch_id: int) -> None:
        import psycopg2

        rows = batch.collect()
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

        with psycopg2.connect(database_url) as connection:
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
        print(f"stored {len(rows)} metric updates from batch {batch_id}")

    query = (
        metrics.writeStream.outputMode("update")
        .option("checkpointLocation", checkpoint)
        .foreachBatch(upsert_batch)
        .start()
    )
    query.awaitTermination()


if __name__ == "__main__":
    main()
