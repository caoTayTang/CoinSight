create table if not exists dim_asset (
    symbol text primary key,
    name text not null
);

create table if not exists fact_price (
    symbol text not null references dim_asset(symbol),
    ts timestamptz not null,
    price_usd numeric(18, 6) not null check (price_usd > 0),
    volume_usd numeric(18, 2) not null check (volume_usd >= 0),
    primary key (symbol, ts)
);

create table if not exists fact_forecast (
    symbol text not null references dim_asset(symbol),
    ts timestamptz not null,
    forecast_price_usd numeric(18, 6) not null check (forecast_price_usd > 0),
    model_name text not null,
    created_at timestamptz not null default now(),
    primary key (symbol, ts, model_name)
);

create table if not exists fact_live_metric (
    symbol text not null references dim_asset(symbol),
    window_start timestamptz not null,
    window_end timestamptz not null,
    avg_price_usd numeric(18, 6) not null check (avg_price_usd > 0),
    price_volatility numeric(18, 6) not null check (price_volatility >= 0),
    total_volume numeric(24, 2) not null check (total_volume >= 0),
    event_count bigint not null check (event_count > 0),
    updated_at timestamptz not null default now(),
    primary key (symbol, window_start, window_end)
);
