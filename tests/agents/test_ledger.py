import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from pydantic import ValidationError

from agents import ledger

CUTOFF = datetime(2026, 10, 21, 13, tzinfo=timezone.utc)
SERVED = {
    'model_id': 'btc_hourly_frozen_ensemble_v1',
    'bundle_payload_sha256': 'ab8716aeb805ac18f4f5be3da9cf6357aaaf3c907d81a5d707428099b5783725',
    'cutoff': CUTOFF.isoformat(),
    'generated_at': (CUTOFF + timedelta(minutes=2)).isoformat(),
    'reference_close_usdt': 100.0,
    'predicted_log_return': 0.001,
    'snapshot_sha256': 'abc',
    'timing': 'target_hour_in_progress',
}


def test_served_forecast_maps_to_contract():
    rec = ledger.from_served_forecast(SERVED)
    assert rec.model_version == 'ab8716aeb805ac18' and rec.symbol == 'BTC'
    assert rec.target_close - rec.target_open == timedelta(hours=1) and rec.input_sha256 == 'abc'


@pytest.mark.parametrize(
    'change',
    [
        {'cutoff': '2026-10-21T13:30:00+00:00'},  # not an hour boundary
        {'cutoff': '2026-10-21T13:00:00'},  # naive timestamp
        {'generated_at': '2026-10-21T12:00:00+00:00'},  # made before its input existed
        {'predicted_log_return': float('nan')},
        {'symbol': 'DOGE'},
        {'unexpected': 1},
    ],
)
def test_contract_rejects_bad_records(change):
    fields = ledger.from_served_forecast(SERVED).model_dump() | change
    with pytest.raises(ValidationError):
        ledger.ForecastRecord(**fields)


def test_next_run_is_three_minutes_past_the_hour():
    assert ledger.seconds_until_next_run(CUTOFF + timedelta(minutes=1)) == 120
    assert ledger.seconds_until_next_run(CUTOFF + timedelta(minutes=3)) == 3600


@pytest.mark.asyncio
async def test_outcome_only_for_a_closed_kline():
    start = int(CUTOFF.timestamp() * 1000)

    def kline(close_time):
        return httpx.Response(200, json=[[start, '100', '1', '1', '102', '1', close_time]])

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: kline(start + 3_599_999))) as c:
        assert await ledger.fetch_outcome(c, 'BTC', CUTOFF) == (100.0, 102.0)
    future = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp() * 1000)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: kline(future))) as c:
        assert await ledger.fetch_outcome(c, 'BTC', CUTOFF) is None


@pytest.mark.skipif(
    not os.getenv('LEDGER_TEST_DATABASE_URL'), reason='needs a disposable Postgres with migration 006'
)
@pytest.mark.asyncio
async def test_record_is_idempotent_and_scoring_fills_outcomes():
    import psycopg

    with psycopg.connect(os.environ['LEDGER_TEST_DATABASE_URL']) as conn:
        rec = ledger.from_served_forecast(SERVED)
        assert ledger.record(conn, rec) is True and ledger.record(conn, rec) is False
        start = int(CUTOFF.timestamp() * 1000)
        transport = httpx.MockTransport(
            lambda r: httpx.Response(200, json=[[start, '100', '1', '1', '101', '1', start + 3_599_999]])
        )
        async with httpx.AsyncClient(transport=transport) as client:
            assert await ledger.score(conn, client) == 1
        with conn.cursor() as cur:
            cur.execute(
                "select round(abs_error::numeric, 6) from ml.prediction_scored where model_id = %s",
                (rec.model_id,),
            )
            assert float(cur.fetchone()[0]) == pytest.approx(
                abs(0.001 - __import__('math').log(1.01)), abs=1e-6
            )
        conn.rollback()
