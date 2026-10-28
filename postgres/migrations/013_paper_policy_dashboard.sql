-- User-owned policy overrides and immutable policy evidence for the trade dashboard.
alter table paper.decision
    add column if not exists policy_config jsonb not null default '{}'::jsonb;

create table if not exists paper.user_policy (
    user_key text primary key check (user_key = 'local' or user_key ~ '^u_[a-f0-9]{16}$'),
    policy_name text not null default 'daily_quantile_v1',
    config jsonb not null,
    config_sha256 text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

comment on table paper.user_policy is
    'Validated paper-only policy overrides. Never used for exchange execution.';
comment on column paper.decision.policy_config is
    'Exact validated policy config frozen when the decision was created.';
