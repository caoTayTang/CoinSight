import pytest
from fastapi import HTTPException

from app import usage
from app.auth import User
from app.desk_commands import CommandRequest

HAIKU = 'global.anthropic.claude-haiku'
ROUTES = {
    'routes': [
        {'name': 'groq', 'model': 'openai/gpt-oss-120b', 'price': None},
        {'name': 'bedrock-haiku', 'model': HAIKU, 'price': {'input': 1.0, 'output': 5.0}},
    ]
}
GUEST = User(key='u_' + 'a' * 16, email='guest@example.com')


@pytest.fixture
def counts(monkeypatch):
    """Today's meta.agent_run counts for the user and the paid tokens across everyone, set per test."""
    state = {'minute': 0, 'today': 0, 'paid_today': 0, 'input': 0, 'output': 0, 'anonymous_today': 0}

    def query(sql, params=()):
        if "like 'a" in sql:
            return [{'n': state['anonymous_today']}]
        if 'any(models)' in sql:
            return [{'input': state['input'], 'output': state['output']}]
        return [{k: state[k] for k in ('minute', 'today', 'paid_today')}]

    monkeypatch.setattr(usage.agent_runs, 'query', query)
    monkeypatch.setattr(usage, 'gateway', lambda method, path, query=None: ROUTES)
    monkeypatch.setitem(usage._routes, 'paid', None)
    monkeypatch.delenv('AGENT_OWNER_EMAILS', raising=False)
    return state


def ask(model=None, command='trade'):
    question = 'How is BTC?' if command in ('trade', 'sre') else ''
    return CommandRequest(command=command, question=question, model=model)


def test_guest_can_use_haiku_within_limits(counts):
    assert usage.check(GUEST, ask('bedrock-haiku')).model == 'bedrock-haiku'
    assert usage.check(GUEST, ask()).model is None  # automatic routing may still reach Haiku


def test_paid_limit_blocks_haiku_and_makes_automatic_routing_free(counts):
    counts['paid_today'] = 5
    with pytest.raises(HTTPException) as refused:
        usage.check(GUEST, ask('bedrock-haiku'))
    assert refused.value.status_code == 429 and 'paid models' in refused.value.detail
    assert usage.check(GUEST, ask()).model == usage.FREE_ONLY
    assert usage.check(GUEST, ask('groq')).model == 'groq'


def test_shared_budget_stops_paid_models_for_everyone_but_owners(counts, monkeypatch):
    counts.update(input=600_000, output=100_000)  # $0.60 + $0.50 = $1.10 over the $1 default
    assert usage.check(GUEST, ask()).model == usage.FREE_ONLY
    monkeypatch.setenv('AGENT_OWNER_EMAILS', 'Owner@Example.com, other@example.com')
    owner = User(key='u_' + 'b' * 16, email='owner@example.com')
    assert usage.check(owner, ask('bedrock-haiku')).model == 'bedrock-haiku'


def test_without_an_email_there_are_no_paid_models(counts):
    anonymous = User(key='u_' + 'c' * 16)
    with pytest.raises(HTTPException, match='Sign in'):
        usage.check(anonymous, ask('bedrock-haiku'))
    listed = usage.annotate_models(anonymous, {'routes': [dict(r) for r in ROUTES['routes']]})
    assert [r.get('allowed', True) for r in listed['routes']] == [True, False]


def test_daily_and_minute_limits(counts):
    counts['today'] = 20
    with pytest.raises(HTTPException, match='20 questions today'):
        usage.check(GUEST, ask())
    # Direct ML commands don't call a language model; only the per-minute limit applies to them.
    assert usage.check(GUEST, ask(command='predict')).command == 'predict'
    counts['minute'] = 4
    with pytest.raises(HTTPException, match='a minute'):
        usage.check(GUEST, ask(command='predict'))


def test_local_development_has_no_limits(counts):
    counts.update(today=999, minute=999, paid_today=999)
    assert usage.check(User(key='local'), ask('bedrock-haiku')).model == 'bedrock-haiku'


def test_one_command_at_a_time_per_user():
    with usage.one_at_a_time(GUEST):
        with pytest.raises(HTTPException, match='still running'):
            with usage.one_at_a_time(GUEST):
                pass
    with usage.one_at_a_time(GUEST):  # released afterwards
        pass


def test_anonymous_visitors_get_a_few_free_questions(counts):
    visitor = User(key='a_' + 'c' * 16, anonymous=True)
    assert usage.check(visitor, ask()).model == usage.FREE_ONLY  # never falls back to a paid route
    with pytest.raises(HTTPException, match='Sign in'):
        usage.check(visitor, ask('bedrock-haiku'))
    counts['today'] = 5
    with pytest.raises(HTTPException, match='5 free questions'):
        usage.check(visitor, ask())
    counts.update(today=0, anonymous_today=200)
    with pytest.raises(HTTPException, match='used up for today'):
        usage.check(visitor, ask())
    assert usage.summary(User(key='a_' + 'd' * 16, anonymous=True))['daily_limit'] == 5
