from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Query, WebSocket
from contextlib import asynccontextmanager
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

try:
    from .chat_agent import ChatRequest, ChatResponse, chat
except ImportError:
    from chat_agent import ChatRequest, ChatResponse, chat

try:
    from .api_schemas import BatchLineage, DataStatus, DirectionPrediction, Envelope, LiveMetric, LiveSummary, ModelEvaluation, Provenance, Quality, Snapshot
except ImportError:  # uvicorn api:app from the /app container working directory
    from api_schemas import BatchLineage, DataStatus, DirectionPrediction, Envelope, LiveMetric, LiveSummary, ModelEvaluation, Provenance, Quality, Snapshot

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
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.websocket("/v1/assets/{symbol}/stream")
async def asset_live_stream(websocket: WebSocket, symbol: str) -> None:
    await stream_live(websocket, symbol)


@app.post("/v1/agent/chat", response_model=ChatResponse)
def agent_chat(request: ChatRequest) -> ChatResponse:
    return chat(request)


@traced("warehouse.query")
def fetch_all(sql: str, params: tuple = ()) -> list[dict]:
    import psycopg2

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


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
            status="unavailable", data=None, trace_id=trace_id,
            provenance=Provenance(source="binance", mode="historical", grain="1d"),
            quality=Quality(warnings=["No Binance daily candle in warehouse"]),
        )
    row = rows[0]
    closed_at = datetime.combine(row["as_of_date"] + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    age = freshness(closed_at)
    return Envelope[Snapshot](
        status="stale" if age is not None and age > 2 * 86400 else "ready",
        data=Snapshot(symbol=row["symbol"], as_of_date=row["as_of_date"],
                      close_price_usdt=row["close_price"], volume_quote_usdt=row["volume_quote"]),
        provenance=Provenance(source=row["source_code"], mode="historical", grain="1d",
                              observed_at=closed_at, computed_at=row["loaded_at"], batch_id=row["batch_id"]),
        quality=Quality(freshness_seconds=age, sample_count=1,
                        warnings=["Daily candle is older than two days"] if age and age > 2 * 86400 else []),
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
        return Envelope[LiveMetric](status="unavailable", data=None, trace_id=trace_id,
            provenance=Provenance(source="binance", mode="live", grain="7d/1d"),
            quality=Quality(warnings=["No live stream metric available"]))
    row = rows[0]
    age = freshness(row["last_event_time"])
    stale = age is not None and age > 180
    return Envelope[LiveMetric](
        status="stale" if stale else "ready",
        data=LiveMetric(symbol=row["symbol"], source=row["source"],
            window_start=row["window_start"], window_end=row["window_end"],
            avg_price_usdt=row["avg_price_usd"], price_volatility_usdt=row["price_volatility"],
            total_volume_quote=row["total_volume"], event_count=row["event_count"]),
        provenance=Provenance(source=row["source"], mode="live", grain="7d/1d",
                              observed_at=row["last_event_time"], computed_at=row["updated_at"]),
        quality=Quality(freshness_seconds=age, sample_count=row["event_count"],
                        warnings=["Metric has not been updated for three minutes"] if stale else []),
        trace_id=trace_id,
    )


@app.get("/v1/assets/{symbol}/live-summary", response_model=Envelope[LiveSummary])
def live_summary(symbol: str) -> Envelope[LiveSummary]:
    rows = fetch_all(
        """select min(open_time) as window_start, max(close_time) as window_end,
                  max(open_time) as last_candle_at,
                  (array_agg(open_price order by open_time))[1] as first_open,
                  (array_agg(close_price order by open_time desc))[1] as last_close,
                  sum(volume_quote) as volume_quote, count(*) as observed_minutes
           from dw.fact_candle_minute_live
           where symbol = %s and open_time >= date_trunc('minute', now()) - interval '15 minutes'
             and open_time < date_trunc('minute', now())""",
        (symbol.upper(),),
    )
    trace_id = str(uuid4())
    row = rows[0] if rows else None
    if not row or not row["observed_minutes"]:
        return Envelope[LiveSummary](status="unavailable", data=None, trace_id=trace_id,
            provenance=Provenance(source="binance-spot", mode="live", grain="1m/15m"),
            quality=Quality(sample_count=0, warnings=["No closed one-minute candles in the last 15 minutes"]))
    age = freshness(row["window_end"])
    count = row["observed_minutes"]
    warnings = []
    if count < 15:
        warnings.append(f"Only {count} of 15 minute candles are available")
    if age is not None and age > 180:
        warnings.append("Latest candle is more than three minutes old")
    return Envelope[LiveSummary](status="stale" if age and age > 180 else "ready",
        data=LiveSummary(symbol=symbol.upper(), window_start=row["window_start"],
            window_end=row["window_end"], last_candle_at=row["last_candle_at"],
            close_price_usdt=row["last_close"],
            change_pct=(row["last_close"] / row["first_open"] - 1) * 100,
            volume_quote_usdt=row["volume_quote"], observed_minutes=count),
        provenance=Provenance(source="binance-spot", mode="live", grain="1m/15m",
            observed_at=row["window_end"]),
        quality=Quality(freshness_seconds=age, sample_count=count, warnings=warnings),
        trace_id=trace_id)


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
        return Envelope[DirectionPrediction](status="insufficient_data", data=None,
            trace_id=trace_id, provenance=Provenance(source="warehouse", mode="historical", grain="1d"),
            quality=Quality(warnings=["No validated direction model prediction is available"]))
    row = rows[0]
    age = (datetime.now(timezone.utc).date() - row["as_of_date"]).days
    return Envelope[DirectionPrediction](status="stale" if age > 1 else "ready",
        data=DirectionPrediction(symbol=row["symbol"], as_of_date=row["as_of_date"],
            target_date=row["target_date"], probability_up=row["probability_up"],
            model_version=row["model_version"], baseline_brier_score=row["baseline_brier_score"],
            model_brier_score=row["brier_score"]),
        provenance=Provenance(source="warehouse", mode="historical", grain="1d",
            computed_at=row["generated_at"], model_version=row["model_version"]),
        quality=Quality(freshness_seconds=age * 86400,
            warnings=["Prediction uses an older daily candle"] if age > 1 else []),
        trace_id=trace_id)


@app.get("/v1/model/evaluation", response_model=Envelope[ModelEvaluation])
def model_evaluation() -> Envelope[ModelEvaluation]:
    rows = fetch_all("""select feature_version, cutoff_date, evaluated_at, decision,
                              train_rows, validation_rows, test_rows, validation_brier,
                              baseline_validation_brier, test_brier, baseline_test_brier,
                              model_version
                       from meta.model_evaluation order by evaluation_id desc limit 1""")
    trace_id = str(uuid4())
    if not rows:
        return Envelope[ModelEvaluation](status="insufficient_data", data=None, trace_id=trace_id,
            provenance=Provenance(source="warehouse", mode="metadata"),
            quality=Quality(warnings=["No model evaluation has run yet"]))
    row = rows[0]
    return Envelope[ModelEvaluation](status="ready", data=ModelEvaluation(**row),
        provenance=Provenance(source="warehouse", mode="metadata",
            computed_at=row["evaluated_at"], model_version=row["model_version"]),
        quality=Quality(warnings=["Candidate did not beat baseline; no new model was published"]
            if row["decision"] == "rejected" else []), trace_id=trace_id)


@app.get("/v1/assets/{symbol}/prediction/lineage", response_model=Envelope[dict])
def prediction_lineage(symbol: str) -> Envelope[dict]:
    rows = fetch_all("""select p.prediction_id, a.symbol, ad.full_date as as_of_date,
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
                       order by ad.full_date desc limit 1""", (symbol.upper(),))
    trace_id = str(uuid4())
    if not rows:
        return Envelope[dict](status="unavailable", data=None, trace_id=trace_id,
            provenance=Provenance(source="warehouse", mode="metadata"),
            quality=Quality(warnings=["No prediction lineage exists for this symbol"]))
    row = rows[0]
    return Envelope[dict](status="ready", data=row, trace_id=trace_id,
        provenance=Provenance(source="warehouse", mode="metadata", model_version=row["model_version"]),
        quality=Quality(sample_count=len(row["load_batches"])))
@app.get("/v1/lineage/batches/{batch_id}", response_model=Envelope[BatchLineage])
def batch_lineage(batch_id: int) -> Envelope[BatchLineage]:
    batches = fetch_all(
        """select batch_id, pipeline, source_code, started_at, finished_at,
                  status, rows_extracted, rows_loaded, rows_rejected
           from meta.etl_batch where batch_id = %s""", (batch_id,))
    trace_id = str(uuid4())
    if not batches:
        return Envelope[BatchLineage](status="unavailable", data=None, trace_id=trace_id,
            provenance=Provenance(source="etl", mode="metadata", batch_id=batch_id),
            quality=Quality(warnings=["Unknown batch ID"]))
    parents = fetch_all(
        """select b.batch_id, b.pipeline, b.source_code, b.started_at, b.finished_at, b.status
           from meta.batch_dependency d join meta.etl_batch b
             on b.batch_id = d.extract_batch_id
           where d.load_batch_id = %s order by b.batch_id""", (batch_id,))
    files = fetch_all(
        """select f.extract_batch_id, f.source_file, f.source_url, f.symbol,
                  f.candle_interval, f.sha256, f.rows_extracted
           from meta.batch_dependency d join meta.source_file_manifest f
             on f.extract_batch_id = d.extract_batch_id
           where d.load_batch_id = %s order by f.source_file""", (batch_id,))
    return Envelope[BatchLineage](status="ready", trace_id=trace_id,
        data=BatchLineage(load_batch=batches[0], extract_batches=parents, source_files=files),
        provenance=Provenance(source=batches[0]["source_code"], mode="metadata",
            computed_at=batches[0]["finished_at"], batch_id=batch_id),
        quality=Quality(sample_count=len(files),
            warnings=["No source file manifest for this batch"] if not files else []))


@app.get("/v1/data-status", response_model=Envelope[DataStatus])
def data_status() -> Envelope[DataStatus]:
    rows = fetch_all(
        """select batch_id, status, finished_at, rows_extracted, rows_rejected from meta.etl_batch
           where pipeline = 'batch_etl' order by batch_id desc limit 1""")
    trace_id = str(uuid4())
    row = rows[0] if rows else None
    warnings = fetch_all(
        """select check_name, severity, failed_rows, details from meta.dq_result
           where batch_id = %s and failed_rows > 0 order by severity, check_name""",
        (row["batch_id"],),
    ) if row else []
    status = ("unavailable" if not row or row["status"] != "success" else
              "insufficient_data" if row["rows_extracted"] == 0 else "ready")
    return Envelope[DataStatus](status=status,
        data=DataStatus(latest_batch_id=row["batch_id"] if row else None,
            latest_batch_status=row["status"] if row else None,
            latest_batch_finished_at=row["finished_at"] if row else None,
            rejected_rows=row["rows_rejected"] if row else None, dq_warnings=warnings),
        provenance=Provenance(source="batch_etl", mode="metadata",
            computed_at=row["finished_at"] if row else None,
            batch_id=row["batch_id"] if row else None),
        quality=Quality(freshness_seconds=freshness(row["finished_at"]) if row else None,
            warnings=["No successful warehouse batch available"] if status == "unavailable" else
                     ["Latest batch had no staged rows"] if status == "insufficient_data" else []),
        trace_id=trace_id)
