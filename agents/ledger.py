"""Prospective prediction ledger: record each served forecast when it is made, score it after the hour closes.

  python -m agents.ledger --once     # record the current forecast, then score every closed target hour
  python -m agents.ledger            # same, every hour a few minutes after the close

Any forecasting model integrates by producing a ForecastRecord (docs/model_integration.md). Recording is
idempotent per (model_id, model_version, symbol, cutoff); outcomes come from the same Binance source the
forecasters read, so a model is scored on the data it could have seen.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

log = logging.getLogger(__name__)
BINANCE = os.getenv('BINANCE_API_URL', 'https://data-api.binance.vision').rstrip('/')
PREDICTION_URL = os.getenv('PREDICTION_AGENT_URL', 'http://127.0.0.1:8011')
PAIRS = {'BTC': 'BTCUSDT', 'ETH': 'ETHUSDT', 'SOL': 'SOLUSDT'}


class ForecastRecord(BaseModel):
    """One hourly log-return forecast, as every model must report it."""

    model_config = ConfigDict(extra='forbid')
    model_id: str = Field(min_length=1, max_length=100)
    model_version: str = Field(min_length=1, max_length=100)
    symbol: str = Field(pattern='^(BTC|ETH|SOL)$')
    cutoff: datetime
    generated_at: datetime
    reference_close: float = Field(gt=0, allow_inf_nan=False)
    predicted_log_return: float = Field(allow_inf_nan=False)
    input_sha256: str | None = Field(default=None, max_length=128)
    artifact_sha256: str | None = Field(default=None, max_length=128)
    details: dict = Field(default_factory=dict)

    @field_validator('cutoff', 'generated_at')
    @classmethod
    def utc(cls, value):
        if value.tzinfo is None:
            raise ValueError('timestamps must be timezone-aware')
        return value.astimezone(timezone.utc)

    @model_validator(mode='after')
    def hour_boundary(self):
        if self.cutoff != self.cutoff.replace(minute=0, second=0, microsecond=0):
            raise ValueError('cutoff must be a UTC hour boundary')
        if self.generated_at < self.cutoff - timedelta(minutes=1):
            raise ValueError(
                'generated_at is before the cutoff: the forecast used data it could not have had'
            )
        return self

    @property
    def target_open(self):
        return self.cutoff

    @property
    def target_close(self):
        return self.cutoff + timedelta(hours=1)


def from_served_forecast(result: dict) -> ForecastRecord:
    """Map the forecast service's predict_hourly output (agents/prediction.py) to the ledger contract."""
    return ForecastRecord(
        model_id=result['model_id'],
        model_version=result['bundle_payload_sha256'][:16],
        symbol='BTC',
        cutoff=result['cutoff'],
        generated_at=result['generated_at'],
        reference_close=result['reference_close_usdt'],
        predicted_log_return=result['predicted_log_return'],
        input_sha256=result.get('snapshot_sha256'),
        artifact_sha256=result['bundle_payload_sha256'],
        details={'timing': result.get('timing'), 'source': result.get('source')},
    )


def record(conn, rec: ForecastRecord) -> bool:
    """Insert one forecast; False if this model version already recorded that hour."""
    with conn.cursor() as cur:
        cur.execute(
            """insert into ml.prediction_ledger (model_id, model_version, symbol, cutoff, target_open,
                   target_close, generated_at, reference_close, predicted_log_return, input_sha256,
                   artifact_sha256, details)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               on conflict (model_id, model_version, symbol, cutoff) do nothing""",
            (
                rec.model_id,
                rec.model_version,
                rec.symbol,
                rec.cutoff,
                rec.target_open,
                rec.target_close,
                rec.generated_at,
                rec.reference_close,
                rec.predicted_log_return,
                rec.input_sha256,
                rec.artifact_sha256,
                json.dumps(rec.details, default=str),
            ),
        )
        return cur.rowcount == 1


def pending_targets(conn, limit=200):
    """Closed target hours that some model predicted but that have no outcome yet."""
    with conn.cursor() as cur:
        cur.execute(
            """select distinct l.symbol, l.target_open from ml.prediction_ledger l
               left join ml.prediction_outcome o using (symbol, target_open)
               where o.symbol is null and l.target_close <= now() - interval '1 minute'
               order by l.target_open limit %s""",
            (limit,),
        )
        return cur.fetchall()


async def fetch_outcome(client, symbol, target_open):
    """Open and close of one closed 1h Binance kline, or None if it is not available yet."""
    start = int(target_open.timestamp() * 1000)
    response = await client.get(
        BINANCE + '/api/v3/klines',
        params={'symbol': PAIRS[symbol], 'interval': '1h', 'startTime': start, 'limit': 1},
    )
    response.raise_for_status()
    rows = response.json()
    if not rows or rows[0][0] != start or rows[0][6] >= datetime.now(timezone.utc).timestamp() * 1000:
        return None
    return float(rows[0][1]), float(rows[0][4])


async def score(conn, client) -> int:
    scored = 0
    for symbol, target_open in pending_targets(conn):
        outcome = await fetch_outcome(client, symbol, target_open)
        if outcome is None:
            continue
        with conn.cursor() as cur:
            cur.execute(
                """insert into ml.prediction_outcome (symbol, target_open, open_price, close_price, source)
                   values (%s, %s, %s, %s, %s) on conflict do nothing""",
                (symbol, target_open, *outcome, 'binance-spot-klines-1h'),
            )
        scored += 1
    return scored


async def run_once(conn) -> dict:
    from agents.rpc import call_agent

    summary = {'recorded': False, 'scored': 0, 'error': None}
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
            reply = await call_agent(PREDICTION_URL, {'operation': 'predict_hourly'}, client=client)
        summary['recorded'] = record(conn, from_served_forecast(reply['result']))
    except Exception as exc:  # a failed forecast is logged, never replaced with an invented one
        summary['error'] = type(exc).__name__
        log.warning('ledger.record_failed error=%s', type(exc).__name__)
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        summary['scored'] = await score(conn, client)
    return summary


def seconds_until_next_run(now, minute=3):
    run = now.replace(minute=minute, second=0, microsecond=0)
    if run <= now:
        run += timedelta(hours=1)
    return (run - now).total_seconds()


async def main_async(once: bool):
    import psycopg

    url = os.environ['LEDGER_DATABASE_URL']
    while True:
        with psycopg.connect(url, autocommit=True) as conn:
            log.info('ledger.run %s', await run_once(conn))
        if once:
            return
        await asyncio.sleep(seconds_until_next_run(datetime.now(timezone.utc)))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--once', action='store_true')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    asyncio.run(main_async(parser.parse_args().once))


if __name__ == '__main__':
    main()
