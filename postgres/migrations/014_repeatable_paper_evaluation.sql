-- Every click on Evaluate now is a distinct, auditable market observation.
-- The old uniqueness key returned an earlier stale decision for the same
-- daily target/model/policy instead of storing the refreshed minute price.
-- PostgreSQL truncates automatically generated identifiers to 63 bytes, so
-- locate this old unique constraint by its ordered columns rather than name.
do $$
declare
    old_constraint record;
begin
    for old_constraint in
        select c.conname, c.conrelid
        from pg_constraint c
        where c.conrelid = 'paper.decision'::regclass
          and c.contype = 'u'
          and (
              select array_agg(a.attname order by key_column.ordinality)
              from unnest(c.conkey) with ordinality as key_column(attnum, ordinality)
              join pg_attribute a
                on a.attrelid = c.conrelid and a.attnum = key_column.attnum
          ) = array[
              'portfolio_id', 'symbol', 'target_close',
              'policy_version', 'model_version'
          ]::name[]
    loop
        execute format(
            'alter table paper.decision drop constraint %I',
            old_constraint.conname
        );
    end loop;
end $$;

alter table paper.decision
    add column if not exists evaluated_at timestamptz,
    add column if not exists execution_price_usdt numeric(24, 10),
    add column if not exists execution_price_observed_at timestamptz,
    add column if not exists execution_price_age_seconds double precision,
    add column if not exists current_position_fraction double precision;

update paper.decision
set evaluated_at = coalesce(evaluated_at, created_at)
where evaluated_at is null;

alter table paper.decision
    alter column evaluated_at set default now(),
    alter column evaluated_at set not null;

alter table paper.decision
    drop constraint if exists paper_decision_execution_price_positive,
    add constraint paper_decision_execution_price_positive
        check (execution_price_usdt is null or execution_price_usdt > 0),
    drop constraint if exists paper_decision_current_position_fraction_range,
    add constraint paper_decision_current_position_fraction_range
        check (current_position_fraction is null or current_position_fraction between 0 and 1);

create index if not exists paper_decision_target_evaluations
    on paper.decision (
        portfolio_id, symbol, target_close, policy_version, model_version,
        evaluated_at desc
    );

comment on column paper.decision.execution_price_observed_at is
    'Close time of the latest closed one-minute candle used during policy evaluation.';
comment on column paper.decision.execution_price_age_seconds is
    'evaluated_at minus execution_price_observed_at; stored to diagnose clock/freshness issues.';
