-- User-scoped, long-only paper trading. No exchange integration and no fee simulation.
create schema if not exists paper;

create table if not exists paper.portfolio (
    portfolio_id uuid primary key default gen_random_uuid(),
    user_key text not null check (user_key = 'local' or user_key ~ '^u_[a-f0-9]{16}$'),
    name text not null check (char_length(name) between 1 and 80),
    initial_cash_usdt numeric(24, 8) not null check (initial_cash_usdt > 0),
    mode text not null default 'manual' check (mode in ('advisory', 'manual')),
    status text not null default 'active' check (status in ('active', 'archived')),
    version integer not null default 1 check (version > 0),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_key, name)
);

create table if not exists paper.decision (
    decision_id uuid primary key default gen_random_uuid(),
    portfolio_id uuid not null references paper.portfolio(portfolio_id),
    symbol text not null check (symbol in ('BTC', 'ETH')),
    cutoff timestamptz not null,
    target_close timestamptz not null,
    policy_id text not null,
    policy_version text not null,
    policy_sha256 text not null,
    model_id text not null,
    model_version text not null,
    action text not null check (action in ('BUY', 'SELL', 'HOLD', 'NO_TRADE')),
    support_score double precision not null check (support_score between 0 and 1),
    signed_score double precision not null check (signed_score between -1 and 1),
    target_position_fraction double precision not null check (target_position_fraction between 0 and 1),
    order_notional_usdt numeric(24, 8) not null check (order_notional_usdt >= 0),
    executable boolean not null,
    reasons jsonb not null,
    risk_flags jsonb not null,
    components jsonb not null,
    evidence jsonb not null,
    evidence_sha256 text not null,
    valid_until timestamptz not null,
    created_at timestamptz not null default now(),
    check (target_close > cutoff),
    unique (portfolio_id, symbol, target_close, policy_version, model_version)
);

create index if not exists paper_decision_recent
    on paper.decision (portfolio_id, created_at desc);

create table if not exists paper.paper_order (
    order_id uuid primary key default gen_random_uuid(),
    decision_id uuid not null unique references paper.decision(decision_id),
    portfolio_id uuid not null references paper.portfolio(portfolio_id),
    symbol text not null check (symbol in ('BTC', 'ETH')),
    side text not null check (side in ('BUY', 'SELL')),
    requested_notional_usdt numeric(24, 8) not null check (requested_notional_usdt > 0),
    idempotency_key text not null check (char_length(idempotency_key) between 8 and 100),
    status text not null check (status in ('FILLED', 'REJECTED')),
    rejection_reason text,
    created_at timestamptz not null default now(),
    unique (portfolio_id, idempotency_key)
);

create table if not exists paper.fill (
    fill_id uuid primary key default gen_random_uuid(),
    order_id uuid not null unique references paper.paper_order(order_id),
    quantity numeric(30, 12) not null check (quantity > 0),
    market_price_usdt numeric(24, 10) not null check (market_price_usdt > 0),
    fill_price_usdt numeric(24, 10) not null check (fill_price_usdt > 0),
    notional_usdt numeric(24, 8) not null check (notional_usdt > 0),
    slippage_bps double precision not null check (slippage_bps >= 0),
    source text not null,
    source_candle_time timestamptz not null,
    cash_after_usdt numeric(24, 8) not null check (cash_after_usdt >= 0),
    position_quantity_after numeric(30, 12) not null check (position_quantity_after >= 0),
    average_entry_after_usdt numeric(24, 10),
    realized_pnl_usdt numeric(24, 8) not null,
    equity_after_usdt numeric(24, 8) not null check (equity_after_usdt >= 0),
    executed_at timestamptz not null default now()
);

create table if not exists paper.equity_snapshot (
    snapshot_id bigint generated always as identity primary key,
    portfolio_id uuid not null references paper.portfolio(portfolio_id),
    observed_at timestamptz not null,
    cash_usdt numeric(24, 8) not null check (cash_usdt >= 0),
    positions_value_usdt numeric(24, 8) not null check (positions_value_usdt >= 0),
    equity_usdt numeric(24, 8) not null check (equity_usdt >= 0),
    realized_pnl_usdt numeric(24, 8) not null,
    drawdown double precision not null check (drawdown between -1 and 0),
    source text not null,
    unique (portfolio_id, observed_at, source)
);

create index if not exists paper_order_recent
    on paper.paper_order (portfolio_id, created_at desc);
create index if not exists paper_equity_curve
    on paper.equity_snapshot (portfolio_id, observed_at);

create or replace view paper.trade_history as
select o.portfolio_id, o.order_id, o.decision_id, o.symbol, o.side, o.status,
       f.quantity, f.market_price_usdt, f.fill_price_usdt, f.notional_usdt,
       f.slippage_bps, f.realized_pnl_usdt, f.executed_at
from paper.paper_order o
left join paper.fill f using (order_id);
