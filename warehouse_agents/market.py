"""Bounded, close-only Binance reads for anomaly/drift tools."""

from datetime import datetime, timedelta, timezone
import hashlib, json
import httpx
import pandas as pd
from agents.domain import Candle
from agents.market import API


async def closed_candles(symbol='BTC', frequency='1h', periods=170, cutoff=None):
    symbol = str(symbol).upper()
    if symbol not in ('BTC', 'ETH'):
        raise ValueError('Only BTC and ETH anomaly sources are supported')
    if frequency not in ('1h', '1d'):
        raise ValueError('Frequency must be 1h or 1d')
    if not isinstance(periods, int) or isinstance(periods, bool) or not 20 <= periods <= 1000:
        raise ValueError('Window must contain 20..1000 periods')
    step = timedelta(hours=1) if frequency == '1h' else timedelta(days=1)
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        r = await client.get(API + '/api/v3/time')
        r.raise_for_status()
        server = datetime.fromtimestamp(r.json()['serverTime'] / 1000, timezone.utc)
        if abs((server - datetime.now(timezone.utc)).total_seconds()) > 10:
            raise ValueError('Source clock mismatch')
        observed = (
            datetime.fromisoformat(cutoff.replace('Z', '+00:00'))
            if cutoff
            else server
        )
        if observed.tzinfo is None:
            raise ValueError('Timezone-aware cutoff required')
        observed = observed.astimezone(timezone.utc)
        if observed > server:
            raise ValueError('Future cutoff is not allowed')
        if frequency == '1h':
            end = observed.replace(minute=0, second=0, microsecond=0)
        else:
            end = observed.replace(hour=0, minute=0, second=0, microsecond=0)
        r = await client.get(
            API + '/api/v3/klines',
            params=dict(
                symbol=symbol + 'USDT',
                interval=frequency,
                startTime=int((end - periods * step).timestamp() * 1000),
                endTime=int(end.timestamp() * 1000) - 1,
                limit=periods,
            ),
        )
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list) or len(rows) != periods:
            raise ValueError(f'Missing source {frequency} candles')
        records = []
        for i, v in enumerate(rows):
            expected_open = end - (periods - i) * step
            close_delta_ms = int(step.total_seconds() * 1000) - 1
            if (
                len(v) != 12
                or v[0] != int(expected_open.timestamp() * 1000)
                or v[6] != v[0] + close_delta_ms
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
        symbol=symbol,
        frequency=frequency,
        cutoff=end.isoformat(),
        raw_candles=periods,
        snapshot_sha256=identity,
        observed_at=datetime.now(timezone.utc).isoformat(),
    )


async def closed_window(hours=169, cutoff=None):
    """Compatibility wrapper for the legacy BTC hourly drift model."""
    if not 169 <= hours <= 1000:
        raise ValueError('Window must be 169..1000 hours')
    if cutoff:
        value = datetime.fromisoformat(cutoff.replace('Z', '+00:00'))
        if value.tzinfo is None:
            raise ValueError('Timezone-aware cutoff required')
        value = value.astimezone(timezone.utc)
        if value.minute or value.second or value.microsecond or value > datetime.now(
            timezone.utc
        ).replace(minute=0, second=0, microsecond=0):
            raise ValueError('Only closed hourly cutoffs allowed')
    return await closed_candles('BTC', '1h', hours, cutoff)
