-- Hourly log-return forecasting registry. Independent of the legacy daily classifier.
create table if not exists meta.forecast_training_run (
    run_id text primary key,
    symbol text not null references dw.dim_asset(symbol),
    model_type text not null check (model_type in ('xgboost','gru','lstm','patchtst','itransformer')),
    snapshot_id text not null,
    feature_version text not null,
    status text not null check (status in ('running','accepted','rejected','failed','tested','promoted')),
    seed integer not null,
    artifact_manifest jsonb not null,
    started_at timestamptz not null default now(),
    finished_at timestamptz
);

create table if not exists meta.forecast_evaluation (
    evaluation_id bigint generated always as identity primary key,
    run_id text not null references meta.forecast_training_run(run_id),
    split text not null check (split in ('train','validation','test')),
    period text not null default 'all',
    metric_name text not null,
    metric_value double precision not null,
    evaluated_at timestamptz not null default now(),
    unique (run_id, split, period, metric_name)
);

create table if not exists dw.dim_forecast_model (
    forecast_model_key bigint generated always as identity primary key,
    run_id text not null unique references meta.forecast_training_run(run_id),
    symbol text not null references dw.dim_asset(symbol),
    model_type text not null,
    horizon_hours smallint not null check (horizon_hours > 0),
    artifact_sha256 text not null,
    is_active boolean not null default false,
    promoted_at timestamptz,
    created_at timestamptz not null default now()
);

create unique index if not exists one_active_hourly_forecast_model
    on dw.dim_forecast_model (symbol, horizon_hours) where is_active;

create table if not exists dw.fact_hourly_forecast (
    forecast_id bigint generated always as identity primary key,
    symbol text not null references dw.dim_asset(symbol),
    forecast_model_key bigint not null references dw.dim_forecast_model(forecast_model_key),
    latest_input_open_time timestamptz not null,
    cutoff_time timestamptz not null,
    target_time timestamptz not null,
    reference_close_usdt numeric(24, 10) not null check (reference_close_usdt > 0),
    predicted_log_return double precision not null,
    predicted_close_usdt numeric(24, 10) not null check (predicted_close_usdt > 0),
    actual_log_return double precision,
    actual_close_usdt numeric(24, 10),
    generated_at timestamptz not null default now(),
    evaluated_at timestamptz,
    unique (symbol, target_time, forecast_model_key),
    check (cutoff_time = target_time),
    check (cutoff_time = latest_input_open_time + interval '1 hour')
);

create table if not exists meta.forecast_input_lineage (
    forecast_id bigint not null references dw.fact_hourly_forecast(forecast_id),
    load_batch_id bigint not null references meta.etl_batch(batch_id),
    primary key (forecast_id, load_batch_id)
);
