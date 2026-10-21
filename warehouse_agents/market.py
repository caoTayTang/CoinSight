"""Bounded, close-only source reads for anomaly/drift tools."""

from datetime import datetime, timedelta, timezone
import hashlib, json
import httpx
import pandas as pd
from agents.domain import Candle
from agents.market import API


async def closed_window(hours=169, cutoff=None):
    if not 169 <= hours <= 1000:
        raise ValueError('Window must be 169..1000 hours')
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        r = await client.get(API + '/api/v3/time')
        r.raise_for_status()
        server = datetime.fromtimestamp(r.json()['serverTime'] / 1000, timezone.utc)
        if abs((server - datetime.now(timezone.utc)).total_seconds()) > 10:
            raise ValueError('Source clock mismatch')
        end = (
            datetime.fromisoformat(cutoff.replace('Z', '+00:00'))
            if cutoff
            else server.replace(minute=0, second=0, microsecond=0)
        )
        if end.tzinfo is None:
            raise ValueError('Timezone-aware cutoff required')
        end = end.astimezone(timezone.utc)
        if (
            end.minute
            or end.second
            or end.microsecond
            or end > server.replace(minute=0, second=0, microsecond=0)
        ):
            raise ValueError('Only closed hourly cutoffs allowed')
        r = await client.get(
            API + '/api/v3/klines',
            params=dict(
                symbol='BTCUSDT',
                interval='1h',
                startTime=int((end - timedelta(hours=hours)).timestamp() * 1000),
                endTime=int(end.timestamp() * 1000) - 1,
                limit=hours,
            ),
        )
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list) or len(rows) != hours:
            raise ValueError('Missing source hours')
        records = []
        for i, v in enumerate(rows):
            if (
                len(v) != 12
                or v[0] != int((end - timedelta(hours=hours - i)).timestamp() * 1000)
                or v[6] != v[0] + 3599999
            ):
                raise ValueError('Source gap or invalid kline')
            bar = Candle(
                open_time=datetime.fromtimestamp(v[0] / 1000, timezone.utc),
                open_price=v[1],
                high_price=v[2],
                low_price=v[3],
                close_price=v[4],
                volume_quote=v[7],
                trade_count=v[8],
            )
            records.append(bar.model_dump())
    frame = pd.DataFrame(records)
    identity = hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()
    return frame, dict(
        source=API,
        cutoff=end.isoformat(),
        raw_candles=hours,
        snapshot_sha256=identity,
        observed_at=datetime.now(timezone.utc).isoformat(),
    )
