from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish closed Binance candles to Kafka")
    parser.add_argument(
        "--bootstrap-servers",
        default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    )
    parser.add_argument("--topic", default=os.getenv("KAFKA_TOPIC", "crypto-prices"))
    parser.add_argument("--symbols", default=os.getenv("LIVE_SYMBOLS", "BTC,ETH,SOL"))
    parser.add_argument(
        "--api-url",
        default=os.getenv("BINANCE_API_URL", "https://data-api.binance.vision"),
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=float(os.getenv("LIVE_POLL_SECONDS", "20")),
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=float(os.getenv("LIVE_REQUEST_TIMEOUT", "10")),
    )
    return parser.parse_args()


def main() -> None:
    from kafka import KafkaProducer

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
    last_event_ids: dict[str, str] = {}
    print(f"polling Binance for {', '.join(symbols)}; publishing to {args.topic}", flush=True)

    try:
        while True:
            wait_seconds = args.poll_seconds
            for symbol in symbols:
                try:
                    event = fetch_closed_candle(symbol, args.api_url, args.request_timeout)
                    if last_event_ids.get(symbol) == event["event_id"]:
                        continue
                    producer.send(args.topic, key=symbol, value=event).get(timeout=10)
                    last_event_ids[symbol] = event["event_id"]
                    print(
                        f"published {symbol} candle {event['event_time']} "
                        f"close={event['close_price']}",
                        flush=True,
                    )
                except BinanceBackoffError as error:
                    wait_seconds = max(wait_seconds, error.retry_after)
                    print(str(error), flush=True)
                    break
                except (OSError, URLError, ValueError, json.JSONDecodeError) as error:
                    print(f"could not fetch {symbol}: {error}", flush=True)
            time.sleep(wait_seconds)
    except KeyboardInterrupt:
        print("stopping live producer", flush=True)
    finally:
        producer.flush()
        producer.close()


if __name__ == "__main__":
    main()
