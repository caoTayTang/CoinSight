from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

import pandas as pd


REQUIRED_COLUMNS = {"Date", "Open", "High", "Low", "Close", "Volume", "ticker", "name"}


def load_events(
    path: str | Path,
    symbols: set[str] | None = None,
    limit: int | None = None,
) -> list[dict]:
    frame = pd.read_csv(path)
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")

    frame = frame.rename(
        columns={
            "Date": "event_time",
            "Open": "open_price",
            "High": "high_price",
            "Low": "low_price",
            "Close": "close_price",
            "Volume": "volume",
        }
    )
    frame["symbol"] = frame["ticker"].str.upper().str.removesuffix("-USD")
    frame["event_time"] = pd.to_datetime(frame["event_time"], utc=True, errors="coerce")

    numeric_columns = ["open_price", "high_price", "low_price", "close_price", "volume"]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    if symbols:
        frame = frame[frame["symbol"].isin({symbol.upper() for symbol in symbols})]

    valid = frame["event_time"].notna() & frame["symbol"].notna()
    valid &= (frame[["open_price", "high_price", "low_price", "close_price"]] > 0).all(axis=1)
    valid &= frame["volume"] >= 0
    valid &= frame["high_price"] >= frame["low_price"]
    frame = frame[valid].sort_values(["event_time", "symbol"])

    if limit is not None:
        frame = frame.head(limit)

    events = []
    for row in frame.itertuples(index=False):
        timestamp = row.event_time.isoformat()
        events.append(
            {
                "event_id": f"{row.symbol}:{timestamp}",
                "symbol": row.symbol,
                "name": row.name,
                "event_time": timestamp,
                "open_price": float(row.open_price),
                "high_price": float(row.high_price),
                "low_price": float(row.low_price),
                "close_price": float(row.close_price),
                "volume": float(row.volume),
                "source": "kaggle-replay",
            }
        )
    return events


def publish_events(
    events: list[dict],
    bootstrap_servers: str,
    topic: str,
    interval_seconds: float,
) -> None:
    from kafka import KafkaProducer

    producer = KafkaProducer(
        bootstrap_servers=bootstrap_servers,
        key_serializer=lambda value: value.encode("utf-8"),
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
        retries=5,
    )
    try:
        for event in events:
            producer.send(topic, key=event["symbol"], value=event)
            if interval_seconds:
                time.sleep(interval_seconds)
        producer.flush()
    finally:
        producer.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay Kaggle OHLCV rows into Kafka")
    parser.add_argument(
        "--csv",
        default=os.getenv("REPLAY_CSV", "/data/raw/Crypto_historical_data.csv"),
    )
    parser.add_argument(
        "--bootstrap-servers",
        default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    )
    parser.add_argument("--topic", default=os.getenv("KAFKA_TOPIC", "crypto-prices"))
    parser.add_argument(
        "--symbols",
        default=os.getenv("REPLAY_SYMBOLS", "BTC,ETH,SOL"),
        help="Comma-separated symbols; use an empty value for every asset",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.getenv("REPLAY_INTERVAL_SECONDS", "0.01")),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.getenv("REPLAY_LIMIT", "0")),
        help="Maximum events; zero means no limit",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    symbols = {value.strip().upper() for value in args.symbols.split(",") if value.strip()}
    events = load_events(args.csv, symbols or None, args.limit or None)
    if not events:
        raise ValueError("no valid rows matched the replay settings")

    print(f"replaying {len(events)} events to {args.topic}")
    publish_events(events, args.bootstrap_servers, args.topic, args.interval)
    print("replay complete")


if __name__ == "__main__":
    main()
