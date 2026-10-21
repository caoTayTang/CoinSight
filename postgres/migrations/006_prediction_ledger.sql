-- Prospective prediction ledger: every forecast is recorded when it is made, and scored only after
-- the target hour closes. Model-agnostic: any forecasting model writes the same row shape
-- (see docs/model_integration.md). Rows are append-only; outcomes live in their own table.
create schema if not exists ml;

create table if not exists ml.prediction_ledger (
    prediction_id bigint generated always as identity primary key,
    model_id text not null,
    model_version text not null,
    symbol text not null check (symbol in ('BTC', 'ETH', 'SOL')),
    horizon_hours smallint not null default 1 check (horizon_hours = 1),
    cutoff timestamptz not null,
    target_open timestamptz not null,
    target_close timestamptz not null,
    generated_at timestamptz not null,
    recorded_at timestamptz not null default now(),
    reference_close double precision not null check (reference_close > 0),
    predicted_log_return double precision not null,
    input_sha256 text,
    artifact_sha256 text,
    details jsonb not null default '{}'::jsonb,
    check (target_open = cutoff and target_close = target_open + interval '1 hour'),
    check (generated_at >= cutoff - interval '1 minute'),
    -- One forecast per model version and hour; a re-run of the recorder is a no-op.
    unique (model_id, model_version, symbol, cutoff)
);

create index if not exists prediction_ledger_target on ml.prediction_ledger (symbol, target_open);

-- Realized close of a target hour from the same source the forecasters read. Shared by all models.
create table if not exists ml.prediction_outcome (
    symbol text not null,
    target_open timestamptz not null,
    open_price double precision not null check (open_price > 0),
    close_price double precision not null check (close_price > 0),
    source text not null,
    observed_at timestamptz not null default now(),
    primary key (symbol, target_open)
);

create or replace view ml.prediction_scored as
select
    l.prediction_id, l.model_id, l.model_version, l.symbol, l.cutoff, l.target_open, l.generated_at,
    -- Forecasts published after the target hour started cannot be acted on; keep them, but flag them.
    l.generated_at > l.cutoff + interval '5 minutes' as late,
    l.predicted_log_return,
    ln(o.close_price / l.reference_close) as realized_log_return,
    abs(l.predicted_log_return - ln(o.close_price / l.reference_close)) as abs_error,
    -- Zero-return baseline ("price does not move"): the bar every model must beat.
    abs(ln(o.close_price / l.reference_close)) as baseline_abs_error,
    sign(l.predicted_log_return) = sign(ln(o.close_price / l.reference_close)) as direction_hit
from ml.prediction_ledger l
join ml.prediction_outcome o using (symbol, target_open);

create or replace view ml.model_performance as
select
    s.model_id, s.model_version, s.symbol, w.window_label,
    count(*) as n,
    avg(s.abs_error) as mae,
    avg(s.baseline_abs_error) as baseline_mae,
    avg(s.abs_error) / nullif(avg(s.baseline_abs_error), 0) as relative_mae,
    avg(case when s.direction_hit then 1.0 else 0.0 end) as directional_accuracy,
    min(s.target_open) as first_target, max(s.target_open) as last_target
from ml.prediction_scored s
join (values ('24h', interval '24 hours'), ('7d', interval '7 days'), ('30d', interval '30 days'))
    as w(window_label, span) on s.target_open >= now() - w.span
where not s.late
group by s.model_id, s.model_version, s.symbol, w.window_label;
