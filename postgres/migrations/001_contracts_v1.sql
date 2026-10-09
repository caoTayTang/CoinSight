-- Safe to run on both existing and newly initialized local databases.
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
    primary key (extract_batch_id, source_file)
);

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

alter table dw.fact_stream_metric_v1
    add column if not exists last_event_time timestamptz;
