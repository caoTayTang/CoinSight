from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pipeline.stream.kafka_publisher import LivePublisher, load_state, save_state
from pipeline.settings import LIVE


ASSET_NAMES = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "SOL": "Solana",
}


class BinanceBackoffError(Exception):
    def __init__(self, status: int, retry_after: float):
        self.status = status
        self.retry_after = retry_after
        super().__init__(f"Binance returned HTTP {status}; retry in {retry_after:g} seconds")


def normalize_kline(symbol: str, kline: list) -> dict:
    if len(kline) < 8:
        raise ValueError("Binance kline has fewer than 8 fields")

    symbol = symbol.upper()
    timestamp = datetime.fromtimestamp(int(kline[0]) / 1000, tz=timezone.utc).isoformat()
    event = {
        "event_id": f"{symbol}:{timestamp}",
        "symbol": symbol,
        "name": ASSET_NAMES.get(symbol, symbol),
        "event_time": timestamp,
        "open_price": float(kline[1]),
        "high_price": float(kline[2]),
        "low_price": float(kline[3]),
        "close_price": float(kline[4]),
        "volume": float(kline[7]),
        "source": "binance-rest",
    }

    prices = [event[key] for key in ("open_price", "high_price", "low_price", "close_price")]
    if any(price <= 0 for price in prices):
        raise ValueError("kline prices must be positive")
    if event["volume"] < 0:
        raise ValueError("kline volume must be non-negative")
    if event["high_price"] < event["low_price"]:
        raise ValueError("kline high price must not be below low price")
    return event


def fetch_closed_candle(symbol: str, base_url: str, timeout: float) -> dict:
    query = urlencode({"symbol": f"{symbol.upper()}USDT", "interval": "1m", "limit": 2})
    request = Request(
        f"{base_url.rstrip('/')}/api/v3/klines?{query}",
        headers={"User-Agent": "CoinSight/1.0"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as error:
        if error.code not in {418, 429}:
            raise
        retry_after = float(error.headers.get("Retry-After", "60"))
        raise BinanceBackoffError(error.code, retry_after) from error

    if not isinstance(payload, list) or len(payload) < 2:
        raise ValueError("Binance returned fewer than two candles")
    return normalize_kline(symbol, payload[-2])


def live_event(symbol: str, kline: list, source: str) -> dict:
    """Add source and unit metadata to the existing Spark event shape."""
    event = normalize_kline(symbol, kline)
    event.update(
        schema_version=1,
        event_id=f"binance:spot:{symbol.upper()}USDT:1m:{event['event_time']}",
        pair=f"{symbol.upper()}USDT",
        quote_asset="USDT",
        interval="1m",
        close_time=datetime.fromtimestamp(int(kline[6]) / 1000, tz=timezone.utc).isoformat(),
        published_at=datetime.now(timezone.utc).isoformat(),
        volume_base=float(kline[5]),
        trade_count=int(kline[8]) if len(kline) > 8 else None,
        mode="live",
        source=source,
    )
    return event


def normalize_websocket_message(payload: dict) -> dict | None:
    """Only final UTC one-minute candles are observations."""
    message = payload.get("data", payload)
    candle = message.get("k")
    if message.get("e") != "kline" or not isinstance(candle, dict):
        return None
    if candle.get("i") != "1m" or candle.get("x") is not True:
        return None
    pair = str(message.get("s", "")).upper()
    if not pair.endswith("USDT") or candle.get("s") != pair:
        raise ValueError("unexpected Binance pair")
    symbol = pair.removesuffix("USDT")
    kline = [candle[key] for key in ("t", "o", "h", "l", "c", "v", "T", "q", "n")]
    return live_event(symbol, kline, "binance-ws")


def stream_url(symbols: list[str], base_url: str) -> str:
    streams = "/".join(f"{symbol.lower()}usdt@kline_1m" for symbol in symbols)
    return f"{base_url.rstrip('/')}/stream?streams={streams}"


def backfill_candles(symbol: str, after_ms: int, base_url: str, timeout: float):
    """Yield closed REST candles after the last acknowledged one, page by page."""
    next_ms = after_ms + 60_000
    for _ in range(LIVE["backfill_page_limit"]):
        query = urlencode({
            "symbol": f"{symbol.upper()}USDT", "interval": "1m",
            "startTime": next_ms, "limit": LIVE["backfill_page_size"],
        })
        request = Request(f"{base_url.rstrip('/')}/api/v3/klines?{query}")
        with urlopen(request, timeout=timeout) as response:
            rows = json.load(response)
        if not rows:
            return
        for row in rows:
            if int(row[6]) >= int(time.time() * 1000):
                return
            yield live_event(symbol, row, "binance-rest-backfill")
        next_ms = int(rows[-1][0]) + 60_000
        if len(rows) < LIVE["backfill_page_size"]:
            return
    maximum = LIVE["backfill_page_limit"] * LIVE["backfill_page_size"]
    raise RuntimeError(f"backfill exceeded {maximum:,} candles for {symbol}")






def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish closed Binance candles to Kafka")
    parser.add_argument(
        "--bootstrap-servers",
        default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    )
    parser.add_argument("--topic", default=os.getenv("KAFKA_TOPIC", "crypto-prices"))
    parser.add_argument("--symbols", default=",".join(LIVE["symbols"]))
    parser.add_argument(
        "--api-url",
        default=os.getenv("BINANCE_API_URL", "https://data-api.binance.vision"),
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=LIVE["reconnect_seconds"],
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=LIVE["request_timeout_seconds"],
    )
    parser.add_argument("--ws-url", default=os.getenv("BINANCE_WS_URL", "wss://stream.binance.com:9443"))
    parser.add_argument("--state-file", default=os.getenv("LIVE_STATE_FILE", "/state/live-producer.json"))
    return parser.parse_args()


def main() -> None:
    from kafka import KafkaProducer
    from websocket import WebSocketException, create_connection

    args = parse_args()
    symbols = [value.strip().upper() for value in args.symbols.split(",") if value.strip()]
    if not symbols:
        raise ValueError("at least one live symbol is required")

    producer = KafkaProducer(
        bootstrap_servers=args.bootstrap_servers,
        key_serializer=lambda value: value.encode("utf-8"),
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
        retries=5,
        acks="all",
    )
    publisher = LivePublisher(producer, args.topic, Path(args.state_file))
    print(f"streaming closed Binance candles for {', '.join(symbols)} to {args.topic}", flush=True)


    try:
        while True:
            connection = None
            try:
                connection = create_connection(stream_url(symbols, args.ws_url), timeout=120)
                for symbol in symbols:
                    # On the first start, resume from the last two complete minutes.
                    start = publisher.last_open.get(symbol, (int(time.time() * 1000) // 60_000 - 3) * 60_000)
                    for event in backfill_candles(symbol, start, args.api_url, args.request_timeout):
                        publisher.publish(event)
                while True:
                    raw = connection.recv()
                    if not raw:
                        raise ConnectionError("Binance WebSocket closed")
                    event = normalize_websocket_message(json.loads(raw))
                    if event and event["symbol"] in symbols:
                        publisher.publish(event)
            except (OSError, URLError, ValueError, RuntimeError, ConnectionError,
                    WebSocketException) as error:
                print(f"live stream disconnected: {error}; reconnecting", flush=True)
                time.sleep(max(1, args.poll_seconds))
            finally:
                if connection is not None:
                    connection.close()
    except KeyboardInterrupt:
        print("stopping live producer", flush=True)
    finally:
        producer.flush()
        producer.close()


if __name__ == "__main__":
    main()
