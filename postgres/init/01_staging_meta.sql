-- Staging and ETL metadata for the batch warehouse pipeline.
--
--   staging  raw OHLCV rows as extracted, before quality checks
--   meta     ETL batch log and data quality results

create schema if not exists staging;
create schema if not exists meta;


-- ---------------------------------------------------------------------------
-- meta: ETL runs and data quality results
-- ---------------------------------------------------------------------------

create table if not exists meta.etl_batch (
    batch_id bigint generated always as identity primary key,
    pipeline text not null,
    source_code text not null,
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    status text not null default 'running'
        check (status in ('running', 'success', 'failed')),
    rows_extracted bigint,
    rows_loaded bigint,
    rows_rejected bigint,
    message text
);

create table if not exists meta.batch_dependency (
    load_batch_id bigint not null references meta.etl_batch(batch_id),
    extract_batch_id bigint not null references meta.etl_batch(batch_id),
    primary key (load_batch_id, extract_batch_id)
);

create table if not exists meta.source_file_manifest (
    extract_batch_id bigint not null references meta.etl_batch(batch_id),
    source_file text not null,
    symbol text not null,
    candle_interval text not null,
    sha256 text not null,
    rows_extracted bigint not null,
    source_url text,
    primary key (extract_batch_id, source_file)
);

-- A file is complete only after both extraction and warehouse loading succeed.
create table if not exists meta.loaded_archive (
    source_file text primary key,
    sha256 text not null,
    load_batch_id bigint not null references meta.etl_batch(batch_id),
    loaded_at timestamptz not null default now()
);

create table if not exists meta.dq_result (
    dq_result_id bigint generated always as identity primary key,
    batch_id bigint not null references meta.etl_batch(batch_id),
    check_name text not null,
    target_table text not null,
    severity text not null check (severity in ('error', 'warning')),
    failed_rows bigint not null check (failed_rows >= 0),
    passed boolean not null,
    details text,
    checked_at timestamptz not null default now()
);


-- ---------------------------------------------------------------------------
-- staging: one row per extracted candle, types already parsed
-- ---------------------------------------------------------------------------

create table if not exists staging.stg_ohlcv (
    batch_id bigint not null references meta.etl_batch(batch_id),
    source_code text not null,
    symbol text not null,
    candle_interval text not null check (candle_interval in ('1h', '1d')),
    open_time timestamptz not null,
    open_price numeric,
    high_price numeric,
    low_price numeric,
    close_price numeric,
    volume_base numeric,
    volume_quote numeric,
    trade_count bigint,
    source_file text,
    extracted_at timestamptz not null default now()
);

create index if not exists stg_ohlcv_batch_idx on staging.stg_ohlcv (batch_id);
