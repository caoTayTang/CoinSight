from __future__ import annotations

import contextvars
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import anyio
from fastapi import Depends, FastAPI, HTTPException, Path as FPath, Query, WebSocket
from contextlib import asynccontextmanager
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from .api_schemas import (
        BatchLineage,
        DataStatus,
        DirectionPrediction,
        Envelope,
        LiveCandle,
        LiveMetric,
        LiveSummary,
        ModelEvaluation,
        Provenance,
        Quality,
        Snapshot,
    )
except ImportError:  # uvicorn api:app from the /app container working directory
    from api_schemas import (
        BatchLineage,
        DataStatus,
        DirectionPrediction,
        Envelope,
        LiveCandle,
        LiveMetric,
        LiveSummary,
        ModelEvaluation,
        Provenance,
        Quality,
        Snapshot,
    )

try:
    from .live_stream import stream_live
except ImportError:
    from live_stream import stream_live


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://crypto:crypto@localhost:5432/crypto_dw")

try:
    from .telemetry import configure_tracing, traced
except ImportError:
    from telemetry import configure_tracing, traced


@asynccontextmanager
async def lifespan(_app):
    provider = configure_tracing()
    yield
    if provider is not None:
        provider.force_flush(timeout_millis=5000)


app = FastAPI(title="Crypto DW DSS API", lifespan=lifespan)


@app.middleware('http')
async def trace_agent_http(request, call_next):
    if request.url.path != '/v1/agent/command':
        return await call_next(request)
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
    from opentelemetry.trace import SpanKind, Status, StatusCode

    try:
        from .telemetry import operation, current_trace_id
    except ImportError:
        from telemetry import operation, current_trace_id
    carrier = {
        k: v for k, v in request.headers.items() if k in ('traceparent', 'tracestate') and len(v) < 512
    }
    with operation(
        'http.agent_request',
        {'http.route': request.url.path, 'http.request.method': request.method},
        context=TraceContextTextMapPropagator().extract(carrier),
        kind=SpanKind.SERVER,
    ) as span:
        response = await call_next(request)
        span.set_attribute('http.response.status_code', response.status_code)
        if response.status_code >= 400:
            span.set_status(Status(StatusCode.ERROR))
        tid = current_trace_id()
        if tid:
            response.headers['X-Trace-ID'] = tid
        return response


@app.exception_handler(RequestValidationError)
async def safe_chat_validation(request, exc):
    if request.url.path == '/v1/agent/command':
        # Pydantic's default error includes the original input; never echo pasted keys.
        errors = [{'loc': e['loc'], 'msg': e['msg'], 'type': e['type']} for e in exc.errors()]
        return JSONResponse(status_code=422, content={'detail': errors})
    return await request_validation_exception_handler(request, exc)


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.websocket("/v1/assets/{symbol}/stream")
async def asset_live_stream(websocket: WebSocket, symbol: str) -> None:
    await stream_live(websocket, symbol)


try:
    from .desk_commands import CommandRequest, gateway
    from . import admin, agent_runs, usage
    from .auth import User, current_user, supabase_config as auth_settings
    from .paper_trading import router as paper_trading_router
except ImportError:
    from desk_commands import CommandRequest, gateway
    import admin
    import agent_runs
    import usage
    from auth import User, current_user, supabase_config as auth_settings
    from paper_trading import router as paper_trading_router

app.include_router(paper_trading_router)


# An agent command can wait minutes. Run it on its own small thread pool so slow agents never take the
# shared pool that every database endpoint needs. The copied context keeps the request's trace.
DESK_THREADS = anyio.CapacityLimiter(8)


@app.post('/v1/agent/command')
async def agent_command(request: CommandRequest, user: User = Depends(current_user)) -> dict:
    # Limits and paid-model access per user (app/usage.py), checked before any model is called.
    admitted = False
    try:
        with usage.one_at_a_time(user):
            request = await anyio.to_thread.run_sync(usage.check, user, request)
            admitted = True
            context = contextvars.copy_context()
            return await anyio.to_thread.run_sync(
                context.run, agent_runs.run, request, user.key, limiter=DESK_THREADS
            )
    except HTTPException as exc:
        # Only the limits' own refusals; a 429 from a provider during the run is logged with the run.
        if exc.status_code == 429 and not admitted:
            await anyio.to_thread.run_sync(agent_runs.record_refusal, user.key, request, exc.detail)
        raise


class Feedback(BaseModel):
    rating: Literal[-1, 1]
    comment: str | None = Field(default=None, max_length=500)


@app.put('/v1/agent/runs/{run_id}/feedback')
def agent_feedback(run_id: UUID, feedback: Feedback, user: User = Depends(current_user)) -> dict:
    agent_runs.rate(user.key, run_id, feedback.rating, feedback.comment)
    return {'run_id': str(run_id), 'rating': feedback.rating}


@app.get('/v1/auth/config')
def auth_config() -> dict:
    # Public by design: the Supabase project URL and publishable key; the browser needs them to sign in.
    config = auth_settings()
    return config if config['url'] else {'url': None, 'publishable_key': None, 'providers': []}


@app.get('/v1/me')
def me(user: User = Depends(current_user)) -> dict:
    agent_runs.remember_user(user)
    try:
        summary = usage.summary(user)
    except HTTPException:  # agents down: still say who this is, so sign-in and the admin button keep working
        summary = {'owner': usage.is_owner(user), 'unavailable': True}
    return {
        'email': user.email,
        'signed_in': user.email is not None,
        'anonymous': user.anonymous,
        'provider': user.provider,
        'usage': summary,
    }


def signed_in(user: User = Depends(current_user)) -> User:
    # Anonymous visitors share an IP-based key, so lists of past threads and memories would leak between them.
    if user.anonymous:
        raise HTTPException(401, 'Sign in to see your conversations and memory.')
    return user


@app.get('/v1/agent/threads')
def agent_threads(user: User = Depends(current_user)) -> dict:
    return {'threads': [] if user.anonymous else agent_runs.threads(user.key)}


@app.get('/v1/agent/threads/{thread_id}')
def agent_thread(thread_id: UUID, user: User = Depends(current_user)) -> dict:
    return {'thread_id': str(thread_id), 'runs': agent_runs.thread(user.key, thread_id)}


@app.delete('/v1/agent/threads/{thread_id}')
def delete_agent_thread(thread_id: UUID, user: User = Depends(current_user)) -> dict:
    return {'deleted_runs': agent_runs.delete_thread(user.key, thread_id)}


@app.get('/v1/agent/models')
def agent_models(user: User = Depends(current_user)) -> dict:
    return usage.annotate_models(user, gateway('GET', ['models']))


# Admin console: owners only (app/admin.py).
@app.get('/v1/admin/overview')
def admin_overview(days: int = 7, _owner: User = Depends(admin.require_owner)) -> dict:
    return admin.overview(days)


@app.get('/v1/admin/runs')
def admin_runs(
    days: int = 7,
    q: str | None = Query(default=None, max_length=200),
    user: str | None = Query(default=None, max_length=64),
    status: Literal['ok', 'error'] | None = None,
    rating: Literal[-1, 1] | None = None,
    limit: int = 50,
    before: datetime | None = None,
    _owner: User = Depends(admin.require_owner),
) -> dict:
    return {'runs': admin.runs(days, q, user, status, rating, limit, before)}


@app.get('/v1/admin/runs/{run_id}')
def admin_run(run_id: UUID, _owner: User = Depends(admin.require_owner)) -> dict:
    return admin.run(run_id)


@app.get('/v1/admin/users')
def admin_users(days: int = 30, _owner: User = Depends(admin.require_owner)) -> dict:
    return {'users': admin.users(days)}


@app.get('/v1/admin/models')
def admin_models(days: int = 7, _owner: User = Depends(admin.require_owner)) -> dict:
    return admin.models(days)


@app.get('/v1/admin/traces/{trace_id}')
def admin_trace(
    trace_id: str = FPath(pattern=r'^[a-f0-9]{32}$'), _owner: User = Depends(admin.require_owner)
) -> dict:
    # Jaeger stays on the home network; owners see its allowlisted span metadata through the gateway.
    return gateway('GET', ['traces', trace_id])


@app.get('/v1/admin/system')
def admin_system(_owner: User = Depends(admin.require_owner)) -> dict:
    return admin.system()


@app.get('/v1/agent/memories')
def agent_memories(user: User = Depends(signed_in)) -> dict:
    return gateway('GET', ['memories'], {'user': user.key})


@app.delete('/v1/agent/memories/{key}')
def delete_agent_memory(key: str, user: User = Depends(signed_in)) -> dict:
    if not key.isalnum() or len(key) > 64:
        raise HTTPException(422, 'Invalid memory id')
    return gateway('DELETE', ['memories', key], {'user': user.key})


@traced("warehouse.query")
def fetch_all(sql: str, params: tuple = ()) -> list[dict]:
    import psycopg2

    # `with connection` only ends the transaction; close explicitly so each request returns its connection.
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        conn.close()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    fetch_all("select 1")
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/assets")
def assets() -> list[dict]:
    return fetch_all("select symbol, name from dim_asset order by symbol")


@app.get("/prices/{symbol}")
def prices(symbol: str, limit: int = Query(100, ge=1, le=1000)) -> list[dict]:
    return fetch_all(
        """
        select symbol, ts, price_usd, volume_usd
        from fact_price
        where symbol = %s
        order by ts desc
        limit %s
        """,
        (symbol.upper(), limit),
    )


@app.get("/live-metrics/{symbol}")
def live_metrics(symbol: str, limit: int = Query(100, ge=1, le=1000)) -> list[dict]:
    return fetch_all(
        """
        select symbol, window_start, window_end, avg_price_usd,
               price_volatility, total_volume, event_count, updated_at
        from fact_live_metric
        where symbol = %s
        order by window_end desc
        limit %s
        """,
        (symbol.upper(), limit),
    )


@app.get("/overview")
def overview() -> list[dict]:
    return fetch_all(
        """
        select a.symbol, a.name,
               latest.ts as latest_ts,
               latest.price_usd as latest_price_usd,
               previous.price_usd as previous_price_usd,
               stats.observation_count,
               stats.first_ts,
               stats.last_ts,
               stats.avg_volume_usd,
               coverage.latest_daily_ts,
               case when latest.ts is null then null else greatest(
                 0,
                 ((now() at time zone 'UTC')::date - 1) - latest.ts::date
               ) end as daily_age_days,
               live.window_end as live_window_end,
               live.avg_price_usd as live_avg_price_usd,
               live.price_volatility as live_price_volatility,
               live.event_count as live_event_count,
               live.updated_at as live_updated_at
        from dim_asset a
        left join lateral (
            select ts, price_usd
            from fact_price
            where symbol = a.symbol
            order by ts desc
            limit 1
        ) latest on true
        left join lateral (
            select price_usd
            from fact_price
            where symbol = a.symbol
            order by ts desc
            offset 1 limit 1
        ) previous on true
        left join lateral (
            select count(*) as observation_count,
                   min(ts) as first_ts,
                   max(ts) as last_ts,
                   avg(volume_usd) as avg_volume_usd
            from fact_price
            where symbol = a.symbol
        ) stats on true
        cross join lateral (
            select max(ts) as latest_daily_ts from fact_price
        ) coverage
        left join lateral (
            select window_end, avg_price_usd, price_volatility,
                   event_count, updated_at
            from fact_live_metric
            where symbol = a.symbol
            order by updated_at desc, window_end desc
            limit 1
        ) live on true
        order by a.symbol
        """
    )


def freshness(observed_at: datetime | None) -> int | None:
    if observed_at is None:
        return None
    return max(0, int((datetime.now(timezone.utc) - observed_at).total_seconds()))


@app.get("/v1/assets/{symbol}/snapshot", response_model=Envelope[Snapshot])
def asset_snapshot(symbol: str) -> Envelope[Snapshot]:
    rows = fetch_all(
        """
        select a.symbol, d.full_date as as_of_date, f.close_price,
               f.volume_quote, s.source_code, f.batch_id, f.loaded_at
        from dw.fact_ohlcv_daily f
        join dw.dim_asset a using (asset_key)
        join dw.dim_date d using (date_key)
        join dw.dim_source s using (source_key)
        where a.symbol = %s and s.source_code = 'binance'
        order by d.full_date desc limit 1
        """,
        (symbol.upper(),),
    )
    trace_id = str(uuid4())
    if not rows:
        return Envelope[Snapshot](
            status="unavailable",
            data=None,
            trace_id=trace_id,
            provenance=Provenance(source="binance", mode="historical", grain="1d"),
            quality=Quality(warnings=["No Binance daily candle in warehouse"]),
        )
    row = rows[0]
    closed_at = datetime.combine(
        row["as_of_date"] + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
    )
    age = freshness(closed_at)
    return Envelope[Snapshot](
        status="stale" if age is not None and age > 2 * 86400 else "ready",
        data=Snapshot(
            symbol=row["symbol"],
            as_of_date=row["as_of_date"],
            close_price_usdt=row["close_price"],
            volume_quote_usdt=row["volume_quote"],
        ),
        provenance=Provenance(
            source=row["source_code"],
            mode="historical",
            grain="1d",
            observed_at=closed_at,
            computed_at=row["loaded_at"],
            batch_id=row["batch_id"],
        ),
        quality=Quality(
            freshness_seconds=age,
            sample_count=1,
            warnings=["Daily candle is older than two days"] if age and age > 2 * 86400 else [],
        ),
        trace_id=trace_id,
    )


@app.get("/v1/assets/{symbol}/live", response_model=Envelope[LiveMetric])
def live_metric_v1(symbol: str) -> Envelope[LiveMetric]:
    rows = fetch_all(
        """
        select symbol, source, window_start, window_end, last_event_time, avg_price_usd,
               price_volatility, total_volume, event_count, updated_at
        from dw.fact_stream_metric_v1
        where symbol = %s and mode = 'live' and source = 'binance-spot'
        order by updated_at desc limit 1
        """,
        (symbol.upper(),),
    )

    trace_id = str(uuid4())
    if not rows:
        return Envelope[LiveMetric](
            status="unavailable",
            data=None,
            trace_id=trace_id,
            provenance=Provenance(source="binance", mode="live", grain="7d/1d"),
            quality=Quality(warnings=["No live stream metric available"]),
        )
    row = rows[0]
    age = freshness(row["last_event_time"])
    stale = age is not None and age > 180
    return Envelope[LiveMetric](
        status="stale" if stale else "ready",
        data=LiveMetric(
            symbol=row["symbol"],
            source=row["source"],
            window_start=row["window_start"],
            window_end=row["window_end"],
            avg_price_usdt=row["avg_price_usd"],
            price_volatility_usdt=row["price_volatility"],
            total_volume_quote=row["total_volume"],
            event_count=row["event_count"],
        ),
        provenance=Provenance(
            source=row["source"],
            mode="live",
            grain="7d/1d",
            observed_at=row["last_event_time"],
            computed_at=row["updated_at"],
        ),
        quality=Quality(
            freshness_seconds=age,
            sample_count=row["event_count"],
            warnings=["Metric has not been updated for three minutes"] if stale else [],
        ),
        trace_id=trace_id,
    )


@app.get("/v1/assets/{symbol}/live-summary", response_model=Envelope[LiveSummary])
def live_summary(symbol: str) -> Envelope[LiveSummary]:
    symbol = symbol.upper()
    rows = fetch_all(
        """select open_time, close_time, open_price, high_price, low_price, close_price, volume_quote
           from (
             select open_time, close_time, open_price, high_price, low_price, close_price, volume_quote
             from dw.fact_candle_minute_live
             where symbol = %s and open_time < date_trunc('minute', now())
             order by open_time desc
             limit 60
           ) recent
           order by open_time""",
        (symbol,),
    )
    trace_id = str(uuid4())
    window_floor = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=15)
    window = [row for row in rows if row["open_time"] >= window_floor]
    if not window:
        return Envelope[LiveSummary](
            status="unavailable",
            data=None,
            trace_id=trace_id,
            provenance=Provenance(source="binance-spot", mode="live", grain="1m/15m"),
            quality=Quality(sample_count=0, warnings=["No closed one-minute candles in the last 15 minutes"]),
        )
    first, last = window[0], window[-1]
    age = freshness(last["close_time"])
    count = len(window)
    warnings = []
    if count < 15:
        warnings.append(f"Only {count} of 15 minute candles are available")
    if age is not None and age > 180:
        warnings.append("Latest candle is more than three minutes old")
    candles = [
        LiveCandle(
            open_time=row["open_time"],
            close_time=row["close_time"],
            open_price_usdt=row["open_price"],
            high_price_usdt=row["high_price"],
            low_price_usdt=row["low_price"],
            close_price_usdt=row["close_price"],
            volume_quote_usdt=row["volume_quote"],
        )
        for row in rows
    ]
    return Envelope[LiveSummary](
        status="stale" if age and age > 180 else "ready",
        data=LiveSummary(
            symbol=symbol,
            window_start=first["open_time"],
            window_end=last["close_time"],
            last_candle_at=last["open_time"],
            close_price_usdt=last["close_price"],
            change_pct=(float(last["close_price"]) / float(first["open_price"]) - 1) * 100,
            volume_quote_usdt=sum(row["volume_quote"] for row in window),
            observed_minutes=count,
            candles=candles,
        ),
        provenance=Provenance(
            source="binance-spot", mode="live", grain="1m/15m", observed_at=last["close_time"]
        ),
        quality=Quality(freshness_seconds=age, sample_count=count, warnings=warnings),
        trace_id=trace_id,
    )


@app.get("/v1/assets/{symbol}/prediction", response_model=Envelope[DirectionPrediction])
def direction_prediction(symbol: str) -> Envelope[DirectionPrediction]:
    rows = fetch_all(
        """select a.symbol, ad.full_date as as_of_date, td.full_date as target_date,
                  p.probability_up, p.generated_at, m.model_version,
                  m.brier_score, m.baseline_brier_score
           from dw.fact_direction_prediction p
           join dw.dim_asset a on a.asset_key = p.asset_key
           join dw.dim_date ad on ad.date_key = p.as_of_date_key
           join dw.dim_date td on td.date_key = p.target_date_key
           join dw.dim_model m on m.model_key = p.model_key
           where a.symbol = %s order by ad.full_date desc, p.generated_at desc limit 1""",
        (symbol.upper(),),
    )
    trace_id = str(uuid4())
    if not rows:
        return Envelope[DirectionPrediction](
            status="insufficient_data",
            data=None,
            trace_id=trace_id,
            provenance=Provenance(source="warehouse", mode="historical", grain="1d"),
            quality=Quality(warnings=["No validated direction model prediction is available"]),
        )
    row = rows[0]
    age = (datetime.now(timezone.utc).date() - row["as_of_date"]).days
    return Envelope[DirectionPrediction](
        status="stale" if age > 1 else "ready",
        data=DirectionPrediction(
            symbol=row["symbol"],
            as_of_date=row["as_of_date"],
            target_date=row["target_date"],
            probability_up=row["probability_up"],
            model_version=row["model_version"],
            baseline_brier_score=row["baseline_brier_score"],
            model_brier_score=row["brier_score"],
        ),
        provenance=Provenance(
            source="warehouse",
            mode="historical",
            grain="1d",
            computed_at=row["generated_at"],
            model_version=row["model_version"],
        ),
        quality=Quality(
            freshness_seconds=age * 86400,
            warnings=["Prediction uses an older daily candle"] if age > 1 else [],
        ),
        trace_id=trace_id,
    )


@app.get("/v1/model/evaluation", response_model=Envelope[ModelEvaluation])
def model_evaluation() -> Envelope[ModelEvaluation]:
    rows = fetch_all("""select feature_version, cutoff_date, evaluated_at, decision,
                              train_rows, validation_rows, test_rows, validation_brier,
                              baseline_validation_brier, test_brier, baseline_test_brier,
                              model_version
                       from meta.model_evaluation order by evaluation_id desc limit 1""")
    trace_id = str(uuid4())
    if not rows:
        return Envelope[ModelEvaluation](
            status="insufficient_data",
            data=None,
            trace_id=trace_id,
            provenance=Provenance(source="warehouse", mode="metadata"),
            quality=Quality(warnings=["No model evaluation has run yet"]),
        )
    row = rows[0]
    return Envelope[ModelEvaluation](
        status="ready",
        data=ModelEvaluation(**row),
        provenance=Provenance(
            source="warehouse",
            mode="metadata",
            computed_at=row["evaluated_at"],
            model_version=row["model_version"],
        ),
        quality=Quality(
            warnings=["Candidate did not beat baseline; no new model was published"]
            if row["decision"] == "rejected"
            else []
        ),
        trace_id=trace_id,
    )


@app.get("/v1/assets/{symbol}/prediction/lineage", response_model=Envelope[dict])
def prediction_lineage(symbol: str) -> Envelope[dict]:
    rows = fetch_all(
        """select p.prediction_id, a.symbol, ad.full_date as as_of_date,
                              td.full_date as target_date, m.model_version,
                              m.feature_version, m.training_cutoff, m.artifact_sha256,
                              array_remove(array_agg(distinct l.load_batch_id), null) as load_batches
                       from dw.fact_direction_prediction p
                       join dw.dim_asset a on a.asset_key = p.asset_key
                       join dw.dim_date ad on ad.date_key = p.as_of_date_key
                       join dw.dim_date td on td.date_key = p.target_date_key
                       join dw.dim_model m on m.model_key = p.model_key
                       left join meta.prediction_batch_lineage l on l.prediction_id = p.prediction_id
                       where a.symbol = %s
                       group by p.prediction_id, a.symbol, ad.full_date, td.full_date,
                                m.model_version, m.feature_version, m.training_cutoff,
                                m.artifact_sha256
                       order by ad.full_date desc limit 1""",
        (symbol.upper(),),
    )
    trace_id = str(uuid4())
    if not rows:
        return Envelope[dict](
            status="unavailable",
            data=None,
            trace_id=trace_id,
            provenance=Provenance(source="warehouse", mode="metadata"),
            quality=Quality(warnings=["No prediction lineage exists for this symbol"]),
        )
    row = rows[0]
    return Envelope[dict](
        status="ready",
        data=row,
        trace_id=trace_id,
        provenance=Provenance(source="warehouse", mode="metadata", model_version=row["model_version"]),
        quality=Quality(sample_count=len(row["load_batches"])),
    )


@app.get("/v1/lineage/batches/{batch_id}", response_model=Envelope[BatchLineage])
def batch_lineage(batch_id: int) -> Envelope[BatchLineage]:
    batches = fetch_all(
        """select batch_id, pipeline, source_code, started_at, finished_at,
                  status, rows_extracted, rows_loaded, rows_rejected
           from meta.etl_batch where batch_id = %s""",
        (batch_id,),
    )
    trace_id = str(uuid4())
    if not batches:
        return Envelope[BatchLineage](
            status="unavailable",
            data=None,
            trace_id=trace_id,
            provenance=Provenance(source="etl", mode="metadata", batch_id=batch_id),
            quality=Quality(warnings=["Unknown batch ID"]),
        )
    parents = fetch_all(
        """select b.batch_id, b.pipeline, b.source_code, b.started_at, b.finished_at, b.status
           from meta.batch_dependency d join meta.etl_batch b
             on b.batch_id = d.extract_batch_id
           where d.load_batch_id = %s order by b.batch_id""",
        (batch_id,),
    )
    files = fetch_all(
        """select f.extract_batch_id, f.source_file, f.source_url, f.symbol,
                  f.candle_interval, f.sha256, f.rows_extracted
           from meta.batch_dependency d join meta.source_file_manifest f
             on f.extract_batch_id = d.extract_batch_id
           where d.load_batch_id = %s order by f.source_file""",
        (batch_id,),
    )
    return Envelope[BatchLineage](
        status="ready",
        trace_id=trace_id,
        data=BatchLineage(load_batch=batches[0], extract_batches=parents, source_files=files),
        provenance=Provenance(
            source=batches[0]["source_code"],
            mode="metadata",
            computed_at=batches[0]["finished_at"],
            batch_id=batch_id,
        ),
        quality=Quality(
            sample_count=len(files), warnings=["No source file manifest for this batch"] if not files else []
        ),
    )


@app.get("/v1/warehouse/proof")
def warehouse_proof(batch_id: int | None = Query(None, ge=1)) -> dict:
    batches = fetch_all(
        """select batch_id, status, rows_extracted, rows_loaded, rows_rejected, finished_at
           from meta.etl_batch where pipeline = 'batch_etl'
             and (%s is null or batch_id = %s) order by batch_id desc limit 1""",
        (batch_id, batch_id),
    )
    selected = batches[0] if batches else None
    return {
        "batch": selected,
        "load_report": fetch_all(
            """select * from meta.warehouse_load_report where batch_id = %s
               order by symbol, candle_interval, source_code""",
            (selected["batch_id"],),
        )
        if selected
        else [],
        "coverage": fetch_all(
            "select * from meta.v_warehouse_coverage order by symbol, candle_interval, source_code"
        ),
        "coverage_scope": "Between first and last observed candle, per source; not proof of full requested history",
    }


@app.get("/v1/warehouse/lineage/{symbol}")
def warehouse_fact_lineage(symbol: str, limit: int = Query(20, ge=1, le=100)) -> list[dict]:
    return fetch_all(
        """select * from meta.v_fact_archive_lineage where symbol = %s
           order by open_time desc, candle_interval limit %s""",
        (symbol.upper(), limit),
    )


@app.get("/v1/data-status", response_model=Envelope[DataStatus])
def data_status() -> Envelope[DataStatus]:
    rows = fetch_all(
        """select batch_id, status, finished_at, rows_extracted, rows_rejected from meta.etl_batch
           where pipeline = 'batch_etl' order by batch_id desc limit 1"""
    )
    trace_id = str(uuid4())
    row = rows[0] if rows else None
    warnings = (
        fetch_all(
            """select check_name, severity, failed_rows, details from meta.dq_result
           where batch_id = %s and failed_rows > 0 order by severity, check_name""",
            (row["batch_id"],),
        )
        if row
        else []
    )
    status = (
        "unavailable"
        if not row or row["status"] != "success"
        else "insufficient_data"
        if row["rows_extracted"] == 0
        else "ready"
    )
    return Envelope[DataStatus](
        status=status,
        data=DataStatus(
            latest_batch_id=row["batch_id"] if row else None,
            latest_batch_status=row["status"] if row else None,
            latest_batch_finished_at=row["finished_at"] if row else None,
            rejected_rows=row["rows_rejected"] if row else None,
            dq_warnings=warnings,
        ),
        provenance=Provenance(
            source="batch_etl",
            mode="metadata",
            computed_at=row["finished_at"] if row else None,
            batch_id=row["batch_id"] if row else None,
        ),
        quality=Quality(
            freshness_seconds=freshness(row["finished_at"]) if row else None,
            warnings=["No successful warehouse batch available"]
            if status == "unavailable"
            else ["Latest batch had no staged rows"]
            if status == "insufficient_data"
            else [],
        ),
        trace_id=trace_id,
    )
