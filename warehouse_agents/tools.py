"""Allowlisted, read-only tools. Unavailable evidence is explicit, never replaced with fake health."""

from datetime import datetime, timezone
from decimal import Decimal
import asyncio, os
from urllib.parse import quote
import httpx
from warehouse_agents.peer import call_agent
from warehouse_agents.telemetry import traced
from agents.domain import CandleContext, detect_anomalies
from warehouse_agents.anomaly import features, score, load_model, population_shift, read_record, MODEL_DIR
from warehouse_agents.market import closed_window


def peer_headers():
    token = os.getenv('WAREHOUSE_AGENT_TOKEN', '')
    return {'Authorization': 'Bearer ' + token} if token else {}


def stamped(data):
    return dict(observed_at=datetime.now(timezone.utc).isoformat(), **data)


def safe_value(v):
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


@traced('warehouse.query', {'db.system.name': 'postgresql', 'db.operation.name': 'SELECT'})
def query(sql, params=()):
    import psycopg2

    # Never take SQL or identifiers from the LLM. Restrict every transaction to SELECT.
    uri = os.getenv('WAREHOUSE_DATABASE_URL', 'postgresql://crypto:crypto@127.0.0.1:5432/crypto_dw')
    with psycopg2.connect(uri, connect_timeout=3) as conn:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor() as cur:
            cur.execute("set local timezone = 'UTC'")
            cur.execute("set local statement_timeout = '4000ms'")
            cur.execute(sql, params)
            return [
                {col.name: safe_value(v) for col, v in zip(cur.description, row)} for row in cur.fetchall()
            ]


async def sql_tool(name, sql, params=()):
    try:
        return stamped(dict(status='available', tool=name, rows=await asyncio.to_thread(query, sql, params)))
    except Exception as e:
        return stamped(
            dict(
                status='unavailable',
                tool=name,
                error_type=type(e).__name__,
                reason='Warehouse could not be queried with the configured read-only connection.',
            )
        )


@traced('tool.warehouse_status')
async def warehouse_status():
    return await sql_tool(
        'warehouse_status',
        """select pipeline,status,count(*) as batches,max(started_at) as latest_started,
        max(finished_at) as latest_finished from meta.etl_batch where started_at >= now()-interval '7 days'
        group by pipeline,status order by latest_started desc limit 30""",
    )


@traced('tool.warehouse_coverage')
async def warehouse_coverage(symbol='BTC', hours=48, source_code='binance'):
    if symbol not in ('BTC', 'ETH', 'SOL') or not isinstance(hours, int) or not 1 <= hours <= 168:
        raise ValueError('Unsupported symbol/window')
    return await sql_tool(
        'warehouse_coverage',
        """with expected as (
      select generate_series(date_trunc('hour',now())-(%s * interval '1 hour'),date_trunc('hour',now())-interval '1 hour',interval '1 hour') as open_time
    ), actual as (
      select f.open_time,count(*) as n from dw.fact_ohlcv_hourly f join dw.dim_asset a using(asset_key)
      join dw.dim_source s using(source_key) where a.symbol=%s and s.source_code=%s
      and f.open_time>=date_trunc('hour',now())-(%s * interval '1 hour') group by f.open_time
    ) select count(*) as expected_hours,count(a.open_time) as observed_hours,
      count(*) filter(where a.open_time is null) as missing_hours,
      max(e.open_time) filter(where a.open_time is not null) as last_observed_open,
      count(*) filter(where a.n>1) as duplicated_grain_hours from expected e left join actual a using(open_time)""",
        (hours, symbol, source_code, hours),
    )


@traced('tool.warehouse_lineage')
async def warehouse_lineage(symbol='BTC'):
    if symbol not in ('BTC', 'ETH', 'SOL'):
        raise ValueError('Unsupported asset')
    return await sql_tool(
        'warehouse_lineage',
        """select symbol,candle_interval,open_time,batch_id,extract_batch_id,
      source_file,sha256,source_url from meta.v_fact_archive_lineage where symbol=%s
      and candle_interval='1h' order by open_time desc limit 5""",
        (symbol,),
    )


@traced('tool.warehouse_reconciliation')
async def warehouse_reconciliation():
    return await sql_tool(
        'warehouse_reconciliation',
        """select r.batch_id,r.symbol,r.candle_interval,
      r.staging_rows,r.rejected_rows,r.duplicate_rows,r.accepted_rows,r.changed_rows,
      r.staging_rows-(r.rejected_rows+r.duplicate_rows+r.accepted_rows) as accounting_delta,
      b.status as load_status,b.finished_at from meta.warehouse_load_report r
      join meta.etl_batch b using(batch_id) order by r.batch_id desc limit 20""",
    )


@traced('tool.warehouse_quality')
async def warehouse_quality():
    return await sql_tool(
        'warehouse_quality',
        """select batch_id,check_name,target_table,severity,failed_rows,passed,checked_at
      from meta.dq_result where checked_at>=now()-interval '7 days' order by checked_at desc limit 30""",
    )


@traced('tool.warehouse_mart_parity')
async def warehouse_mart_parity():
    return await sql_tool(
        'warehouse_mart_parity',
        """with fact as (
      select s.source_code,a.symbol,count(*) as candles,sum(f.volume_quote) as volume_usd
      from dw.fact_ohlcv_hourly f join dw.dim_asset a using(asset_key) join dw.dim_source s using(source_key)
      group by s.source_code,a.symbol
    ), mart as (
      select source_code,symbol,candles,volume_usd from mart.mv_hourly_activity
      where symbol<>'ALL' and hour_utc is null and trading_session='ALL'
    ) select coalesce(f.source_code,m.source_code) as source_code,coalesce(f.symbol,m.symbol) as symbol,
      f.candles as fact_candles,m.candles as mart_candles,f.volume_usd as fact_volume,m.volume_usd as mart_volume,
      coalesce(f.candles=m.candles and abs(f.volume_usd-m.volume_usd)<0.01,false) as aggregates_match
      from fact f full join mart m using(source_code,symbol) order by source_code,symbol limit 30""",
    )


@traced('tool.airflow_status')
async def airflow_status(dag_id=None):
    base = os.getenv('AIRFLOW_API_URL', 'http://127.0.0.1:8081').rstrip('/')
    token = os.getenv('AIRFLOW_API_TOKEN')
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    path = '/api/v2/dags/' + quote(dag_id, safe='') + '/dagRuns' if dag_id else '/api/v2/dags'
    params = {'limit': 10, 'order_by': '-run_after'} if dag_id else {'limit': 20}
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as c:
            r = await c.get(base + path, params=params, headers=headers)
            if r.status_code in (401, 403):
                return stamped(
                    dict(
                        status='unavailable',
                        reason='Airflow API authentication required; configure AIRFLOW_API_TOKEN.',
                        http_status=r.status_code,
                    )
                )
            r.raise_for_status()
            body = r.json()
        # Read-only JSON endpoints; avoid returning arbitrary task log text to the LLM.
        fields = (
            ('dag_id', 'is_paused', 'is_stale', 'last_parsed_time')
            if not dag_id
            else ('dag_id', 'dag_run_id', 'state', 'start_date', 'end_date', 'run_after')
        )
        rows = [{k: v.get(k) for k in fields} for v in body.get('dag_runs' if dag_id else 'dags', [])]
        return stamped(dict(status='available', dag_id=dag_id, rows=rows))
    except Exception as e:
        return stamped(
            dict(
                status='unavailable',
                error_type=type(e).__name__,
                reason='Airflow public API is not reachable with configured connection.',
            )
        )


@traced('tool.service_health')
async def service_health():
    endpoints = {
        'forecast': os.getenv('FORECAST_AGENT_URL', 'http://127.0.0.1:8011') + '/health',
        'warehouse_api': os.getenv('WAREHOUSE_API_URL', 'http://127.0.0.1:8000') + '/health',
        'traces': os.getenv('JAEGER_URL', 'http://127.0.0.1:16686') + '/',
    }

    async def check(name, url):
        try:
            async with httpx.AsyncClient(timeout=3, follow_redirects=False) as c:
                r = await c.get(url)
            return dict(
                service=name, status='reachable' if r.is_success else 'http_error', http_status=r.status_code
            )
        except Exception as e:
            return dict(service=name, status='unreachable', error_type=type(e).__name__)

    return stamped(
        dict(
            status='available',
            checks=await asyncio.gather(*(check(k, v) for k, v in endpoints.items())),
            scope='HTTP reachability only; no Docker control or Kafka-lag metric is inferred.',
        )
    )


MARKET_VIEWS = {
    'snapshot': '/v1/assets/{symbol}/snapshot',
    'live_summary': '/v1/assets/{symbol}/live-summary',
    'daily_direction': '/v1/assets/{symbol}/prediction',
    'model_evaluation': '/v1/model/evaluation',
}


@traced('tool.market_data')
async def market_data(view, symbol='BTC'):
    """Read-only market views from the warehouse API: latest daily candle, last 15 one-minute candles,
    the daily direction model and its evaluation. Unavailable responses are reported, never filled in."""
    url = os.getenv('WAREHOUSE_API_URL', 'http://127.0.0.1:8000') + MARKET_VIEWS[view].format(symbol=symbol)
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as c:
            r = await c.get(url)
        if not r.is_success:
            return stamped(dict(status='unavailable', view=view, symbol=symbol, http_status=r.status_code))
        return stamped(dict(status='available', view=view, symbol=symbol, data=r.json()))
    except Exception as e:
        return stamped(dict(status='unavailable', view=view, symbol=symbol, error_type=type(e).__name__))


@traced('tool.predict_hourly')
async def predict_hourly(cutoff=None):
    result = await call_agent(
        os.getenv('FORECAST_AGENT_URL', 'http://127.0.0.1:8011'),
        dict(operation='predict_hourly', cutoff=cutoff),
    )
    return stamped(dict(status='available', **result))


@traced('tool.detect_market_anomaly')
async def detect_market_anomaly(cutoff=None):
    raw, source = await closed_window(cutoff=cutoff)
    trained = await asyncio.to_thread(score, raw)
    baseline = detect_anomalies(CandleContext(cutoff=source['cutoff'], candles=raw.to_dict('records')))
    return stamped(dict(status='available', source=source, trained=trained, mad_baseline=baseline))


@traced('tool.model_health')
async def model_health(cutoff=None):
    raw, source = await closed_window(hours=336, cutoff=cutoff)
    current = features(raw).dropna()
    _, meta = load_model()
    shift = population_shift(current, meta['reference_profile'])
    offline = read_record(MODEL_DIR / 'report.json')
    return stamped(
        dict(
            status='available',
            source=source,
            window_feature_rows=len(current),
            data_drift=shift,
            reference_scope='Isolation Forest anomaly features, not CatBoost forecast inputs',
            reference_model_sha256=meta['model_sha256'],
            reference_period=meta.get('train_period', 'See frozen anomaly plan.json'),
            drift_watch=any(v['heuristic_drift_flag'] for v in shift),
            threshold_interpretation='PSI >= .25 is a heuristic watch flag, not a significance test or proof of model failure.',
            performance_status='No prospective forecast ledger is attached; do not claim current MAE from drift.',
            frozen_forecast_test=dict(
                relative_mae=0.9970170386973569, n=6984, status='retrospective 2026-01-01..2026-10-18'
            ),
            anomaly_test=dict(alert_rate=offline['test_alert_rate'], n=offline['test_n'], accuracy=None),
        )
    )


@traced('tool.investigate_warehouse')
async def investigate_warehouse(question, symbol='BTC'):
    async with httpx.AsyncClient(timeout=180, follow_redirects=False, headers=peer_headers()) as client:
        from warehouse_agents.run_context import CURRENT_MODEL

        # Operations answers with the model the user picked, not the router's default.
        payload = dict(question=question, symbol=symbol)
        if CURRENT_MODEL.get():
            payload['model'] = CURRENT_MODEL.get()
        reply = await call_agent(
            os.getenv('OPERATIONS_AGENT_URL', 'http://127.0.0.1:8022'), payload, client=client
        )
    return stamped(dict(status='available', **reply))


@traced('tool.save_memory')
async def save_memory(text):
    """Keep a short note for this user across conversations (warehouse_agents/memory.py)."""
    from warehouse_agents import memory
    from warehouse_agents.run_context import CURRENT_USER

    user = CURRENT_USER.get()
    if not user:
        return stamped(dict(status='unavailable', reason='No signed-in user for this conversation.'))
    try:
        key = await memory.save(user, text)
    except (ValueError, RuntimeError) as exc:
        return stamped(dict(status='unavailable', reason=str(exc)))
    return stamped(dict(status='available', saved=True, id=key, text=' '.join(str(text).split())))


@traced('tool.load_skill')
async def load_skill(name):
    """Instructions for one kind of request (warehouse_agents/skills); not evidence of current state."""
    from warehouse_agents.skills import load

    return stamped(load(name))


@traced('tool.search_traces')
async def search_traces(service='coinsight-api', lookback_minutes=30, limit=5):
    from warehouse_agents.traces import search_traces as search

    try:
        return stamped(await search(service, lookback_minutes, limit))
    except Exception as exc:
        return stamped(
            dict(
                status='unavailable',
                error_type=type(exc).__name__,
                reason='Jaeger trace search unavailable; no trace evidence was invented.',
            )
        )


@traced('tool.inspect_trace')
async def inspect_trace(trace_id):
    from warehouse_agents.traces import inspect_trace as inspect

    try:
        return stamped(await inspect(trace_id))
    except Exception as exc:
        return stamped(
            dict(
                status='unavailable',
                error_type=type(exc).__name__,
                reason='Trace unavailable or exceeded bounds; no root cause was inferred.',
            )
        )
