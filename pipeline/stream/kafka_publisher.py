"""Kafka publishing and durable per-symbol progress for the live feed."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from pipeline.telemetry import operation, kafka_headers, current_trace_id

def load_state(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    return {symbol: int(value) for symbol, value in json.loads(path.read_text()).items()}


def save_state(path: Path, state: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".tmp")
    partial.write_text(json.dumps(state, sort_keys=True))
    partial.replace(path)


class LivePublisher:
    def __init__(self, producer, topic: str, state_path: Path):
        self.producer = producer
        self.topic = topic
        self.state_path = state_path
        self.last_open = load_state(state_path)

    def publish(self, event: dict) -> None:
        open_ms = int(datetime.fromisoformat(event["event_time"]).timestamp() * 1000)
        if open_ms <= self.last_open.get(event["symbol"], -1):
            return
        with operation('kafka.publish', {'messaging.system': 'kafka', 'messaging.destination.name': self.topic,
                                         'market.symbol': event['symbol'], 'market.event_id': event['event_id']}) as span:
            metadata = self.producer.send(self.topic, key=event["pair"], value=event,
                                          headers=kafka_headers()).get(timeout=10)
            trace_id = current_trace_id()
            if metadata is not None:
                span.set_attribute('messaging.partition', metadata.partition)
                span.set_attribute('messaging.offset', metadata.offset)
        self.last_open[event["symbol"]] = open_ms
        save_state(self.state_path, self.last_open)
        print(f"published {event['pair']} {event['event_time']} via {event['source']} trace={trace_id}", flush=True)
