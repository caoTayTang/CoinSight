-- CoinSight data warehouse schema.
--
-- Layers:
--   staging  raw OHLCV rows as extracted, before quality checks
--   dw       conformed dimensions and fact tables (galaxy schema)
--   mart     analysis views built on top of dw
--   meta     ETL batch log and data quality results
--
-- The design is source-agnostic: any OHLCV source (Binance, Kaggle, ...) is
-- loaded through staging.stg_ohlcv and identified by dw.dim_source.
-- Binance Spot candles in this version use USDT as the quote asset. Legacy
-- *_usd column names remain for compatibility; no USD conversion is made.

-- Requires 01_staging_meta.sql (staging and meta schemas).

create schema if not exists dw;
create schema if not exists mart;

-- Existing streaming and API code uses unqualified table names.
do $$
begin
    execute format(
        'alter database %I set search_path = dw, mart, meta, public',
        current_database()
    );
end
$$;
set search_path = dw, mart, meta, public;


-- ---------------------------------------------------------------------------
-- dw: dimensions
-- ---------------------------------------------------------------------------

create table if not exists dw.dim_date (
    date_key integer primary key,             -- YYYYMMDD
    full_date date not null unique,
    day_of_month smallint not null,
    day_of_week smallint not null,            -- ISO: 1 = Monday, 7 = Sunday
    day_name text not null,
    is_weekend boolean not null,
    week_of_year smallint not null,           -- ISO week
    month smallint not null,
    month_name text not null,
    quarter smallint not null,
    year smallint not null,
    year_month text not null                  -- e.g. 2026-01
);

insert into dw.dim_date
select
    to_char(d, 'YYYYMMDD')::integer,
    d::date,
    extract(day from d)::smallint,
    extract(isodow from d)::smallint,
    trim(to_char(d, 'Day')),
    extract(isodow from d) in (6, 7),
    extract(week from d)::smallint,
    extract(month from d)::smallint,
    trim(to_char(d, 'Month')),
    extract(quarter from d)::smallint,
    extract(year from d)::smallint,
    to_char(d, 'YYYY-MM')
from generate_series('2010-01-01'::date, '2030-12-31'::date, interval '1 day') as d
on conflict (date_key) do nothing;

create table if not exists dw.dim_time (
    time_key smallint primary key,            -- hour of day in UTC, 0-23
    hour_label text not null,                 -- e.g. 09:00
    day_part text not null,                   -- night / morning / afternoon / evening
    trading_session text not null             -- approximate session by UTC hour
);

insert into dw.dim_time
select
    h,
    lpad(h::text, 2, '0') || ':00',
    case
        when h < 6 then 'night'
        when h < 12 then 'morning'
        when h < 18 then 'afternoon'
        else 'evening'
    end,
    case
        when h < 8 then 'asia'
        when h < 16 then 'europe'
        else 'america'
    end
from generate_series(0, 23) as h
on conflict (time_key) do nothing;

-- SCD Type 1: attribute changes overwrite the current row.
create table if not exists dw.dim_asset (
    asset_key integer generated always as identity primary key,
    symbol text not null unique,              -- natural key, base asset (BTC)
    name text not null,
    category text,                            -- layer-1, defi, meme, stablecoin, ...
    is_stablecoin boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists dw.dim_source (
    source_key smallint generated always as identity primary key,
    source_code text not null unique,         -- natural key used in staging
    source_name text not null,
    source_type text not null check (source_type in ('batch', 'stream')),
    source_url text
);


-- ---------------------------------------------------------------------------
-- dw: facts
-- ---------------------------------------------------------------------------

-- Grain: one asset, one UTC calendar day, one source.
create table if not exists dw.fact_ohlcv_daily (
    asset_key integer not null references dw.dim_asset(asset_key),
    date_key integer not null references dw.dim_date(date_key),
    source_key smallint not null references dw.dim_source(source_key),
    open_price numeric(24, 10) not null check (open_price > 0),
    high_price numeric(24, 10) not null,
    low_price numeric(24, 10) not null check (low_price > 0),
    close_price numeric(24, 10) not null check (close_price > 0),
    volume_base numeric(30, 8) check (volume_base >= 0),
    volume_quote numeric(30, 2) not null check (volume_quote >= 0),
    trade_count bigint check (trade_count >= 0),
    batch_id bigint not null references meta.etl_batch(batch_id),
    loaded_at timestamptz not null default now(),
    primary key (asset_key, date_key, source_key),
    check (high_price >= greatest(open_price, close_price, low_price)),
    check (low_price <= least(open_price, close_price))
);

create index if not exists fact_ohlcv_daily_date_idx
    on dw.fact_ohlcv_daily (date_key);

-- Grain: one asset, one UTC hour, one source.
create table if not exists dw.fact_ohlcv_hourly (
    asset_key integer not null references dw.dim_asset(asset_key),
    date_key integer not null references dw.dim_date(date_key),
    time_key smallint not null references dw.dim_time(time_key),
    source_key smallint not null references dw.dim_source(source_key),
    open_time timestamptz not null,
    open_price numeric(24, 10) not null check (open_price > 0),
    high_price numeric(24, 10) not null,
    low_price numeric(24, 10) not null check (low_price > 0),
    close_price numeric(24, 10) not null check (close_price > 0),
    volume_base numeric(30, 8) check (volume_base >= 0),
    volume_quote numeric(30, 2) not null check (volume_quote >= 0),
    trade_count bigint check (trade_count >= 0),
    batch_id bigint not null references meta.etl_batch(batch_id),
    loaded_at timestamptz not null default now(),
    primary key (asset_key, date_key, time_key, source_key),
    check (high_price >= greatest(open_price, close_price, low_price)),
    check (low_price <= least(open_price, close_price))
);

create index if not exists fact_ohlcv_hourly_date_idx
    on dw.fact_ohlcv_hourly (date_key, time_key);

-- Owned by streaming (Dai). Kept unchanged so spark_stream_processor.py works as is.
create table if not exists dw.fact_live_metric (
    symbol text not null references dw.dim_asset(symbol),
    window_start timestamptz not null,
    window_end timestamptz not null,
    avg_price_usd numeric(18, 6) not null check (avg_price_usd > 0),
    price_volatility numeric(18, 6) not null check (price_volatility >= 0),
    total_volume numeric(24, 2) not null check (total_volume >= 0),
    event_count bigint not null check (event_count > 0),
    updated_at timestamptz not null default now(),
    primary key (symbol, window_start, window_end)
);

-- Source-aware stream output. Legacy fact_live_metric remains for the dashboard.
create table if not exists dw.fact_stream_metric_v1 (
    symbol text not null references dw.dim_asset(symbol),
    mode text not null check (mode in ('live', 'replay')),
    source text not null,
    window_start timestamptz not null,
    window_end timestamptz not null,
    avg_price_usd numeric(18, 6) not null,
    price_volatility numeric(18, 6) not null,
    total_volume numeric(24, 2) not null,
    event_count bigint not null,
    last_event_time timestamptz not null,
    updated_at timestamptz not null default now(),
    primary key (symbol, mode, source, window_start, window_end)
);

-- Immutable closed one-minute observations, independent of transport (WS/REST).
create table if not exists dw.fact_candle_minute_live (
    event_id text primary key,
    symbol text not null references dw.dim_asset(symbol),
    pair text not null,
    open_time timestamptz not null,
    close_time timestamptz not null,
    open_price numeric(24, 10) not null,
    high_price numeric(24, 10) not null,
    low_price numeric(24, 10) not null,
    close_price numeric(24, 10) not null,
    volume_base numeric(30, 8) not null,
    volume_quote numeric(30, 8) not null,
    transport text not null,
    kafka_topic text not null,
    kafka_partition integer not null,
    kafka_offset bigint not null,
    ingested_at timestamptz not null default now(),
    unique (pair, open_time),
    check (pair = symbol || 'USDT'),
    check (high_price >= greatest(open_price, close_price, low_price)),
    check (low_price <= least(open_price, close_price)),
    check (volume_base >= 0 and volume_quote >= 0)
);
create index if not exists fact_candle_minute_live_time_idx
    on dw.fact_candle_minute_live (symbol, open_time desc);

-- Owned by DSS (Duong). Kept unchanged until the forecast contract is agreed.
create table if not exists dw.fact_forecast (
    symbol text not null references dw.dim_asset(symbol),
    ts timestamptz not null,
    forecast_price_usd numeric(18, 6) not null check (forecast_price_usd > 0),
    model_name text not null,
    created_at timestamptz not null default now(),
    primary key (symbol, ts, model_name)
);

-- One accepted model version is a dimension; training runs are auditable.
create table if not exists dw.dim_model (
    model_key bigint generated always as identity primary key,
    model_version text not null unique,
    feature_version text not null,
    training_cutoff timestamptz not null,
    artifact_sha256 text not null,
    brier_score numeric(12, 8) not null,
    baseline_brier_score numeric(12, 8) not null,
    accuracy numeric(12, 8) not null,
    baseline_accuracy numeric(12, 8) not null,
    created_at timestamptz not null default now()
);

create table if not exists meta.model_evaluation (
    evaluation_id bigint generated always as identity primary key,
    feature_version text not null,
    evaluated_at timestamptz not null default now(),
    cutoff_date date not null,
    train_rows integer not null,
    validation_rows integer not null,
    test_rows integer not null,
    validation_brier numeric(12, 8),
    baseline_validation_brier numeric(12, 8),
    test_brier numeric(12, 8),
    baseline_test_brier numeric(12, 8),
    decision text not null check (decision in ('accepted', 'rejected')),
    model_version text
);

-- Grain: asset x as-of UTC day x target UTC day x model version.
create table if not exists dw.fact_direction_prediction (
    prediction_id bigint generated always as identity primary key,
    asset_key integer not null references dw.dim_asset(asset_key),
    as_of_date_key integer not null references dw.dim_date(date_key),
    target_date_key integer not null references dw.dim_date(date_key),
    model_key bigint not null references dw.dim_model(model_key),
    probability_up numeric(8, 7) not null check (probability_up between 0 and 1),
    generated_at timestamptz not null default now(),
    feature_source text not null check (feature_source in ('warehouse', 'binance-rest')),
    unique (asset_key, as_of_date_key, target_date_key, model_key)
);

create table if not exists meta.prediction_batch_lineage (
    prediction_id bigint not null references dw.fact_direction_prediction(prediction_id),
    load_batch_id bigint not null references meta.etl_batch(batch_id),
    primary key (prediction_id, load_batch_id)
);


-- ---------------------------------------------------------------------------
-- mart: analysis views
-- ---------------------------------------------------------------------------

-- Compatibility view for the current API (/prices, /overview).
create or replace view mart.fact_price as
select
    a.symbol,
    d.full_date::timestamptz as ts,
    f.close_price as price_usd,
    f.volume_quote as volume_usd
from dw.fact_ohlcv_daily f
join dw.dim_asset a using (asset_key)
join dw.dim_date d using (date_key);

-- Daily candles with their dimension labels and day-over-day return. The
-- return is computed per asset and source, so sources never mix.
create or replace view mart.v_daily_return as
select
    f.asset_key,
    f.date_key,
    f.source_key,
    a.symbol,
    coalesce(a.category, 'unknown') as category,
    a.is_stablecoin,
    s.source_code,
    d.full_date,
    f.open_price,
    f.high_price,
    f.low_price,
    f.close_price,
    f.volume_quote,
    f.trade_count,
    f.close_price
        / lag(f.close_price) over (
            partition by f.asset_key, f.source_key order by f.date_key
        )
        - 1 as daily_return,
    (f.high_price - f.low_price) / f.open_price as intraday_range
from dw.fact_ohlcv_daily f
join dw.dim_asset a using (asset_key)
join dw.dim_source s using (source_key)
join dw.dim_date d using (date_key);


-- ---------------------------------------------------------------------------
-- Reference data
-- ---------------------------------------------------------------------------

insert into dw.dim_source (source_code, source_name, source_type, source_url) values
    ('binance', 'Binance Public Data', 'batch', 'https://data.binance.vision'),
    ('kaggle', 'Kaggle dataset', 'batch', 'https://www.kaggle.com'),
    ('binance-rest', 'Binance REST API (live)', 'stream', 'https://data-api.binance.vision')
on conflict (source_code) do nothing;
