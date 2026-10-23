"""Allowlisted, read-only tools. Unavailable evidence is explicit, never replaced with fake health."""

from datetime import datetime, timezone
from decimal import Decimal
import asyncio, math, os, re, time
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
      coalesce(f.candles,0)-coalesce(m.candles,0) as candle_gap,
      round(coalesce(f.volume_usd,0)-coalesce(m.volume_usd,0),2) as volume_gap,
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


STREAM_STALE_SECONDS = 300


async def _http_check(component, url, parse=None, headers=None):
    """One HTTP probe: reachable or not, with latency; `parse` turns a 200 body into status and detail."""
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=4, follow_redirects=False) as c:
            r = await c.get(url, headers=headers or {})
        latency = round((time.perf_counter() - started) * 1000)
        if not r.is_success:
            return dict(component=component, status='degraded', http_status=r.status_code, latency_ms=latency)
        status, detail = parse(r.json()) if parse else ('ok', None)
        return dict(component=component, status=status, latency_ms=latency, detail=detail)
    except Exception as e:
        return dict(component=component, status='unreachable', error_type=type(e).__name__)


def _airflow(body):
    parts = {k: (v or {}).get('status') for k, v in body.items() if isinstance(v, dict)}
    return ('ok' if parts and all(v == 'healthy' for v in parts.values()) else 'degraded'), parts


def _kafka(clusters):
    detail = [
        dict(
            name=c.get('name'),
            status=c.get('status'),
            brokers=c.get('brokerCount'),
            topics=c.get('topicCount'),
        )
        for c in clusters
    ]
    return (
        'ok' if detail and all(c['status'] == 'ONLINE' and c['brokers'] for c in detail) else 'degraded'
    ), detail


async def _postgres():
    started = time.perf_counter()
    try:
        await asyncio.to_thread(query, 'select 1')
        return dict(
            component='postgres', status='ok', latency_ms=round((time.perf_counter() - started) * 1000)
        )
    except Exception as e:
        return dict(component='postgres', status='unreachable', error_type=type(e).__name__)


async def _stream():
    """Spark streaming judged by its output: how old the newest live candle and stream metric are."""
    try:
        rows = await asyncio.to_thread(
            query,
            """select 'minute_candles' as output, symbol, max(close_time) as latest,
                      extract(epoch from now() - max(close_time))::int as age_seconds
               from dw.fact_candle_minute_live group by symbol
               union all
               select 'stream_metrics', symbol, max(last_event_time),
                      extract(epoch from now() - max(last_event_time))::int
               from dw.fact_stream_metric_v1 group by symbol
               order by 1, 2""",
        )
    except Exception as e:
        return dict(component='stream', status='unknown', error_type=type(e).__name__)
    if not rows:
        return dict(component='stream', status='degraded', detail='No live stream output in the warehouse.')
    stale = [r for r in rows if r['age_seconds'] is None or r['age_seconds'] > STREAM_STALE_SECONDS]
    return dict(
        component='stream',
        status='degraded' if stale else 'ok',
        detail=[{k: str(v) if k == 'latest' else v for k, v in r.items()} for r in rows],
        stale_after_seconds=STREAM_STALE_SECONDS,
    )


@traced('tool.service_health')
async def service_health():
    """Probe every pipeline component the agent can see: HTTP services, Airflow, Kafka, Postgres, stream freshness."""
    airflow = os.getenv('AIRFLOW_API_URL', 'http://127.0.0.1:8081').rstrip('/')
    token = os.getenv('AIRFLOW_API_TOKEN')
    checks = await asyncio.gather(
        _http_check('warehouse_api', os.getenv('WAREHOUSE_API_URL', 'http://127.0.0.1:8000') + '/health'),
        _http_check('forecast', os.getenv('FORECAST_AGENT_URL', 'http://127.0.0.1:8011') + '/health'),
        _http_check('traces', os.getenv('JAEGER_URL', 'http://127.0.0.1:16686') + '/'),
        _http_check(
            'airflow',
            airflow + '/api/v2/monitor/health',
            _airflow,
            {'Authorization': 'Bearer ' + token} if token else None,
        ),
        _http_check('kafka', os.getenv('KAFKA_UI_URL', 'http://127.0.0.1:8080') + '/api/clusters', _kafka),
        _postgres(),
        _stream(),
    )
    counts = {s: sum(c['status'] == s for c in checks) for s in ('ok', 'degraded', 'unreachable', 'unknown')}
    return stamped(
        dict(
            status='available',
            summary=counts,
            checks=list(checks),
            scope='Observed from the agent: HTTP reachability, Airflow and Kafka status APIs, a Postgres query and '
            'the age of the stream\'s newest output. Unreachable does not prove a container stopped; no Docker access.',
        )
    )


MARKET_VIEWS = {
    'snapshot': '/v1/assets/{symbol}/snapshot',
    'live_summary': '/v1/assets/{symbol}/live-summary',
    'daily_direction': '/v1/assets/{symbol}/prediction',
    'model_evaluation': '/v1/model/evaluation',
}


def compact_market(view, envelope):
    """Keep tool evidence small: the live summary's 60 raw minute candles become the window's high, low and the
    last 15 closes. Small free-tier rate limits count every evidence token on the next model call."""
    data = envelope.get('data')
    if view != 'live_summary' or not isinstance(data, dict) or not data.get('candles'):
        return envelope
    candles = data.pop('candles')
    data.update(
        candles_in_window=len(candles),
        window_high_usdt=max(c['high_price_usdt'] for c in candles),
        window_low_usdt=min(c['low_price_usdt'] for c in candles),
        recent_closes=[
            {'open_time': c['open_time'], 'close_usdt': c['close_price_usdt']} for c in candles[-15:]
        ],
    )
    return envelope


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
        return stamped(
            dict(status='available', view=view, symbol=symbol, data=compact_market(view, r.json()))
        )
    except Exception as e:
        return stamped(dict(status='unavailable', view=view, symbol=symbol, error_type=type(e).__name__))


def readable_forecast(result):
    """Add the forecast as people read it: percent and USDT move. Saves the model converting a log return."""
    try:
        ret, ref, pred = (float(result[k]) for k in ('predicted_log_return', 'reference_close_usdt', 'predicted_close_usdt'))
    except (KeyError, TypeError, ValueError):
        return result
    if not all(map(math.isfinite, (ret, ref, pred))):
        return result
    return dict(result, expected_move_pct=round(math.expm1(ret) * 100, 3), expected_move_usdt=round(pred - ref, 2))


@traced('tool.predict_hourly')
async def predict_hourly(cutoff=None):
    result = await call_agent(
        os.getenv('FORECAST_AGENT_URL', 'http://127.0.0.1:8011'),
        dict(operation='predict_hourly', cutoff=cutoff),
    )
    return stamped(dict(status='available', **readable_forecast(result)))


@traced('tool.detect_market_anomaly')
async def detect_market_anomaly(cutoff=None):
    raw, source = await closed_window(cutoff=cutoff)
    trained = await asyncio.to_thread(score, raw)
    baseline = detect_anomalies(CandleContext(cutoff=source['cutoff'], candles=raw.to_dict('records')))
    return stamped(dict(status='available', source=source, trained=trained, mad_baseline=baseline))


FORECAST_PROFILE = os.getenv(
    'FORECAST_REFERENCE_PROFILE', 'data/models/agent-serving-bundle/v1/reference_profile.json'
)
LEDGER_MIN_HOURS = 168
FORECAST_DRIFT_ROWS = 720  # 30 days: shorter windows make PSI on slow features meaningless
LONG_WINDOW = re.compile(r'_(72|168)$')


def psi_table(frame, profile):
    """PSI of each profiled feature over the rows in `frame`, highest first (same rule as the anomaly model)."""
    import numpy as np

    result = []
    for name, p in profile.items():
        values = frame[name].to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        counts = np.histogram(values, bins=np.array([-np.inf, *p['inner_edges'], np.inf]))[0]
        actual = np.maximum(counts / max(counts.sum(), 1), 1e-6)
        reference = np.maximum(np.asarray(p['bin_fractions']), 1e-6)
        psi = float(np.sum((actual - reference) * np.log(actual / reference)))
        result.append(dict(feature=name, psi=round(psi, 4), heuristic_drift_flag=psi >= 0.25))
    return sorted(result, key=lambda r: r['psi'], reverse=True)


def forecast_drift(raw):
    """Drift of the hourly forecast's own inputs over the last 168 hours, against its training-period profile."""
    import json
    from pathlib import Path
    from pipeline.decision.hourly_engineering import build_experimental_inputs

    path = Path(FORECAST_PROFILE)
    if not path.exists():
        return dict(
            status='unavailable', reason='No reference profile; run python -m agents.reference_profile.'
        )
    reference = json.loads(path.read_text())
    rows = (
        build_experimental_inputs(raw)['compact'][list(reference['features'])]
        .dropna()
        .tail(FORECAST_DRIFT_ROWS)
    )
    if len(rows) < 168:
        return dict(status='unavailable', reason=f'Only {len(rows)} complete feature rows in the window.')
    shift = psi_table(rows, reference['features'])
    for v in shift:
        # 72h/168h rolling features change slowly: a month of them reflects the current regime, so their PSI is
        # reported but kept out of the headline flag.
        v['long_window'] = bool(LONG_WINDOW.search(v['feature']))
    return dict(
        status='available',
        model_id=reference['model_id'],
        feature_set=reference['feature_set'],
        window_feature_rows=len(rows),
        reference_period=reference['period'],
        reference_rows=reference['rows'],
        drift_watch=any(v['heuristic_drift_flag'] and not v['long_window'] for v in shift),
        flagged=[v for v in shift if v['heuristic_drift_flag'] and not v['long_window']],
        flagged_long_window=[v['feature'] for v in shift if v['heuristic_drift_flag'] and v['long_window']],
        top_features=shift[:5],
        features_checked=len(shift),
        not_covered=reference.get('not_covered', []),
    )


async def live_performance():
    """Scored forecasts from the prospective prediction ledger (ml.model_performance)."""
    try:
        rows = await asyncio.to_thread(
            query,
            """select model_id, model_version, symbol, window_label, n, mae, baseline_mae, relative_mae,
                      directional_accuracy, first_target, last_target
               from ml.model_performance order by model_id, symbol, window_label""",
        )
        pending = await asyncio.to_thread(
            query,
            """select count(*) as recorded, count(o.symbol) as scored, min(l.recorded_at) as recording_since
               from ml.prediction_ledger l left join ml.prediction_outcome o using (symbol, target_open)""",
        )
    except Exception as e:
        return dict(
            status='unavailable', error_type=type(e).__name__, reason='Prediction ledger not readable.'
        )
    scored = max((r['n'] for r in rows), default=0)
    return dict(
        status='available' if rows else 'insufficient_data',
        windows=[
            {
                k: (round(float(v), 6) if isinstance(v, Decimal) else str(v) if k.endswith('_target') else v)
                for k, v in r.items()
            }
            for r in rows
        ],
        ledger={k: str(v) if k == 'recording_since' else v for k, v in pending[0].items()},
        reliable=scored >= LEDGER_MIN_HOURS,
        note=f'Relative MAE < 1 beats predicting no change. Fewer than {LEDGER_MIN_HOURS} scored hours is not yet reliable.',
    )


@traced('tool.model_health')
async def model_health(cutoff=None):
    """Health of every served model: input drift against each model's training reference, and live forecast
    performance from the prediction ledger."""
    raw, source = await closed_window(hours=336, cutoff=cutoff)
    current = features(raw).dropna()
    _, meta = load_model()
    shift = population_shift(current, meta['reference_profile'])
    offline = read_record(MODEL_DIR / 'report.json')
    try:
        month, _ = await closed_window(hours=1000, cutoff=cutoff)
        forecast = await asyncio.to_thread(forecast_drift, month)
    except Exception as e:
        forecast = dict(status='unavailable', error_type=type(e).__name__)
    return stamped(
        dict(
            status='available',
            source=source,
            window_feature_rows=len(current),
            data_drift=shift,
            reference_scope='data_drift: Isolation Forest anomaly features. forecast_drift: the hourly forecast inputs.',
            reference_model_sha256=meta['model_sha256'],
            reference_period=meta.get('train_period', 'See frozen anomaly plan.json'),
            drift_watch=any(v['heuristic_drift_flag'] for v in shift),
            forecast_drift=forecast,
            live_performance=await live_performance(),
            threshold_interpretation='PSI >= .25 is a heuristic watch flag, not a significance test or proof of model failure.',
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
