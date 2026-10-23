"""Real schema integration. Requires an explicitly isolated test DB, never the application DB."""

import os
from pathlib import Path
import pytest
from warehouse_agents import tools

DSN = os.getenv('WAREHOUSE_AGENT_TEST_DSN')
pytestmark = pytest.mark.skipif(not DSN, reason='Set WAREHOUSE_AGENT_TEST_DSN to an isolated disposable DB')


@pytest.fixture(scope='module', autouse=True)
def isolated_database():
    if not DSN:
        return
    import psycopg2

    with psycopg2.connect(DSN) as conn:
        with conn.cursor() as c:
            c.execute('select current_database()')
            assert c.fetchone()[0] == 'warehouse_test', 'Refusing to seed any non-test database'
            c.execute('drop schema if exists mart, dw, staging, meta cascade')
            for name in (
                '01_staging_meta.sql',
                '02_dw_schema.sql',
                '03_seed.sql',
                '04_marts.sql',
                '05_warehouse_proof.sql',
            ):
                c.execute((Path('postgres/init') / name).read_text())
            c.execute(
                "insert into meta.etl_batch(pipeline,source_code,status) values ('fixture','binance','success') returning batch_id"
            )
            batch = c.fetchone()[0]
            c.execute(
                "insert into dw.dim_source(source_code,source_name,source_type) values ('binance','Fixture','batch') on conflict do nothing"
            )
            c.execute(
                """insert into dw.fact_ohlcv_hourly(asset_key,date_key,time_key,source_key,open_time,
              open_price,high_price,low_price,close_price,volume_quote,trade_count,batch_id)
              select a.asset_key,to_char(h,'YYYYMMDD')::int,extract(hour from h)::int,s.source_key,h,
                100,110,90,101,1234,10,%s from dw.dim_asset a cross join dw.dim_source s,
                (select date_trunc('hour',now())-interval '1 hour' as h) t
              where a.symbol='BTC' and s.source_code='binance' on conflict do nothing""",
                (batch,),
            )
            c.execute(
                "insert into meta.warehouse_load_report values (%s,'binance','BTC','1h',10,2,3,5,1)", (batch,)
            )
            c.execute(
                "insert into meta.dq_result(batch_id,check_name,target_table,severity,failed_rows,passed) values (%s,'fixture','staging','warning',2,false)",
                (batch,),
            )
    old = os.environ.get('WAREHOUSE_DATABASE_URL')
    os.environ['WAREHOUSE_DATABASE_URL'] = DSN
    yield
    if old is None:
        os.environ.pop('WAREHOUSE_DATABASE_URL', None)
    else:
        os.environ['WAREHOUSE_DATABASE_URL'] = old


@pytest.mark.asyncio
async def test_all_queries_and_known_missing_hour():
    for fn in (
        tools.warehouse_status,
        tools.warehouse_lineage,
        tools.warehouse_reconciliation,
        tools.warehouse_quality,
    ):
        assert (await fn())['status'] == 'available'
    coverage = await tools.warehouse_coverage(hours=2)
    assert coverage['rows'][0]['missing_hours'] == 1
    assert coverage['rows'][0]['observed_hours'] == 1
    reconciliation = await tools.warehouse_reconciliation()
    assert reconciliation['rows'][0]['accounting_delta'] == 0
    quality = await tools.warehouse_quality()
    assert quality['rows'][0]['passed'] is False


@pytest.mark.asyncio
async def test_stale_mart_detected_then_refresh_resolves():
    import psycopg2

    stale = await tools.warehouse_mart_parity()
    assert stale['rows'] and not stale['rows'][0]['aggregates_match']
    row = stale['rows'][0]
    # A missing mart row counts as zero, so the gap is never null.
    assert row['candle_gap'] == row['fact_candles'] - (row['mart_candles'] or 0) > 0
    assert row['volume_gap'] == round(row['fact_volume'] - (row['mart_volume'] or 0), 2)
    with psycopg2.connect(DSN) as conn:
        with conn.cursor() as c:
            c.execute('refresh materialized view mart.mv_hourly_activity')
    fresh = await tools.warehouse_mart_parity()
    assert fresh['rows'][0]['aggregates_match']


def test_connection_rejects_writes():
    import psycopg2

    with pytest.raises(psycopg2.errors.ReadOnlySqlTransaction):
        tools.query("delete from meta.etl_batch where pipeline='fixture'")
