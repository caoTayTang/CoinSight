alter table meta.source_file_manifest add column if not exists source_url text;

create table if not exists meta.loaded_archive (
    source_file text primary key,
    sha256 text not null,
    load_batch_id bigint not null references meta.etl_batch(batch_id),
    loaded_at timestamptz not null default now()
);

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
