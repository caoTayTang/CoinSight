-- Every agent answer, kept for audit, conversation history and future eval cases. Written by the API after
-- each /v1/agent/command call, including failures. user_key is a hash of the signed-in email, never the email.
create table if not exists meta.agent_run (
    run_id uuid primary key,
    created_at timestamptz not null default now(),
    user_key text not null,
    thread_id uuid not null,
    command text not null,
    symbol text not null,
    question text not null,
    model_requested text,
    answer text,
    status text not null check (status in ('ok', 'error')),
    error text,
    models text[] not null default '{}',
    llm_calls integer not null default 0,
    input_tokens integer not null default 0,
    output_tokens integer not null default 0,
    latency_ms integer not null,
    trace_id text,
    steps jsonb not null default '[]'::jsonb,
    evidence jsonb not null default '[]'::jsonb,
    guardrails jsonb
);

create index if not exists agent_run_thread on meta.agent_run (user_key, thread_id, created_at);
create index if not exists agent_run_recent on meta.agent_run (user_key, created_at desc);
