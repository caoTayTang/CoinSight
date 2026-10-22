-- Admin console: answer feedback from users and the requests refused by the limits (app/usage.py).
-- Read only by owners through /v1/admin/*. user_key is the same hash as in meta.agent_run, never an email.
create table if not exists meta.agent_feedback (
    run_id uuid primary key references meta.agent_run (run_id) on delete cascade,
    user_key text not null,
    rating smallint not null check (rating in (-1, 1)),
    comment text check (length(comment) <= 500),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists meta.agent_refusal (
    refusal_id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    user_key text not null,
    command text not null,
    model_requested text,
    reason text not null
);

create index if not exists agent_run_created on meta.agent_run (created_at desc);
create index if not exists agent_refusal_created on meta.agent_refusal (created_at desc);
