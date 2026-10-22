"""Who may ask the agents how often, and who may reach paid models (routes with a price in router.json).

Owners (AGENT_OWNER_EMAILS, comma-separated; and 'local' in development) have no limits. Everyone else who is
signed in gets AGENT_DAILY_LIMIT agent questions per UTC day, AGENT_MINUTE_LIMIT commands a minute and one
command at a time. Paid models are open to them for AGENT_PAID_DAILY_LIMIT questions a day while today's paid
spend across all users stays under AGENT_PAID_DAILY_BUDGET_USD. Without an email (not signed in) there are no
paid models. Automatic routing for someone who may not pay becomes free-only, so a busy Groq can't fall back
to a paid route on their behalf. Counts come from meta.agent_run, which records every command.
"""

import os
import threading
import time
from contextlib import contextmanager

from fastapi import HTTPException

try:
    from . import agent_runs
    from .desk_commands import gateway
except ImportError:
    import agent_runs
    from desk_commands import gateway

FREE_ONLY = 'auto-free'  # warehouse_agents.router.FREE_ONLY
AGENT_COMMANDS = ('trade', 'sre')
ROUTES_TTL_SECONDS = 300


def limits():
    number = lambda name, default: float(os.getenv(name) or default)  # noqa: E731
    return dict(
        daily=int(number('AGENT_DAILY_LIMIT', 20)),
        minute=int(number('AGENT_MINUTE_LIMIT', 4)),
        paid_daily=int(number('AGENT_PAID_DAILY_LIMIT', 5)),
        paid_budget_usd=number('AGENT_PAID_DAILY_BUDGET_USD', 1.0),
    )


def is_owner(user):
    owners = {e.strip().lower() for e in os.getenv('AGENT_OWNER_EMAILS', '').split(',') if e.strip()}
    return user.key == 'local' or (user.email is not None and user.email in owners)


_routes = {'at': 0.0, 'paid': None}


def paid_routes():
    """{route name: (model id, price)} for routes with a price, from the gateway's model list (cached)."""
    if _routes['paid'] is None or time.monotonic() - _routes['at'] > ROUTES_TTL_SECONDS:
        try:
            listed = gateway('GET', ['models'])['routes']
        except HTTPException:
            if _routes['paid'] is None:
                raise
            return _routes['paid']  # keep the last known list while the gateway restarts
        _routes.update(
            at=time.monotonic(), paid={r['name']: (r['model'], r['price']) for r in listed if r.get('price')}
        )
    return _routes['paid']


def usage(user):
    paid = paid_routes()
    models = [model for model, _ in paid.values()] or ['']
    today = "date_trunc('day', now() at time zone 'utc') at time zone 'utc'"
    mine = agent_runs.query(
        f"""select count(*) filter (where created_at > now() - interval '1 minute') as minute,
                   count(*) filter (where command in %s) as today,
                   count(*) filter (where models && %s::text[]) as paid_today
            from meta.agent_run where user_key = %s and created_at >= {today}""",
        (AGENT_COMMANDS, models, user.key),
    )[0]
    spend = 0.0
    for model, price in paid.values():
        tokens = agent_runs.query(
            f"""select coalesce(sum(input_tokens), 0) as input, coalesce(sum(output_tokens), 0) as output
                from meta.agent_run where %s = any(models) and created_at >= {today}""",
            (model,),
        )[0]
        # Runs that also used free models count in full: an overestimate, which is the safe side.
        spend += (tokens['input'] * price['input'] + tokens['output'] * price['output']) / 1e6
    return dict(mine, paid_spend_usd=round(spend, 4))


def paid_refusal(user, used, limit):
    """Why this user may not reach a paid model right now, or None."""
    if user.email is None:
        return 'Sign in to use paid models.'
    if used['paid_today'] >= limit['paid_daily']:
        return f'You have used today\'s {limit["paid_daily"]} questions on paid models. Pick a free model.'
    if used['paid_spend_usd'] >= limit['paid_budget_usd']:
        return "Today's budget for paid models is used up. Pick a free model."
    return None


def check(user, request):
    """The request to run: unchanged, or with automatic routing made free-only. Raises 429 over a limit."""
    if is_owner(user):
        return request
    limit, used = limits(), usage(user)
    if used['minute'] >= limit['minute']:
        raise HTTPException(429, f'At most {limit["minute"]} commands a minute. Wait a moment and retry.')
    if request.command not in AGENT_COMMANDS:
        return request
    if used['today'] >= limit['daily']:
        raise HTTPException(429, f'You have asked {limit["daily"]} questions today. The limit resets at 00:00 UTC.')
    refusal = paid_refusal(user, used, limit)
    if request.model in paid_routes() and refusal:
        raise HTTPException(429, refusal)
    if request.model is None and refusal:
        return request.model_copy(update={'model': FREE_ONLY})
    return request


def summary(user):
    """For /v1/me: the user's limits and what is left today."""
    if is_owner(user):
        return {'owner': True}
    limit, used = limits(), usage(user)
    return {
        'owner': False,
        'questions_left': max(0, limit['daily'] - used['today']),
        'daily_limit': limit['daily'],
        'paid_allowed': paid_refusal(user, used, limit) is None,
        'paid_left': max(0, limit['paid_daily'] - used['paid_today']),
    }


def annotate_models(user, listed):
    """Mark paid routes this user can't pick now, with the reason, for the model picker."""
    refusal = None if is_owner(user) else paid_refusal(user, usage(user), limits())
    for route in listed.get('routes', []):
        if route.get('price') and refusal:
            route.update(allowed=False, reason=refusal)
    return listed


_running, _lock = set(), threading.Lock()


@contextmanager
def one_at_a_time(user):
    """One agent command per user at a time (the API runs as one process)."""
    if is_owner(user):
        yield
        return
    with _lock:
        if user.key in _running:
            raise HTTPException(429, 'Your previous question is still running.')
        _running.add(user.key)
    try:
        yield
    finally:
        with _lock:
            _running.discard(user.key)
