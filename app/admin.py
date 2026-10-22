"""Admin console data (/v1/admin/*): who uses the agents, what they ask, how the answers and models do.

Owners only (usage.is_owner). Users appear by email when they signed in (meta.app_user) or are owners;
anonymous visitors stay an 'a_' key. Every query is read-only and bounded by a window in days.
"""

import os
import re

from fastapi import Depends, HTTPException

try:
    from . import agent_runs, usage
    from .auth import User, current_user, user_key
except ImportError:
    import agent_runs
    import usage
    from auth import User, current_user, user_key

AGENT_COMMANDS = usage.AGENT_COMMANDS
MAX_DAYS = 90
SINCE = "now() - make_interval(days => %(days)s)"


def require_owner(user: User = Depends(current_user)) -> User:
    if not usage.is_owner(user):
        raise HTTPException(403, 'Admin console is for owners only.')
    return user


def window(days):
    if not 1 <= days <= MAX_DAYS:
        raise HTTPException(422, f'days must be between 1 and {MAX_DAYS}')
    return {'days': days, 'agent': list(AGENT_COMMANDS)}


def labels():
    """user_key -> a readable name: signed-in emails (meta.app_user), owners, 'local'; anonymous stays a key."""
    owners = [e.strip().lower() for e in os.getenv('AGENT_OWNER_EMAILS', '').split(',') if e.strip()]
    known = {r['user_key']: r['email'] for r in agent_runs.query('select user_key, email from meta.app_user')}
    return {'local': 'local', **{user_key(e): e for e in owners}, **known}


def paid_models():
    """{model id: price} for routes with a price; empty if the gateway can't be reached."""
    try:
        return {model: price for model, price in usage.paid_routes().values()}
    except HTTPException:
        return {}


def overview(days):
    params = window(days)
    totals = agent_runs.query(
        f"""select count(*) as runs,
                   count(*) filter (where command = any(%(agent)s)) as questions,
                   count(distinct user_key) as users,
                   count(distinct thread_id) as threads,
                   count(*) filter (where status = 'error') as errors,
                   percentile_cont(0.5) within group (order by latency_ms) as latency_p50_ms,
                   percentile_cont(0.95) within group (order by latency_ms) as latency_p95_ms,
                   coalesce(sum(input_tokens), 0) as input_tokens,
                   coalesce(sum(output_tokens), 0) as output_tokens
            from meta.agent_run where created_at >= {SINCE}""",
        params,
    )[0]
    daily = agent_runs.query(
        f"""select (created_at at time zone 'utc')::date as day, count(*) as runs,
                   count(distinct user_key) as users, count(*) filter (where status = 'error') as errors,
                   percentile_cont(0.5) within group (order by latency_ms) as latency_p50_ms,
                   coalesce(sum(input_tokens + output_tokens), 0) as tokens
            from meta.agent_run where created_at >= {SINCE} group by 1 order by 1""",
        params,
    )
    feedback = agent_runs.query(
        f"""select count(*) filter (where f.rating = 1) as up, count(*) filter (where f.rating = -1) as down
            from meta.agent_feedback f join meta.agent_run r using (run_id) where r.created_at >= {SINCE}""",
        params,
    )[0]
    refusals = agent_runs.query(
        f"""select reason, count(*) as n from meta.agent_refusal where created_at >= {SINCE}
            group by reason order by n desc limit 10""",
        params,
    )
    tools = agent_runs.query(
        f"""select t->>'name' as tool, count(*) as calls
            from meta.agent_run r
            cross join lateral jsonb_array_elements(r.steps) s
            cross join lateral jsonb_array_elements(coalesce(s->'tools', '[]'::jsonb)) t
            where r.created_at >= {SINCE} and s->>'kind' = 'model'
            group by 1 order by calls desc limit 15""",
        params,
    )
    spend = 0.0
    for model, price in paid_models().items():
        tokens = agent_runs.query(
            f"""select coalesce(sum(input_tokens), 0) as input, coalesce(sum(output_tokens), 0) as output
                from meta.agent_run where %(model)s = any(models) and created_at >= {SINCE}""",
            {**params, 'model': model},
        )[0]
        spend += (tokens['input'] * price['input'] + tokens['output'] * price['output']) / 1e6
    return dict(
        days=days,
        totals=totals,
        daily=daily,
        feedback=feedback,
        refusals=refusals,
        tools=tools,
        paid_spend_usd=round(spend, 4),
        paid_budget_usd_per_day=usage.limits()['paid_budget_usd'],
    )


def like(text):
    return '%' + re.sub(r'([\\%_])', r'\\\1', text) + '%'


def runs(days, q=None, user=None, status=None, rating=None, limit=50, before=None):
    params = dict(
        window(days),
        q=like(q) if q else None,
        user=user,
        status=status,
        rating=rating,
        limit=max(1, min(limit, 200)),
        before=before,
    )
    rows = agent_runs.query(
        f"""select r.run_id, r.created_at, r.user_key, r.thread_id, r.command, r.symbol, r.question,
                   left(r.answer, 280) as answer_preview, r.status, r.error, r.models, r.model_requested,
                   r.llm_calls, r.input_tokens, r.output_tokens, r.latency_ms, f.rating, f.comment
            from meta.agent_run r left join meta.agent_feedback f using (run_id)
            where r.created_at >= {SINCE}
              and (%(q)s::text is null or r.question ilike %(q)s or r.answer ilike %(q)s)
              and (%(user)s::text is null or r.user_key = %(user)s)
              and (%(status)s::text is null or r.status = %(status)s)
              and (%(rating)s::int is null or f.rating = %(rating)s)
              and (%(before)s::timestamptz is null or r.created_at < %(before)s)
            order by r.created_at desc limit %(limit)s""",
        params,
    )
    names = labels()
    for row in rows:
        row['user_label'] = names.get(row['user_key'])
    return rows


def run(run_id):
    rows = agent_runs.query(
        """select r.*, f.rating, f.comment, f.updated_at as rated_at
           from meta.agent_run r left join meta.agent_feedback f using (run_id) where r.run_id = %s""",
        (str(run_id),),
    )
    if not rows:
        raise HTTPException(404, 'No such run')
    return dict(rows[0], user_label=labels().get(rows[0]['user_key']))


def users(days):
    params = dict(window(days), paid=list(paid_models()) or [''])
    rows = agent_runs.query(
        f"""with runs as (
              select user_key, min(created_at) as first_seen, max(created_at) as last_seen,
                     count(*) filter (where created_at >= {SINCE}) as runs,
                     count(*) filter (where created_at >= {SINCE} and command = any(%(agent)s)) as questions,
                     count(*) filter (where created_at >= {SINCE} and status = 'error') as errors,
                     count(distinct thread_id) filter (where created_at >= {SINCE}) as threads,
                     count(*) filter (where created_at >= {SINCE} and models && %(paid)s::text[]) as paid_runs,
                     coalesce(sum(input_tokens + output_tokens) filter (where created_at >= {SINCE}), 0) as tokens
              from meta.agent_run group by user_key having max(created_at) >= {SINCE}
            ), rated as (
              select f.user_key, count(*) filter (where rating = 1) as up, count(*) filter (where rating = -1) as down
              from meta.agent_feedback f join meta.agent_run r using (run_id)
              where r.created_at >= {SINCE} group by f.user_key
            ), refused as (
              select user_key, count(*) as refusals from meta.agent_refusal
              where created_at >= {SINCE} group by user_key
            )
            select runs.*, coalesce(up, 0) as up, coalesce(down, 0) as down, coalesce(refusals, 0) as refusals
            from runs left join rated using (user_key) left join refused using (user_key)
            order by last_seen desc""",
        params,
    )
    names = labels()
    for row in rows:
        row['user_label'] = names.get(row['user_key'])
    return rows


def models(days):
    params = window(days)
    calls = agent_runs.query(
        f"""select s->'model'->>'provider' as provider, s->'model'->>'model' as model, count(*) as calls,
                   percentile_cont(0.5) within group (order by (s->>'latency_ms')::numeric) as latency_p50_ms,
                   percentile_cont(0.95) within group (order by (s->>'latency_ms')::numeric) as latency_p95_ms,
                   coalesce(sum((s->'usage'->>'inputTokens')::bigint), 0) as input_tokens,
                   coalesce(sum((s->'usage'->>'outputTokens')::bigint), 0) as output_tokens,
                   count(*) filter (where jsonb_array_length(coalesce(s->'fallbacks', '[]'::jsonb)) > 0)
                     as after_fallback
            from meta.agent_run r cross join lateral jsonb_array_elements(r.steps) s
            where r.created_at >= {SINCE} and s->>'kind' = 'model' and s->'model' is not null
            group by 1, 2 order by calls desc""",
        params,
    )
    failures = agent_runs.query(
        f"""select split_part(f->>'route', '#', 1) as route, f->>'model' as model, f->>'status' as status,
                   f->>'http_status' as http_status, count(*) as n
            from meta.agent_run r
            cross join lateral jsonb_array_elements(r.steps) s
            cross join lateral jsonb_array_elements(coalesce(s->'fallbacks', '[]'::jsonb)) f
            where r.created_at >= {SINCE} and s->>'kind' = 'model'
            group by 1, 2, 3, 4 order by n desc limit 20""",
        params,
    )
    try:
        listed = usage.gateway('GET', ['models'])['routes']
        card = {r['model']: dict(label=r.get('label'), eval=r.get('eval'), price=r.get('price')) for r in listed}
    except HTTPException:
        card = {}
    for row in calls:
        row.update(card.get(row['model'], {}))
    return dict(days=days, calls=calls, failures=failures)


def system():
    try:
        performance = agent_runs.query(
            """select model_id, symbol, window_label, n, mae, baseline_mae, relative_mae, directional_accuracy,
                      last_target
               from ml.model_performance order by model_id, symbol, window_label"""
        )
    except Exception as exc:  # the ledger schema may not exist on a fresh database
        performance = {'unavailable': type(exc).__name__}
    errors = agent_runs.query(
        """select run_id, created_at, command, model_requested, error from meta.agent_run
           where status = 'error' order by created_at desc limit 10"""
    )
    return dict(forecast_performance=performance, recent_errors=errors)
