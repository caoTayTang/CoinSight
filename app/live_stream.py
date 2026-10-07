"""Push committed live warehouse changes to browser WebSocket clients."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
import re
import select
import time

from fastapi import WebSocket, WebSocketDisconnect


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://crypto:crypto@localhost:5432/crypto_dw")
CHANNEL = "coinsight_live"
SYMBOL_PATTERN = re.compile(r"[A-Z0-9]{2,20}\Z")


def connect_listener():
    import psycopg2

    connection = psycopg2.connect(DATABASE_URL)
    connection.set_session(autocommit=True)
    with connection.cursor() as cursor:
        cursor.execute(f"listen {CHANNEL}")
    return connection


def wait_for_change(connection, timeout: float = 25.0) -> set[str]:
    if not select.select([connection], [], [], timeout)[0]:
        return set()
    connection.poll()
    symbols = {notification.payload for notification in connection.notifies}
    connection.notifies.clear()
    return symbols


def live_payload(symbol: str) -> dict:
    # Import after route registration so the existing API remains the source of
    # truth for freshness, quality, and provenance in both HTTP and WebSocket.
    try:
        from . import api
    except ImportError:
        import api

    return {
        "type": "live.snapshot",
        "symbol": symbol,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "summary": api.live_summary(symbol).model_dump(mode="json"),
        "metric": api.live_metric_v1(symbol).model_dump(mode="json"),
    }


async def stream_live(websocket: WebSocket, symbol: str) -> None:
    symbol = symbol.upper()
    if not SYMBOL_PATTERN.fullmatch(symbol):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    connection = None
    receiver = None
    try:
        # LISTEN must be committed before the initial read. Any commit between
        # that read and the wait will still produce a notification.
        connection = await asyncio.to_thread(connect_listener)
        await websocket.send_json(await asyncio.to_thread(live_payload, symbol))
        receiver = asyncio.create_task(websocket.receive())
        last_sent = time.monotonic()
        while True:
            # select() waits for PG socket activity without querying the DB.
            # A short timeout also lets us close promptly when the browser leaves.
            changed = await asyncio.to_thread(wait_for_change, connection, 1.0)
            if receiver.done():
                message = receiver.result()
                if message["type"] == "websocket.disconnect":
                    break
                receiver = asyncio.create_task(websocket.receive())
            if symbol in changed:
                await websocket.send_json(await asyncio.to_thread(live_payload, symbol))
                last_sent = time.monotonic()
            elif time.monotonic() - last_sent >= 25:
                await websocket.send_json({
                    "type": "heartbeat",
                    "symbol": symbol,
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                })
                last_sent = time.monotonic()
    except WebSocketDisconnect:
        pass
    finally:
        if receiver is not None:
            receiver.cancel()
        if connection is not None:
            await asyncio.to_thread(connection.close)
