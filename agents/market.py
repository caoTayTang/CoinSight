"""Bounded public REST read: close-only BTC/ETH context, no writes or background jobs."""

from datetime import datetime, timedelta, timezone
import hashlib, json, os
import httpx
from agents.domain import Candle, CandleContext

API = os.getenv('BINANCE_API_URL', 'https://data-api.binance.vision').rstrip('/')


async def load_context(cutoff: str | None = None, *, assets: tuple[str, ...] = ('BTC', 'ETH')) -> dict:
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        response = await client.get(API + '/api/v3/time')
        response.raise_for_status()
        server = datetime.fromtimestamp(response.json()['serverTime'] / 1000, timezone.utc)
        if abs((datetime.now(timezone.utc) - server).total_seconds()) > 10:
            raise ValueError('Exchange/local clock mismatch; refusing stale source time')
        boundary = server.replace(minute=0, second=0, microsecond=0)
        end = datetime.fromisoformat(cutoff.replace('Z', '+00:00')) if cutoff else boundary
        if end.tzinfo is None or end.minute or end.second or end.microsecond or end > boundary:
            raise ValueError('Cutoff must be a past or current aligned UTC hour with all inputs closed')
        end = end.astimezone(timezone.utc)
        # Bound historical requests to the period already evaluated for this model.
        if end < datetime(2026, 1, 1, tzinfo=timezone.utc):
            raise ValueError('This serving prototype accepts cutoffs from 2026 onward')
        result = {}
        for asset in assets:
            response = await client.get(
                API + '/api/v3/klines',
                params=dict(
                    symbol=asset + 'USDT',
                    interval='1h',
                    startTime=int((end - timedelta(hours=169)).timestamp() * 1000),
                    endTime=int(end.timestamp() * 1000) - 1,
                    limit=169,
                ),
            )
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list) or len(rows) != 169:
                raise ValueError(f'{asset}: incomplete source context')
            candles = []
            for row in rows:
                if len(row) != 12 or int(row[6]) != int(row[0]) + 3599999:
                    raise ValueError('Invalid source candle schema')
                candles.append(
                    Candle(
                        open_time=datetime.fromtimestamp(row[0] / 1000, timezone.utc),
                        open_price=row[1],
                        high_price=row[2],
                        low_price=row[3],
                        close_price=row[4],
                        volume_quote=row[7],
                        trade_count=row[8],
                    )
                )
            result[asset] = CandleContext(cutoff=end, candles=candles)
    serialized = {a: c.model_dump(mode='json') for a, c in result.items()}
    identity = hashlib.sha256(
        json.dumps(serialized, sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest()
    return dict(
        contexts=serialized, snapshot_sha256=identity, observed_server_time=server.isoformat(), source=API
    )
